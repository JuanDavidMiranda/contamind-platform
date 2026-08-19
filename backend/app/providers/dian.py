"""Adaptador fiscal DIAN para la consulta individual GetAcquirer.

El servicio está limitado a completar nombre/razón social y correo durante la
emisión de una factura electrónica. No es una consulta general de RUT ni un
mecanismo de enriquecimiento masivo de terceros.
"""

import base64
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import httpx2 as httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from defusedxml import ElementTree
from lxml import etree

from app.config.settings import settings
from app.providers.canonical import Party, PartyType, ProviderContext, ProviderKind
from app.providers.ports import FiscalProviderPort
from app.providers.secrets import ProviderSecret
from app.providers.transport import ProviderHttpClient
from app.shared.errors import app_error

_DOCUMENT_TYPES = frozenset({"11", "12", "13", "21", "22", "31", "41", "42", "47", "48", "50", "91"})
_DOCUMENT_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,50}$")
_REQUIRED_SECRET_FIELDS = frozenset(
    {"software_id", "software_password", "certificate_pfx_base64", "certificate_password"}
)

_SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
_WSSE_NS = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-secext-1.0.xsd"
)
_WSU_NS = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-wssecurity-utility-1.0.xsd"
)
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_DIAN_NS = "http://wcf.dian.colombia"
_WSA_NS = "http://www.w3.org/2005/08/addressing"
_EC_NS = "http://www.w3.org/2001/10/xml-exc-c14n#"
_GET_ACQUIRER_ACTION = "http://wcf.dian.colombia/IWcfDianCustomerServices/GetAcquirer"

_EXCLUSIVE_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_X509_VALUE_TYPE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
_BASE64_ENCODING_TYPE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"

ClientFactory = Callable[..., httpx.AsyncClient]


