"""Firma XML XAdES aislada para documentos UBL de DIAN.

Esta implementación cubre XAdES-BES con RSA-SHA256 y puede emitir XAdES-EPES
cuando el llamador suministra un identificador y *hash* de política ya
verificados. No contiene ni infiere una política oficial de DIAN: esa decisión
debe venir de la configuración controlada y vigente de cada empresa.

Los certificados se reciben solamente como argumentos para la operación de
firma. Este módulo no persiste, registra ni devuelve la clave privada, el PFX
ni su contraseña.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree


_DS_NS: Final = "http://www.w3.org/2000/09/xmldsig#"
_XADES_NS: Final = "http://uri.etsi.org/01903/v1.3.2#"
_EXT_NS: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
_UBL_NAMESPACE_PREFIX: Final = "urn:oasis:names:specification:ubl:schema:xsd:"
_EXCLUSIVE_C14N: Final = "http://www.w3.org/2001/10/xml-exc-c14n#"
_ENVELOPED_SIGNATURE_TRANSFORM: Final = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_RSA_SHA256: Final = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256_DIGEST: Final = "http://www.w3.org/2001/04/xmlenc#sha256"
_SIGNED_PROPERTIES_TYPE: Final = "http://uri.etsi.org/01903#SignedProperties"
_MAX_XML_BYTES: Final = 10_000_000
_MAX_PFX_BASE64_CHARS: Final = 20_000_000


class DianXadesSigningError(ValueError):
    """Error seguro de firma, sin datos sensibles en el mensaje."""


@dataclass(frozen=True, slots=True)
class DianXadesSignaturePolicy:
    """Política opcional para producir XAdES-EPES.

    ``digest_sha256_base64`` debe ser el SHA-256 de la política que la empresa
    haya validado por su proceso de habilitación. El módulo no aporta valores
    predeterminados ni declara que una política sea oficial de DIAN.
    """

    identifier: str
    digest_sha256_base64: str
    qualifier_url: str | None = None


@dataclass(frozen=True, slots=True)
class DianXadesSignedDocument:
    """Artefacto firmado y su integridad sobre la serialización devuelta."""

    signed_xml: bytes
    sha256: str
    signature_id: str


@dataclass(frozen=True, slots=True)
class _SignatureParts:
    signature: etree._Element
    document_digest: etree._Element
    signed_properties: etree._Element
    signed_properties_digest: etree._Element
    signed_info: etree._Element
    signature_value: etree._Element


class DianXadesSigner:
    """Genera una firma enveloped XMLDSig con propiedades XAdES.

    La firma se inserta en una extensión UBL dedicada. Un documento que ya
    contiene ``ds:Signature`` se rechaza para evitar una segunda firma ambigua;
    la renovación o cofirma exige un flujo explícito distinto.
    """

    def sign(
        self,
        *,
        xml: bytes,
        certificate_pfx_base64: str,
        certificate_password: str | bytes,
        signature_policy: DianXadesSignaturePolicy | None = None,
        signing_time: datetime | None = None,
    ) -> DianXadesSignedDocument:
        """Firma un XML UBL y devuelve sus bytes finales junto con SHA-256.

        ``signing_time`` permite inyectar una hora consciente de zona horaria
        en pruebas o procesos auditables. Si se omite, se usa la hora UTC actual.
        """

        root = _parse_ubl_xml(xml)
        private_key, certificate = _load_signing_material(
            certificate_pfx_base64=certificate_pfx_base64,
            certificate_password=certificate_password,
        )
        normalized_time = _normalize_signing_time(signing_time)
        policy = _normalize_signature_policy(signature_policy)

        signature_id = f"Signature-{uuid4().hex}"
        signed_properties_id = f"SignedProperties-{uuid4().hex}"
        extension_content = _create_signature_extension(root)
        parts = _create_signature(
            certificate=certificate,
            signature_id=signature_id,
            signed_properties_id=signed_properties_id,
            signing_time=normalized_time,
            signature_policy=policy,
        )
        extension_content.append(parts.signature)

        parts.document_digest.text = _digest_base64(_canonical_document_without_signature(root, parts.signature))
        parts.signed_properties_digest.text = _digest_base64(_exclusive_c14n(parts.signed_properties))
        parts.signature_value.text = base64.b64encode(
            private_key.sign(
                _exclusive_c14n(parts.signed_info),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        ).decode("ascii")

        signed_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        return DianXadesSignedDocument(
            signed_xml=signed_xml,
            sha256=hashlib.sha256(signed_xml).hexdigest(),
            signature_id=signature_id,
        )


def sign_dian_ubl_xades(
    *,
    xml: bytes,
    certificate_pfx_base64: str,
    certificate_password: str | bytes,
    signature_policy: DianXadesSignaturePolicy | None = None,
    signing_time: datetime | None = None,
) -> DianXadesSignedDocument:
    """Atajo para firmar un documento UBL de DIAN con XAdES-BES/EPES."""

    return DianXadesSigner().sign(
        xml=xml,
        certificate_pfx_base64=certificate_pfx_base64,
        certificate_password=certificate_password,
        signature_policy=signature_policy,
        signing_time=signing_time,
    )


def _parse_ubl_xml(xml: bytes) -> etree._Element:
    if not isinstance(xml, bytes) or not xml or len(xml) > _MAX_XML_BYTES:
        raise DianXadesSigningError("El XML UBL está vacío o supera el tamaño permitido.")
    if b"<!doctype" in xml.lower():
        raise DianXadesSigningError("El XML UBL no puede incluir declaraciones DTD.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise DianXadesSigningError("El XML UBL no tiene una estructura válida.") from exc

    namespace = etree.QName(root).namespace
    if namespace is None or not namespace.startswith(_UBL_NAMESPACE_PREFIX):
        raise DianXadesSigningError("Solo se pueden firmar documentos UBL compatibles con DIAN.")
    if root.xpath(".//ds:Signature", namespaces={"ds": _DS_NS}):
        raise DianXadesSigningError("El XML ya contiene una firma y no puede firmarse de nuevo.")
    return root


def _load_signing_material(
    *, certificate_pfx_base64: str, certificate_password: str | bytes
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    if not isinstance(certificate_pfx_base64, str) or not certificate_pfx_base64.strip():
        raise DianXadesSigningError("El certificado de firma no tiene un formato válido.")
    if len(certificate_pfx_base64) > _MAX_PFX_BASE64_CHARS:
        raise DianXadesSigningError("El certificado de firma supera el tamaño permitido.")
    if isinstance(certificate_password, str):
        password = certificate_password.encode("utf-8")
    elif isinstance(certificate_password, bytes):
        password = certificate_password
    else:
        raise DianXadesSigningError("La contraseña del certificado no tiene un formato válido.")

    try:
        pfx = base64.b64decode(certificate_pfx_base64.strip(), validate=True)
        private_key, certificate, _ = pkcs12.load_key_and_certificates(pfx, password)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise DianXadesSigningError("No fue posible abrir el certificado de firma.") from exc

    if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(certificate, x509.Certificate):
        raise DianXadesSigningError("El certificado de firma debe usar una clave RSA válida.")
    certificate_public_key = certificate.public_key()
    if not isinstance(certificate_public_key, rsa.RSAPublicKey):
        raise DianXadesSigningError("El certificado de firma debe usar una clave RSA válida.")
    if private_key.public_key().public_numbers() != certificate_public_key.public_numbers():
        raise DianXadesSigningError("La clave privada no corresponde al certificado de firma.")

    now = datetime.now(UTC)
    not_valid_before, not_valid_after = _certificate_validity_utc(certificate)
    if now < not_valid_before or now > not_valid_after:
        raise DianXadesSigningError("El certificado de firma no se encuentra vigente.")
    return private_key, certificate


def _certificate_validity_utc(certificate: x509.Certificate) -> tuple[datetime, datetime]:
    """Compatibilidad con las propiedades UTC de cryptography actuales y previas."""

    not_valid_before = getattr(certificate, "not_valid_before_utc", None)
    not_valid_after = getattr(certificate, "not_valid_after_utc", None)
    if not_valid_before is None:
        not_valid_before = certificate.not_valid_before.replace(tzinfo=UTC)
    if not_valid_after is None:
        not_valid_after = certificate.not_valid_after.replace(tzinfo=UTC)
    return not_valid_before.astimezone(UTC), not_valid_after.astimezone(UTC)


def _normalize_signing_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DianXadesSigningError("La fecha de firma debe incluir una zona horaria.")
    return value.astimezone(UTC).replace(microsecond=0)


def _normalize_signature_policy(
    policy: DianXadesSignaturePolicy | None,
) -> DianXadesSignaturePolicy | None:
    if policy is None:
        return None
    if not isinstance(policy, DianXadesSignaturePolicy):
        raise DianXadesSigningError("La política de firma no tiene un formato válido.")
    identifier = policy.identifier.strip() if isinstance(policy.identifier, str) else ""
    if not identifier or len(identifier) > 2_048:
        raise DianXadesSigningError("El identificador de política de firma no es válido.")
    if any(ord(character) < 0x20 for character in identifier):
        raise DianXadesSigningError("El identificador de política de firma no es válido.")
    try:
        digest = base64.b64decode(policy.digest_sha256_base64, validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise DianXadesSigningError("El hash de política de firma no es válido.") from exc
    if len(digest) != hashes.SHA256().digest_size:
        raise DianXadesSigningError("El hash de política debe ser SHA-256 codificado en base64.")

    qualifier_url = policy.qualifier_url
    if qualifier_url is not None:
        if not isinstance(qualifier_url, str) or not qualifier_url.strip() or len(qualifier_url) > 2_048:
            raise DianXadesSigningError("La URL calificadora de política no es válida.")
        qualifier_url = qualifier_url.strip()
    return DianXadesSignaturePolicy(
        identifier=identifier,
        digest_sha256_base64=base64.b64encode(digest).decode("ascii"),
        qualifier_url=qualifier_url,
    )


def _create_signature_extension(root: etree._Element) -> etree._Element:
    extensions = root.find(etree.QName(_EXT_NS, "UBLExtensions"))
    if extensions is None:
        extensions = etree.Element(etree.QName(_EXT_NS, "UBLExtensions"))
        root.insert(0, extensions)
    extension = etree.SubElement(extensions, etree.QName(_EXT_NS, "UBLExtension"))
    return etree.SubElement(extension, etree.QName(_EXT_NS, "ExtensionContent"))


def _create_signature(
    *,
    certificate: x509.Certificate,
    signature_id: str,
    signed_properties_id: str,
    signing_time: datetime,
    signature_policy: DianXadesSignaturePolicy | None,
) -> _SignatureParts:
    signature = etree.Element(
        etree.QName(_DS_NS, "Signature"),
        nsmap={"ds": _DS_NS, "xades": _XADES_NS},
        Id=signature_id,
    )
    signed_info = etree.SubElement(signature, etree.QName(_DS_NS, "SignedInfo"))
    etree.SubElement(
        signed_info,
        etree.QName(_DS_NS, "CanonicalizationMethod"),
        Algorithm=_EXCLUSIVE_C14N,
    )
    etree.SubElement(signed_info, etree.QName(_DS_NS, "SignatureMethod"), Algorithm=_RSA_SHA256)

    document_reference = etree.SubElement(signed_info, etree.QName(_DS_NS, "Reference"), URI="")
    document_reference.set("Id", f"Reference-{uuid4().hex}")
    transforms = etree.SubElement(document_reference, etree.QName(_DS_NS, "Transforms"))
    etree.SubElement(
        transforms,
        etree.QName(_DS_NS, "Transform"),
        Algorithm=_ENVELOPED_SIGNATURE_TRANSFORM,
    )
    etree.SubElement(transforms, etree.QName(_DS_NS, "Transform"), Algorithm=_EXCLUSIVE_C14N)
    etree.SubElement(document_reference, etree.QName(_DS_NS, "DigestMethod"), Algorithm=_SHA256_DIGEST)
    document_digest = etree.SubElement(document_reference, etree.QName(_DS_NS, "DigestValue"))

    properties_reference = etree.SubElement(
        signed_info,
        etree.QName(_DS_NS, "Reference"),
        Type=_SIGNED_PROPERTIES_TYPE,
        URI=f"#{signed_properties_id}",
    )
    properties_transforms = etree.SubElement(properties_reference, etree.QName(_DS_NS, "Transforms"))
    etree.SubElement(properties_transforms, etree.QName(_DS_NS, "Transform"), Algorithm=_EXCLUSIVE_C14N)
    etree.SubElement(properties_reference, etree.QName(_DS_NS, "DigestMethod"), Algorithm=_SHA256_DIGEST)
    signed_properties_digest = etree.SubElement(properties_reference, etree.QName(_DS_NS, "DigestValue"))

    signature_value = etree.SubElement(signature, etree.QName(_DS_NS, "SignatureValue"))
    signature_value.set("Id", f"SignatureValue-{uuid4().hex}")
    _append_key_info(signature, certificate)

    signature_object = etree.SubElement(signature, etree.QName(_DS_NS, "Object"))
    qualifying_properties = etree.SubElement(
        signature_object,
        etree.QName(_XADES_NS, "QualifyingProperties"),
        Target=f"#{signature_id}",
    )
    signed_properties = etree.SubElement(
        qualifying_properties,
        etree.QName(_XADES_NS, "SignedProperties"),
        Id=signed_properties_id,
    )
    signed_signature_properties = etree.SubElement(
        signed_properties,
        etree.QName(_XADES_NS, "SignedSignatureProperties"),
    )
    etree.SubElement(signed_signature_properties, etree.QName(_XADES_NS, "SigningTime")).text = (
        signing_time.isoformat().replace("+00:00", "Z")
    )
    _append_signing_certificate(signed_signature_properties, certificate)
    if signature_policy is not None:
        _append_signature_policy(signed_signature_properties, signature_policy)

    return _SignatureParts(
        signature=signature,
        document_digest=document_digest,
        signed_properties=signed_properties,
        signed_properties_digest=signed_properties_digest,
        signed_info=signed_info,
        signature_value=signature_value,
    )


def _append_key_info(parent: etree._Element, certificate: x509.Certificate) -> None:
    key_info = etree.SubElement(parent, etree.QName(_DS_NS, "KeyInfo"))
    x509_data = etree.SubElement(key_info, etree.QName(_DS_NS, "X509Data"))
    certificate_der = certificate.public_bytes(serialization.Encoding.DER)
    etree.SubElement(x509_data, etree.QName(_DS_NS, "X509Certificate")).text = base64.b64encode(
        certificate_der
    ).decode("ascii")


def _append_signing_certificate(parent: etree._Element, certificate: x509.Certificate) -> None:
    signing_certificate = etree.SubElement(parent, etree.QName(_XADES_NS, "SigningCertificate"))
    cert = etree.SubElement(signing_certificate, etree.QName(_XADES_NS, "Cert"))
    cert_digest = etree.SubElement(cert, etree.QName(_XADES_NS, "CertDigest"))
    etree.SubElement(cert_digest, etree.QName(_DS_NS, "DigestMethod"), Algorithm=_SHA256_DIGEST)
    certificate_der = certificate.public_bytes(serialization.Encoding.DER)
    etree.SubElement(cert_digest, etree.QName(_DS_NS, "DigestValue")).text = _digest_base64(certificate_der)
    issuer_serial = etree.SubElement(cert, etree.QName(_XADES_NS, "IssuerSerial"))
    etree.SubElement(issuer_serial, etree.QName(_DS_NS, "X509IssuerName")).text = (
        certificate.issuer.rfc4514_string()
    )
    etree.SubElement(issuer_serial, etree.QName(_DS_NS, "X509SerialNumber")).text = str(certificate.serial_number)


def _append_signature_policy(parent: etree._Element, policy: DianXadesSignaturePolicy) -> None:
    policy_identifier = etree.SubElement(parent, etree.QName(_XADES_NS, "SignaturePolicyIdentifier"))
    policy_id = etree.SubElement(policy_identifier, etree.QName(_XADES_NS, "SignaturePolicyId"))
    sig_policy_id = etree.SubElement(policy_id, etree.QName(_XADES_NS, "SigPolicyId"))
    etree.SubElement(sig_policy_id, etree.QName(_XADES_NS, "Identifier")).text = policy.identifier
    policy_hash = etree.SubElement(policy_id, etree.QName(_XADES_NS, "SigPolicyHash"))
    etree.SubElement(policy_hash, etree.QName(_DS_NS, "DigestMethod"), Algorithm=_SHA256_DIGEST)
    etree.SubElement(policy_hash, etree.QName(_DS_NS, "DigestValue")).text = policy.digest_sha256_base64
    if policy.qualifier_url is not None:
        qualifiers = etree.SubElement(policy_id, etree.QName(_XADES_NS, "SigPolicyQualifiers"))
        qualifier = etree.SubElement(qualifiers, etree.QName(_XADES_NS, "SigPolicyQualifier"))
        etree.SubElement(qualifier, etree.QName(_XADES_NS, "SPURI")).text = policy.qualifier_url


def _canonical_document_without_signature(root: etree._Element, signature: etree._Element) -> bytes:
    parent = signature.getparent()
    if parent is None:
        raise DianXadesSigningError("No fue posible preparar la firma XML.")
    parent.remove(signature)
    try:
        return _exclusive_c14n(root)
    finally:
        parent.append(signature)


def _exclusive_c14n(element: etree._Element) -> bytes:
    try:
        return etree.tostring(element, method="c14n", exclusive=True, with_comments=False)
    except (TypeError, ValueError) as exc:
        raise DianXadesSigningError("No fue posible canonizar el XML para la firma.") from exc


def _digest_base64(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")
