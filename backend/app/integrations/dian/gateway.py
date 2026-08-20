"""Cliente SOAP de DIAN para el ciclo de habilitación de facturación electrónica.

El cliente no comparte el transporte de conectores contables: una transmisión
de factura no se puede reintentar ciegamente. Si la conexión se interrumpe,
el llamador debe consultar el estado antes de volver a enviar el documento.
"""

from __future__ import annotations

import base64
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Callable
from urllib.parse import urlparse
import httpx2 as httpx
from defusedxml import ElementTree
from lxml import etree

from app.integrations.dian.credentials import DianTechnicalCredentials
from app.integrations.dian.ws_security import build_signed_soap_envelope


DIAN_HABILITATION_SERVICE_URL = "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc"

_DIAN_NS = "http://wcf.dian.colombia"
_SEND_TEST_SET_ACTION = "http://wcf.dian.colombia/IWcfDianCustomerServices/SendTestSetAsync"
_GET_STATUS_ZIP_ACTION = "http://wcf.dian.colombia/IWcfDianCustomerServices/GetStatusZip"
_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,118}\.zip$")
_TEST_SET_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,128}$")

ClientFactory = Callable[..., httpx.AsyncClient]


@dataclass(frozen=True)
class DianGatewayResponse:
    """Respuesta normalizada, sin conservar el SOAP ni los datos del documento."""

    track_id: str | None
    status_code: str | None
    status_description: str | None
    status_message: str | None
    error_message: str | None
    is_valid: bool | None


