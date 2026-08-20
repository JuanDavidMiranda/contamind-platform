"""Contratos seguros del envío de habilitación DIAN.

Estas pruebas no contactan DIAN: verifican que el cliente no reintenta un
envío ambiguo y que solo transmite al extremo oficial de habilitación.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import UTC, datetime, timedelta
import base64
import hashlib

import httpx2 as httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from app.integrations.dian.credentials import DianTechnicalCredentials
from app.integrations.dian.gateway import DianGatewayError, DianHabilitationGateway


_NAMESPACES = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "wsa": "http://www.w3.org/2005/08/addressing",
    "wsse": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
    "wsu": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
}


def _exclusive_c14n(element, prefixes: list[str]) -> bytes:
    return etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
        inclusive_ns_prefixes=prefixes,
    )


def _client_factory(transport: httpx.MockTransport):
    def build_client(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return build_client


def _zip_document() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("fv-hab-1.xml", "<Invoice/>")
    return output.getvalue()


def _credentials() -> DianTechnicalCredentials:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ContaMind DIAN gateway test")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"dian-gateway-test",
        key,
        certificate,
        None,
        BestAvailableEncryption(b"certificate-pass"),
    )
    return DianTechnicalCredentials.from_secret_values(
        {
            "software_id": "software-id",
            "software_password": "software-password",
            "certificate_pfx_base64": base64.b64encode(pfx).decode("ascii"),
            "certificate_password": "certificate-pass",
        }
    )


@pytest.mark.asyncio
async def test_habilitation_submission_uses_official_endpoint_and_normalizes_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "vpfe-hab.dian.gov.co"
        assert request.url.path == "/WcfDianCustomerServices.svc"
        assert request.headers["authorization"].startswith("Basic ")
        assert "SendTestSetAsync" in request.headers["content-type"]
        assert b"SendTestSetAsync" in request.content
        assert b"test-set-123" in request.content
        root = etree.fromstring(request.content)
        to = root.find("soap:Header/wsa:To", namespaces=_NAMESPACES)
        security = root.find("soap:Header/wsse:Security", namespaces=_NAMESPACES)
        assert to is not None and security is not None
        signature = security.find("ds:Signature", namespaces=_NAMESPACES)
        signed_info = signature.find("ds:SignedInfo", namespaces=_NAMESPACES)
        reference = signed_info.find("ds:Reference", namespaces=_NAMESPACES)
        to_id = to.get(f"{{{_NAMESPACES['wsu']}}}Id")
        assert reference.get("URI") == f"#{to_id}"
        assert reference.findtext("ds:DigestValue", namespaces=_NAMESPACES) == base64.b64encode(
            hashlib.sha256(_exclusive_c14n(to, ["soap", "wcf"])).digest()
        ).decode("ascii")
        certificate = x509.load_der_x509_certificate(
            base64.b64decode(security.findtext("wsse:BinarySecurityToken", namespaces=_NAMESPACES))
        )
        certificate.public_key().verify(
            base64.b64decode(signature.findtext("ds:SignatureValue", namespaces=_NAMESPACES)),
            _exclusive_c14n(signed_info, ["soap", "wcf", "wsa"]),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return httpx.Response(
            200,
            content=(
                b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                b"<s:Body><SendTestSetAsyncResponse><SendTestSetAsyncResult>"
                b"<ZipKey>track-123</ZipKey><StatusCode>00</StatusCode>"
                b"<StatusDescription>Procesado</StatusDescription><IsValid>true</IsValid>"
                b"</SendTestSetAsyncResult></SendTestSetAsyncResponse></s:Body></s:Envelope>"
            ),
        )

    gateway = DianHabilitationGateway(client_factory=_client_factory(httpx.MockTransport(handler)))
    result = await gateway.send_test_set_async(
        file_name="fv-hab-1.zip",
        zipped_document=_zip_document(),
        test_set_id="test-set-123",
        credentials=_credentials(),
    )

    assert result.track_id == "track-123"
    assert result.status_code == "00"
    assert result.status_description == "Procesado"
    assert result.is_valid is True


@pytest.mark.asyncio
async def test_ambiguous_submission_is_not_retried_and_requires_status_check():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    gateway = DianHabilitationGateway(client_factory=_client_factory(httpx.MockTransport(handler)))

    with pytest.raises(DianGatewayError) as raised:
        await gateway.send_test_set_async(
            file_name="fv-hab-2.zip",
            zipped_document=_zip_document(),
            test_set_id="test-set-456",
            credentials=_credentials(),
        )

    assert calls == 1
    assert raised.value.code == "PROVIDER_UNREACHABLE"
    assert raised.value.may_have_been_submitted is True


@pytest.mark.asyncio
async def test_status_lookup_can_be_retried_without_marking_document_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    gateway = DianHabilitationGateway(client_factory=_client_factory(httpx.MockTransport(handler)))

    with pytest.raises(DianGatewayError) as raised:
        await gateway.get_status_zip(
            track_id="track-123",
            credentials=_credentials(),
        )

    assert raised.value.code == "PROVIDER_UNREACHABLE"
    assert raised.value.may_have_been_submitted is False


def test_habilitation_gateway_rejects_non_official_endpoint():
    with pytest.raises(ValueError):
        DianHabilitationGateway(endpoint_url="https://example.test/WcfDianCustomerServices.svc")
