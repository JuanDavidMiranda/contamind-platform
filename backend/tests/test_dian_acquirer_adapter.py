import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2 as httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from app.providers.canonical import ProviderContext, ProviderKind
from app.providers.dian import DianAcquirerAdapter
from app.providers.secrets import ProviderSecret
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def _context() -> ProviderContext:
    return ProviderContext(tenant_id=uuid4(), company_id=uuid4(), provider=ProviderKind.DIAN)


def _secret(
    *,
    not_valid_before: datetime | None = None,
    not_valid_after: datetime | None = None,
) -> ProviderSecret:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ContaMind DIAN test")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before or datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(not_valid_after or datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"contamind-dian-test",
        key,
        certificate,
        None,
        BestAvailableEncryption(b"certificate-pass"),
    )
    return ProviderSecret(
        {
            "software_id": "software-test-id",
            "software_password": "software-test-password",
            "certificate_pfx_base64": base64.b64encode(pfx).decode("ascii"),
            "certificate_password": "certificate-pass",
        }
    )


def _client_factory(transport: httpx.MockTransport):
    def build_client(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return build_client


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


@pytest.mark.asyncio
async def test_get_acquirer_signs_and_maps_only_authorized_fields():
    secret = _secret()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://dian.contract.test/WcfDianCustomerServices.svc"
        assert request.headers["content-type"] == (
            'application/soap+xml; charset=utf-8; action="'
            "http://wcf.dian.colombia/IWcfDianCustomerServices/GetAcquirer\""
        )
        assert request.headers["authorization"].startswith("Basic ")
        assert b"<wcf:identificationType>31</wcf:identificationType>" in request.content
        assert b"<wcf:identificationNumber>900123456</wcf:identificationNumber>" in request.content
        root = etree.fromstring(request.content)
        assert root.findtext("soap:Header/wsa:Action", namespaces=_NAMESPACES) == (
            "http://wcf.dian.colombia/IWcfDianCustomerServices/GetAcquirer"
        )
        to = root.find("soap:Header/wsa:To", namespaces=_NAMESPACES)
        assert to is not None
        assert to.text == "https://dian.contract.test/WcfDianCustomerServices.svc"
        to_id = to.get("{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Id")
        assert to_id

        security = root.find("soap:Header/wsse:Security", namespaces=_NAMESPACES)
        assert security is not None
        assert [etree.QName(item).localname for item in security] == [
            "BinarySecurityToken", "Signature", "Timestamp"
        ]
        signature = security.find("ds:Signature", namespaces=_NAMESPACES)
        signed_info = signature.find("ds:SignedInfo", namespaces=_NAMESPACES)
        reference = signed_info.find("ds:Reference", namespaces=_NAMESPACES)
        assert reference.get("URI") == f"#{to_id}"
        assert len(signed_info.findall("ds:Reference", namespaces=_NAMESPACES)) == 1
        digest = reference.findtext("ds:DigestValue", namespaces=_NAMESPACES)
        assert digest == base64.b64encode(
            hashlib.sha256(_exclusive_c14n(to, ["soap", "wcf"])).digest()
        ).decode("ascii")
        binary_token = security.findtext("wsse:BinarySecurityToken", namespaces=_NAMESPACES)
        certificate = x509.load_der_x509_certificate(base64.b64decode(binary_token))
        certificate.public_key().verify(
            base64.b64decode(signature.findtext("ds:SignatureValue", namespaces=_NAMESPACES)),
            _exclusive_c14n(signed_info, ["soap", "wcf", "wsa"]),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        created = datetime.fromisoformat(
            security.findtext("wsu:Timestamp/wsu:Created", namespaces=_NAMESPACES).replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            security.findtext("wsu:Timestamp/wsu:Expires", namespaces=_NAMESPACES).replace("Z", "+00:00")
        )
        assert expires - created == timedelta(seconds=60)
        assert created.microsecond % 1_000 == 0
        return httpx.Response(
            200,
            content=(
                b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                b"<s:Body><GetAcquirerResponse><GetAcquirerResult>"
                b"<Name>Cliente DIAN S.A.S.</Name><Email>cliente@example.test</Email>"
                b"<Phone>6010000000</Phone></GetAcquirerResult></GetAcquirerResponse>"
                b"</s:Body></s:Envelope>"
            ),
        )

    adapter = DianAcquirerAdapter(
        endpoint_url="https://dian.contract.test/WcfDianCustomerServices.svc?wsdl=",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )
    party = await adapter.get_acquirer_information(_context(), secret, "31", "900123456")

    assert party.name == "Cliente DIAN S.A.S."
    assert party.email == "cliente@example.test"
    assert party.phone is None
    assert party.address is None
    assert party.fiscal_responsibility is None


@pytest.mark.asyncio
async def test_get_acquirer_rejects_a_soap_fault_without_exposing_provider_payload():
    secret = _secret()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                b"<s:Body><s:Fault><s:Reason><s:Text>confidential diagnostic</s:Text>"
                b"</s:Reason></s:Fault></s:Body></s:Envelope>"
            ),
        )

    adapter = DianAcquirerAdapter(
        endpoint_url="https://dian.contract.test/GetAcquirer",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AppError) as error:
        await adapter.get_acquirer_information(_context(), secret, "31", "900123456")

    assert error.value.code == "PROVIDER_ERROR"
    assert "confidential diagnostic" not in error.value.message


@pytest.mark.asyncio
async def test_get_acquirer_rejects_an_invalid_certificate_before_transporting_secrets():
    adapter = DianAcquirerAdapter(endpoint_url="https://dian.contract.test/GetAcquirer")
    secret = ProviderSecret(
        {
            "software_id": "software-test-id",
            "software_password": "software-test-password",
            "certificate_pfx_base64": base64.b64encode(b"not-a-pfx").decode("ascii"),
            "certificate_password": "certificate-pass",
        }
    )

    with pytest.raises(AppError) as error:
        await adapter.get_acquirer_information(_context(), secret, "31", "900123456")

    assert error.value.code == "VALIDATION_ERROR"
    assert "software-test-password" not in error.value.message


@pytest.mark.asyncio
async def test_get_acquirer_rejects_an_expired_certificate_before_transporting_secrets():
    now = datetime.now(UTC)
    adapter = DianAcquirerAdapter(endpoint_url="https://dian.contract.test/GetAcquirer")
    secret = _secret(
        not_valid_before=now - timedelta(days=2),
        not_valid_after=now - timedelta(seconds=1),
    )

    with pytest.raises(AppError) as error:
        await adapter.get_acquirer_information(_context(), secret, "31", "900123456")

    assert error.value.code == "VALIDATION_ERROR"
    assert "certificado" in error.value.message.lower()


@pytest.mark.asyncio
async def test_get_acquirer_rejects_document_types_outside_the_dian_catalog():
    adapter = DianAcquirerAdapter(endpoint_url="https://dian.contract.test/GetAcquirer")

    with pytest.raises(AppError) as error:
        await adapter.get_acquirer_information(_context(), _secret(), "99", "900123456")

    assert error.value.code == "VALIDATION_ERROR"