class DianGatewayError(Exception):
    """Fallo seguro de la puerta de enlace, traducible por el servicio de dominio."""

    def __init__(self, code: str, message: str, *, may_have_been_submitted: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.may_have_been_submitted = may_have_been_submitted


class DianHabilitationGateway:
    """Consume únicamente la URL oficial de habilitación de DIAN.

    El software propio de cada empresa usa su ``software_id`` y contraseña
    técnica mediante Basic Auth. El archivo ya debe venir firmado, comprimido
    y listo para enviar; esta clase nunca guarda ni registra credenciales ni
    payloads.
    """

    def __init__(
        self,
        *,
        endpoint_url: str = DIAN_HABILITATION_SERVICE_URL,
        client_factory: ClientFactory = httpx.AsyncClient,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._endpoint_url = self._validate_endpoint(endpoint_url)
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    async def send_test_set_async(
        self,
        *,
        file_name: str,
        zipped_document: bytes,
        test_set_id: str,
        credentials: DianTechnicalCredentials,
    ) -> DianGatewayResponse:
        self._validate_upload(file_name, zipped_document, test_set_id)
        body = etree.Element(etree.QName(_DIAN_NS, "SendTestSetAsync"), nsmap={"wcf": _DIAN_NS})
        etree.SubElement(body, etree.QName(_DIAN_NS, "fileName")).text = file_name
        etree.SubElement(body, etree.QName(_DIAN_NS, "contentFile")).text = base64.b64encode(
            zipped_document
        ).decode("ascii")
        etree.SubElement(body, etree.QName(_DIAN_NS, "testSetId")).text = test_set_id.strip()
        return await self._invoke(
            action=_SEND_TEST_SET_ACTION,
            body=body,
            credentials=credentials,
            may_have_been_submitted_on_network_failure=True,
        )

    async def get_status_zip(
        self,
        *,
        track_id: str,
        credentials: DianTechnicalCredentials,
    ) -> DianGatewayResponse:
        normalized_track_id = track_id.strip()
        if not normalized_track_id or len(normalized_track_id) > 255:
            raise DianGatewayError("VALIDATION_ERROR", "El identificador de seguimiento DIAN no es válido.")
        body = etree.Element(etree.QName(_DIAN_NS, "GetStatusZip"), nsmap={"wcf": _DIAN_NS})
        etree.SubElement(body, etree.QName(_DIAN_NS, "trackId")).text = normalized_track_id
        return await self._invoke(
            action=_GET_STATUS_ZIP_ACTION,
            body=body,
            credentials=credentials,
            may_have_been_submitted_on_network_failure=False,
        )

    async def _invoke(
        self,
        *,
        action: str,
        body: etree._Element,
        credentials: DianTechnicalCredentials,
        may_have_been_submitted_on_network_failure: bool,
    ) -> DianGatewayResponse:
        basic_token = self._basic_credentials(credentials)
        envelope = build_signed_soap_envelope(
            action=action,
            endpoint=self._endpoint_url,
            body=body,
            credentials=credentials,
        )
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "Accept": "application/soap+xml, text/xml",
        }
        try:
            async with self._client_factory(timeout=self._timeout_seconds) as client:
                response = await client.post(self._endpoint_url, headers=headers, content=envelope)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise DianGatewayError(
                "PROVIDER_UNREACHABLE",
                "No fue posible confirmar la respuesta de DIAN.",
                may_have_been_submitted=may_have_been_submitted_on_network_failure,
            ) from exc

        if response.status_code in (401, 403):
            raise DianGatewayError("PROVIDER_AUTH_FAILED", "DIAN no aceptó las credenciales técnicas.")
        if response.status_code == 429 or response.status_code >= 500:
            raise DianGatewayError(
                "SERVICE_UNAVAILABLE",
                "DIAN no está disponible temporalmente.",
                may_have_been_submitted=may_have_been_submitted_on_network_failure,
            )
        if response.status_code >= 400:
            raise DianGatewayError("PROVIDER_ERROR", "DIAN rechazó la solicitud de habilitación.")
        return self._parse_response(response.content)

    @staticmethod
    def _basic_credentials(credentials: DianTechnicalCredentials) -> str:
        if (
            not credentials.software_id.strip()
            or not credentials.software_password
            or len(credentials.software_id) > 512
        ):
            raise DianGatewayError("VALIDATION_ERROR", "Las credenciales DIAN no son válidas.")
        return base64.b64encode(
            f"{credentials.software_id}:{credentials.software_password}".encode("utf-8")
        ).decode("ascii")

    @staticmethod
    def _validate_upload(file_name: str, zipped_document: bytes, test_set_id: str) -> None:
        if not _FILE_NAME_PATTERN.fullmatch(file_name):
            raise DianGatewayError("VALIDATION_ERROR", "El nombre del archivo DIAN no es válido.")
        if not zipped_document or len(zipped_document) > 10_000_000:
            raise DianGatewayError("VALIDATION_ERROR", "El archivo DIAN está vacío o supera el límite permitido.")
        if not zipfile.is_zipfile(BytesIO(zipped_document)):
            raise DianGatewayError("VALIDATION_ERROR", "El documento para DIAN debe ser un archivo ZIP válido.")
        if not _TEST_SET_PATTERN.fullmatch(test_set_id.strip()):
            raise DianGatewayError("VALIDATION_ERROR", "El identificador del set de pruebas DIAN no es válido.")

    @staticmethod
    def _validate_endpoint(value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc.casefold() != "vpfe-hab.dian.gov.co"
            or parsed.path.rstrip("/") != "/WcfDianCustomerServices.svc"
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("La integración solo admite la URL oficial de habilitación DIAN.")
        return value

    @staticmethod
    def _parse_response(content: bytes) -> DianGatewayResponse:
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise DianGatewayError("PROVIDER_ERROR", "DIAN devolvió una respuesta SOAP no compatible.") from exc
        if any(_local_name(element.tag) == "Fault" for element in root.iter()):
            raise DianGatewayError("PROVIDER_ERROR", "DIAN rechazó la solicitud de habilitación.")
        return DianGatewayResponse(
            track_id=_first_text(root, {"zipkey", "trackid"}),
            status_code=_first_text(root, {"statuscode"}),
            status_description=_first_text(root, {"statusdescription"}),
            status_message=_first_text(root, {"statusmessage"}),
            error_message=_first_text(root, {"errormessage"}),
            is_valid=_bool_text(_first_text(root, {"isvalid"})),
        )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _first_text(root: ElementTree.Element, allowed_names: set[str]) -> str | None:
    for element in root.iter():
        if _local_name(element.tag).casefold() not in allowed_names:
            continue
        value = (element.text or "").strip()
        if value:
            return value[:1_000]
    return None


def _bool_text(value: str | None) -> bool | None:
    if value is None:
        return None
    if value.casefold() == "true":
        return True
    if value.casefold() == "false":
        return False
    return None
