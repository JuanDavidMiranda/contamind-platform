import json
from uuid import uuid4

import httpx2 as httpx
import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.data_source import (
    CompanyDataSourceRecord,
    PartyRecord,
    ProviderCredentialRecord,
)
from app.models.user import User
from app.providers.factory import ProviderFactory
from app.providers.siigo import SiigoProviderAdapter
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Siigo E2E user",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


def _client_factory(transport: httpx.MockTransport):
    def build_client(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return build_client


def test_siigo_connection_sync_audit_and_tenant_isolation_end_to_end(client, monkeypatch):
    """Recorre la API real usando solo el transporte HTTP de Siigo simulado."""

    from app.services import provider_connection_service as connection_module

    auth_calls = 0
    customer_pages: list[int] = []
    access_key = "siigo-access-key-that-must-remain-encrypted"
    username = "integracion-siigo@cliente.test"
    partner_id = "ContaMind"

    def siigo_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        assert request.headers["partner-id"] == partner_id
        if request.url.path == "/auth":
            auth_calls += 1
            assert json.loads(request.content) == {
                "username": username,
                "access_key": access_key,
            }
            return httpx.Response(201, json={"access_token": "temporary-siigo-jwt"})

        assert request.url.path == "/v1/customers"
        assert request.headers["authorization"] == "Bearer temporary-siigo-jwt"
        assert request.url.params["page_size"] == "1"
        page = int(request.url.params["page"])
        customer_pages.append(page)
        customers = {
            1: {
                "id": "siigo-party-1",
                "type": "Customer",
                "id_type": {"code": "31"},
                "identification": "900111222",
                "commercial_name": "Cliente Siigo Uno SAS",
                "contacts": [{"email": "uno@cliente.test"}],
                "phones": [{"number": "6015550101"}],
                "address": {
                    "address": "Carrera 1 # 2-3",
                    "city": {"name": "Bogotá"},
                },
            },
            2: {
                "id": "siigo-party-2",
                "type": "Supplier",
                "id_type": {"code": "13"},
                "identification": "1010101010",
                "name": ["Ana", "Proveedor"],
                "contacts": [{"email": "ana@proveedor.test"}],
            },
        }
        return httpx.Response(
            200,
            json={
                "pagination": {"total_results": 2},
                "results": [customers[page]],
            },
        )

    adapter = SiigoProviderAdapter(
        api_base_url="https://siigo.contract.test",
        client_factory=_client_factory(httpx.MockTransport(siigo_handler)),
    )
    factory = ProviderFactory()
    factory.register(adapter)
    monkeypatch.setattr(connection_module, "default_provider_factory", lambda: factory)

    suffix = uuid4().hex
    owner = _create_user(f"siigo-owner-{suffix}@test.local")
    outsider = _create_user(f"siigo-outsider-{suffix}@test.local")
    owner_headers = _headers(owner)

    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={
            "tenant_name": f"Tenant Siigo {suffix}",
            "company_name": "Empresa piloto Siigo",
        },
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]

    outsider_onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(outsider),
        json={
            "tenant_name": f"Tenant externo {suffix}",
            "company_name": "Empresa sin acceso",
        },
    )
    assert outsider_onboarding.status_code == 201

    source_response = client.post(
        "/api/v1/data-sources",
        headers=owner_headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "siigo_api",
            "display_name": "Siigo Nube",
            "kind": "accounting_software",
            "mode": "cloud_api",
            "capabilities": ["parties"],
            "provider_id": "siigo",
        },
    )
    assert source_response.status_code == 201
    assert source_response.json()["status"] == "pending"
    source_id = source_response.json()["id"]

    credentials_response = client.put(
        f"/api/v1/data-sources/{source_id}/credentials",
        headers=owner_headers,
        json={
            "credentials": {
                "username": username,
                "access_key": access_key,
                "partner_id": partner_id,
            }
        },
    )
    assert credentials_response.status_code == 200
    assert credentials_response.json() == {
        "data_source_id": source_id,
        "provider_id": "siigo",
        "status": "pending",
        "credential_configured": True,
    }
    assert access_key not in credentials_response.text
    assert username not in credentials_response.text

    connection = client.post(
        f"/api/v1/data-sources/{source_id}/connection-test",
        headers=_headers(owner, "siigo-e2e-connection"),
    )
    assert connection.status_code == 200
    assert connection.json()["status"] == "succeeded"
    assert connection.json()["correlation_id"] == "siigo-e2e-connection"

    first_sync = client.post(
        f"/api/v1/data-sources/{source_id}/sync/parties?page_size=1",
        headers=_headers(owner, "siigo-e2e-page-1"),
    )
    second_sync = client.post(
        f"/api/v1/data-sources/{source_id}/sync/parties?page_size=1",
        headers=_headers(owner, "siigo-e2e-page-2"),
    )
    assert first_sync.status_code == 200
    assert first_sync.json()["processed_records"] == 1
    assert first_sync.json()["cursor_before"] is None
    assert first_sync.json()["cursor_after"] == "2"
    assert second_sync.status_code == 200
    assert second_sync.json()["processed_records"] == 1
    assert second_sync.json()["cursor_before"] == "2"
    assert second_sync.json()["cursor_after"] is None

    runs = client.get(
        f"/api/v1/data-sources/{source_id}/connection-runs",
        headers=owner_headers,
    )
    assert runs.status_code == 200
    assert [run["operation"] for run in runs.json()] == [
        "sync_parties",
        "sync_parties",
        "connection_test",
    ]
    assert [run["correlation_id"] for run in runs.json()] == [
        "siigo-e2e-page-2",
        "siigo-e2e-page-1",
        "siigo-e2e-connection",
    ]

    audit = client.get(f"/api/v1/companies/{company_id}/audit", headers=owner_headers)
    assert audit.status_code == 200
    assert [source["id"] for source in audit.json()["sources"]] == [source_id]

    outsider_headers = _headers(outsider)
    assert client.get(
        f"/api/v1/data-sources/{source_id}/connection-runs",
        headers=outsider_headers,
    ).status_code == 403
    assert client.get(
        f"/api/v1/companies/{company_id}/audit",
        headers=outsider_headers,
    ).status_code == 403

    db = SessionLocal()
    try:
        credential = db.scalar(
            select(ProviderCredentialRecord).where(
                ProviderCredentialRecord.data_source_id == source_id
            )
        )
        assert credential is not None
        assert access_key not in credential.ciphertext
        assert username not in credential.ciphertext
        assert partner_id not in credential.ciphertext

        source = db.get(CompanyDataSourceRecord, source_id)
        assert source is not None
        assert source.status == "active"
        assert source.last_sync_cursor is None
        assert source.last_synced_at is not None

        parties = list(
            db.scalars(
                select(PartyRecord)
                .where(PartyRecord.data_source_id == source_id)
                .order_by(PartyRecord.external_id)
            )
        )
        assert len(parties) == 2
        assert parties[0].company_id == company_id
        assert parties[0].name == "Cliente Siigo Uno SAS"
        assert parties[0].email == "uno@cliente.test"
        assert parties[0].phone == "6015550101"
        assert parties[0].city == "Bogotá"
        assert parties[0].integration_id == f"{company_id}:siigo:siigo-party-1"
        assert parties[1].company_id == company_id
        assert parties[1].party_type == "supplier"
        assert parties[1].name == "Ana Proveedor"
    finally:
        db.close()

    serialized_outputs = "".join(
        response.text
        for response in (connection, first_sync, second_sync, runs, audit)
    )
    assert access_key not in serialized_outputs
    assert username not in serialized_outputs
    assert auth_calls == 3
    assert customer_pages == [1, 2]
