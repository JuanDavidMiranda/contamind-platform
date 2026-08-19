import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2 as httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from app.database.database import SessionLocal
from app.models.dian import DianAcquirerLookupRecord
from app.models.user import User
from app.providers.dian import DianAcquirerAdapter
from app.providers.factory import ProviderFactory
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _credentials() -> dict[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ContaMind DIAN API test")])
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
        b"contamind-dian-api-test",
        key,
        certificate,
        None,
        BestAvailableEncryption(b"certificate-pass"),
    )
    return {
        "software_id": "software-test-id",
        "software_password": "software-test-password",
        "certificate_pfx_base64": base64.b64encode(pfx).decode("ascii"),
        "certificate_password": "certificate-pass",
    }


def _create_user() -> User:
    db = SessionLocal()
    try:
        user = User(
            email=f"dian-owner-{uuid4().hex}@test.local",
            full_name="DIAN owner",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _client_factory(transport: httpx.MockTransport):
    def build_client(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return build_client


def test_lookup_is_individual_audited_and_does_not_persist_personal_response(client, monkeypatch):
    from app.services import dian_acquirer_service as service_module

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"900123456" in request.content
        return httpx.Response(
            200,
            content=(
                b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                b"<s:Body><GetAcquirerResponse><GetAcquirerResult>"
                b"<Name>Adquiriente privado S.A.S.</Name><Email>adquiriente@example.test</Email>"
                b"</GetAcquirerResult></GetAcquirerResponse></s:Body></s:Envelope>"
            ),
        )

    factory = ProviderFactory()
    factory.register(
        DianAcquirerAdapter(
            endpoint_url="https://dian.contract.test/GetAcquirer",
            client_factory=_client_factory(httpx.MockTransport(handler)),
        )
    )
    monkeypatch.setattr(service_module, "default_provider_factory", lambda: factory)

    user = _create_user()
    headers = _headers(user)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant DIAN", "company_name": "Empresa DIAN"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source = client.post(
        "/api/v1/data-sources",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "dian_get_acquirer",
            "display_name": "DIAN GetAcquirer",
            "kind": "fiscal_authority",
            "mode": "fiscal_service",
            "provider_id": "dian",
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]
    credentials = _credentials()
    configured = client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=headers,
        json={"credentials": credentials},
    )
    assert configured.status_code == 200
    assert credentials["software_password"] not in configured.text
    assert credentials["certificate_password"] not in configured.text

    response = client.post(
        f"/api/v1/companies/{company_id}/dian/acquirers/lookup",
        headers={**headers, "X-Request-ID": "dian-test-lookup"},
        json={
            "data_source_id": source_id,
            "document_type": "31",
            "document_number": "900123456",
            "purpose": "electronic_invoice_issuance",
            "confirmed": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Adquiriente privado S.A.S."
    assert response.json()["email"] == "adquiriente@example.test"
    assert "900123456" not in response.text
    assert "document_number" not in response.text

    audit_response = client.get(
        f"/api/v1/companies/{company_id}/dian/acquirers/lookups",
        headers=headers,
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["total"] == 1
    assert audit_response.json()["items"][0]["status"] == "succeeded"
    assert "900123456" not in audit_response.text
    assert "adquiriente@example.test" not in audit_response.text

    db = SessionLocal()
    try:
        record = db.get(DianAcquirerLookupRecord, response.json()["lookup_id"])
        assert record is not None
        assert record.status == "succeeded"
        assert record.document_type == "31"
        assert record.document_number_hmac != "900123456"
        assert record.correlation_id == "dian-test-lookup"
        assert record.error_code is None
    finally:
        db.close()


def test_lookup_requires_explicit_invoice_purpose_and_confirmation(client):
    user = _create_user()
    headers = _headers(user)
    company = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant DIAN validation", "company_name": "Empresa DIAN validation"},
    ).json()["company"]
    payload = {
        "data_source_id": str(uuid4()),
        "document_type": "31",
        "document_number": "900123456",
        "purpose": "electronic_invoice_issuance",
        "confirmed": False,
    }

    response = client.post(
        f"/api/v1/companies/{company['id']}/dian/acquirers/lookup",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