class DianAcquirerAdapter(FiscalProviderPort):
    """Cliente SOAP 1.2 para GetAcquirer con firma WS-Security por solicitud.

    Las cuatro credenciales se reciben solo desde ``ProviderSecret``. El
    certificado PKCS#12 y su clave privada se usan en memoria para firmar y no
    se escriben en disco, logs, respuestas ni auditorías.
    """

    provider = ProviderKind.DIAN

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        client_factory: ClientFactory = httpx.AsyncClient,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._endpoint_url = endpoint_url if endpoint_url is not None else settings.DIAN_ACQUIRER_URL
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    async def get_acquirer_information(
        self,
        context: ProviderContext,
        secret: ProviderSecret,
        document_type: str,
        document_number: str,
    ) -> Party:
        self._validate_query(document_type, document_number)
        credentials = _DianCredentials.from_secret(secret)
        endpoint = self._validated_endpoint()
        envelope = self._build_envelope(credentials, document_type, document_number, endpoint)
        response = await self._request(context, endpoint, credentials, envelope)
        name, email = self._parse_response(response)
        return Party(
            company_id=context.company_id,
            party_type=PartyType.CUSTOMER,
            name=name,
            document_type=document_type,
            document_number=document_number,
            email=email,
            external_id=None,
            integration_id=f"{context.company_id}:{self.provider}:get-acquirer",
        )

    def _validated_endpoint(self) -> str:
        if not self._endpoint_url:
            raise app_error(
                "DEPENDENCY_DISABLED",
                message="La URL de GetAcquirer DIAN no está configurada en este ambiente.",
                details={"provider": self.provider},
            )
        parsed = urlparse(self._endpoint_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise app_error(
                "VALIDATION_ERROR",
                message="La URL configurada para GetAcquirer debe usar HTTPS.",
                details={"provider": self.provider},
            )
        # En el catálogo el participante puede recibir la URL WSDL, mientras
        # que la llamada SOAP debe dirigirse al servicio .svc sin ``?wsdl``.
        query = "" if parsed.query.casefold().rstrip("=") == "wsdl" else parsed.query
        return urlunparse(parsed._replace(query=query, fragment=""))

    async def _request(
        self,
        context: ProviderContext,
        endpoint: str,
        credentials: "_DianCredentials",
        envelope: bytes,
    ) -> httpx.Response:
        basic_token = base64.b64encode(
            f"{credentials.software_id}:{credentials.software_password}".encode("utf-8")
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{_GET_ACQUIRER_ACTION}"',
            "Accept": "application/soap+xml, text/xml",
        }
        async with self._client_factory(timeout=self._timeout_seconds) as client:
            transport = ProviderHttpClient(client)
            return await transport.request(
                context,
                "POST",
                endpoint,
                headers=headers,
                content=envelope,
            )

    @staticmethod
    def _build_envelope(
        credentials: "_DianCredentials",
        document_type: str,
        document_number: str,
        endpoint: str,
    ) -> bytes:
        """Construye el sobre que configura la guía DIAN para GetAcquirer.

        Se firma únicamente ``wsa:To`` con canonicalización exclusiva y los
        prefijos inclusivos configurados en la guía. El servicio requiere además
        ``wsa:Action``, Basic Auth, BinarySecurityToken y un Timestamp de 60 s
        con precisión de milisegundos. No se persiste ninguno de esos secretos.
        """

        issued_at = datetime.now(UTC)
        created = _timestamp_value(issued_at)
        expires = _timestamp_value(issued_at + timedelta(seconds=60))
        to_id = f"id-{uuid4()}"
        timestamp_id = f"TS-{uuid4()}"
        token_id = f"X509-{uuid4()}"
        signature_id = f"SIG-{uuid4()}"

        nsmap = {
            "soap": _SOAP_NS,
            "wcf": _DIAN_NS,
            "wsa": _WSA_NS,
            "wsse": _WSSE_NS,
            "wsu": _WSU_NS,
            "ds": _DS_NS,
            "ec": _EC_NS,
        }
        envelope = etree.Element(etree.QName(_SOAP_NS, "Envelope"), nsmap=nsmap)
        header = etree.SubElement(envelope, etree.QName(_SOAP_NS, "Header"))
        action = etree.SubElement(header, etree.QName(_WSA_NS, "Action"))
        action.text = _GET_ACQUIRER_ACTION
        to = etree.SubElement(header, etree.QName(_WSA_NS, "To"))
        to.set(etree.QName(_WSU_NS, "Id"), to_id)
        to.text = endpoint

        body = etree.SubElement(envelope, etree.QName(_SOAP_NS, "Body"))
        request = etree.SubElement(body, etree.QName(_DIAN_NS, "GetAcquirer"))
        etree.SubElement(request, etree.QName(_DIAN_NS, "identificationType")).text = document_type
        etree.SubElement(request, etree.QName(_DIAN_NS, "identificationNumber")).text = document_number

        security = etree.SubElement(header, etree.QName(_WSSE_NS, "Security"))
        security.set(etree.QName(_SOAP_NS, "mustUnderstand"), "true")
        token = etree.SubElement(security, etree.QName(_WSSE_NS, "BinarySecurityToken"))
        token.set("EncodingType", _BASE64_ENCODING_TYPE)
        token.set("ValueType", _X509_VALUE_TYPE)
        token.set(etree.QName(_WSU_NS, "Id"), token_id)
        token.text = base64.b64encode(
            credentials.certificate.public_bytes(serialization.Encoding.DER)
        ).decode("ascii")

        signature = etree.SubElement(security, etree.QName(_DS_NS, "Signature"))
        signature.set("Id", signature_id)
        signed_info = etree.SubElement(signature, etree.QName(_DS_NS, "SignedInfo"))
        canonicalization = etree.SubElement(
            signed_info, etree.QName(_DS_NS, "CanonicalizationMethod")
        )
        canonicalization.set("Algorithm", _EXCLUSIVE_C14N)
        inclusive = etree.SubElement(canonicalization, etree.QName(_EC_NS, "InclusiveNamespaces"))
        inclusive.set("PrefixList", "soap wcf wsa")
        signature_method = etree.SubElement(signed_info, etree.QName(_DS_NS, "SignatureMethod"))
        signature_method.set("Algorithm", _RSA_SHA256)
        reference = etree.SubElement(signed_info, etree.QName(_DS_NS, "Reference"))
        reference.set("URI", f"#{to_id}")
        transforms = etree.SubElement(reference, etree.QName(_DS_NS, "Transforms"))
        transform = etree.SubElement(transforms, etree.QName(_DS_NS, "Transform"))
        transform.set("Algorithm", _EXCLUSIVE_C14N)
        transform_inclusive = etree.SubElement(transform, etree.QName(_EC_NS, "InclusiveNamespaces"))
        transform_inclusive.set("PrefixList", "soap wcf")
        digest_method = etree.SubElement(reference, etree.QName(_DS_NS, "DigestMethod"))
        digest_method.set("Algorithm", _SHA256)
        etree.SubElement(reference, etree.QName(_DS_NS, "DigestValue"))
        etree.SubElement(signature, etree.QName(_DS_NS, "SignatureValue"))
        key_info = etree.SubElement(signature, etree.QName(_DS_NS, "KeyInfo"))
        token_reference = etree.SubElement(key_info, etree.QName(_WSSE_NS, "SecurityTokenReference"))
        token_reference.set(etree.QName(_WSU_NS, "Id"), f"STR-{uuid4()}")
        token_reference_value = etree.SubElement(token_reference, etree.QName(_WSSE_NS, "Reference"))
        token_reference_value.set("URI", f"#{token_id}")
        token_reference_value.set("ValueType", _X509_VALUE_TYPE)

        timestamp = etree.SubElement(security, etree.QName(_WSU_NS, "Timestamp"))
        timestamp.set(etree.QName(_WSU_NS, "Id"), timestamp_id)
        etree.SubElement(timestamp, etree.QName(_WSU_NS, "Created")).text = created
        etree.SubElement(timestamp, etree.QName(_WSU_NS, "Expires")).text = expires

        # Firma sobre el documento ya serializado: la canonicalización debe usar
        # exactamente el mismo árbol de namespaces que recibirá DIAN.
        wire_envelope = etree.fromstring(etree.tostring(envelope, encoding="utf-8"))
        wire_to = wire_envelope.find("soap:Header/wsa:To", namespaces=nsmap)
        wire_signed_info = wire_envelope.find(".//ds:SignedInfo", namespaces=nsmap)
        wire_digest_value = wire_envelope.find(".//ds:DigestValue", namespaces=nsmap)
        wire_signature_value = wire_envelope.find(".//ds:SignatureValue", namespaces=nsmap)
        assert wire_to is not None
        assert wire_signed_info is not None
        assert wire_digest_value is not None
        assert wire_signature_value is not None
        wire_digest_value.text = _digest(wire_to, inclusive_prefixes=("soap", "wcf"))
        signed_info_bytes = _canonicalize(
            wire_signed_info, inclusive_prefixes=("soap", "wcf", "wsa")
        )
        wire_signature_value.text = base64.b64encode(
            credentials.private_key.sign(signed_info_bytes, padding.PKCS1v15(), hashes.SHA256())
        ).decode("ascii")
        return etree.tostring(wire_envelope, xml_declaration=True, encoding="utf-8")

    @staticmethod
    def _validate_query(document_type: str, document_number: str) -> None:
        if document_type not in _DOCUMENT_TYPES:
            raise app_error(
                "VALIDATION_ERROR",
                message="El tipo de documento no está permitido para la consulta DIAN.",
                details={"field": "document_type"},
            )
        if not _DOCUMENT_NUMBER_PATTERN.fullmatch(document_number):
            raise app_error(
                "VALIDATION_ERROR",
                message="El número de documento no tiene un formato válido para la consulta DIAN.",
                details={"field": "document_number"},
            )

    @staticmethod
    def _parse_response(response: httpx.Response) -> tuple[str, str | None]:
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise app_error(
                "PROVIDER_ERROR",
                message="DIAN respondió un contenido SOAP no compatible.",
                details={"provider": ProviderKind.DIAN},
            ) from exc

        if any(_local_name(element.tag) == "Fault" for element in root.iter()):
            raise app_error(
                "PROVIDER_ERROR",
                message="DIAN rechazó la consulta de adquiriente.",
                details={"provider": ProviderKind.DIAN},
            )

        name = _first_text(root, {"name", "fullname", "businessname", "legalname"})
        email = _first_text(root, {"email", "emailaddress"})
        if not name:
            raise app_error(
                "PROVIDER_ERROR",
                message="DIAN no devolvió el nombre o razón social del adquiriente.",
                details={"provider": ProviderKind.DIAN},
            )
        return name, email


class _DianCredentials:
    """Material efímero para firmar una solicitud, sin representación imprimible."""

    def __init__(
        self,
        *,
        software_id: str,
        software_password: str,
        private_key: rsa.RSAPrivateKey,
        certificate: x509.Certificate,
    ) -> None:
        self.software_id = software_id
        self.software_password = software_password
        self.private_key = private_key
        self.certificate = certificate

    @classmethod
    def from_secret(cls, secret: ProviderSecret) -> "_DianCredentials":
        missing = sorted(_REQUIRED_SECRET_FIELDS.difference(secret.values))
        if missing:
            raise app_error(
                "VALIDATION_ERROR",
                message="Faltan campos obligatorios de la credencial DIAN.",
                details={"fields": missing},
            )
        try:
            raw_pfx = base64.b64decode(secret.values["certificate_pfx_base64"], validate=True)
            key, certificate, _ = pkcs12.load_key_and_certificates(
                raw_pfx, secret.values["certificate_password"].encode("utf-8")
            )
        except (ValueError, TypeError) as exc:
            raise app_error(
                "VALIDATION_ERROR",
                message="El certificado DIAN no tiene un formato PKCS#12 válido.",
                details={"field": "certificate_pfx_base64"},
            ) from exc
        if not isinstance(key, rsa.RSAPrivateKey) or certificate is None:
            raise app_error(
                "VALIDATION_ERROR",
                message="El certificado DIAN debe incluir una clave privada RSA y un certificado vigente.",
                details={"field": "certificate_pfx_base64"},
            )
        now = datetime.now(UTC)
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise app_error(
                "VALIDATION_ERROR",
                message="El certificado DIAN no está vigente para firmar la consulta.",
                details={"field": "certificate_pfx_base64"},
            )
        return cls(
            software_id=secret.values["software_id"],
            software_password=secret.values["software_password"],
            private_key=key,
            certificate=certificate,
        )


def _timestamp_value(value: datetime) -> str:
    """Emite el Timestamp con la precisión a milisegundos de la guía DIAN."""

    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonicalize(element: Any, *, inclusive_prefixes: tuple[str, ...]) -> bytes:
    """Canonicalización exclusiva XML requerida antes de resumir o firmar."""

    return etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
        inclusive_ns_prefixes=list(inclusive_prefixes),
    )


def _digest(element: Any, *, inclusive_prefixes: tuple[str, ...]) -> str:
    return base64.b64encode(
        hashlib.sha256(_canonicalize(element, inclusive_prefixes=inclusive_prefixes)).digest()
    ).decode("ascii")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _first_text(root: Any, allowed_names: set[str]) -> str | None:
    for element in root.iter():
        if _local_name(element.tag).lower() not in allowed_names:
            continue
        value = (element.text or "").strip()
        if value:
            return value
    return None
