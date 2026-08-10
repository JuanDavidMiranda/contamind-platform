from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.data_source import ImportBatchRecord, PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _admin_token() -> str:
    db = SessionLocal()
    try:
        email = "data-sources-admin@test.local"
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name="Data Sources Admin",
                password_hash=hash_password("password123"),
                is_platform_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token(user)
    finally:
        db.close()


def test_admin_can_configure_and_import_csv_parties(client):
    token = _admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    onboarding_response = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant API", "company_name": "Empresa API"},
    )
    assert onboarding_response.status_code == 201
    tenant_id = onboarding_response.json()["tenant"]["id"]
    company_id = onboarding_response.json()["company"]["id"]
    source_response = client.post(
        "/api/v1/admin/data-sources",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "csv_import",
            "display_name": "Carga inicial",
            "kind": "file_import",
            "mode": "file_upload",
            "capabilities": ["parties", "file_import_export"],
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    profile_response = client.post(
        f"/api/v1/admin/data-sources/{source_id}/profiles",
        headers=headers,
        json={
            "entity": "parties",
            "file_format": "csv",
            "column_mapping": {"name": "Nombre", "document_number": "Documento"},
        },
    )
    assert profile_response.status_code == 201

    response = client.post(
        f"/api/v1/admin/data-sources/{source_id}/imports/parties",
        headers=headers,
        data={"profile_id": profile_response.json()["id"]},
        files={"file": ("terceros.csv", b"Nombre,Documento\nCliente API,900123456\n", "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["parties"][0]["name"] == "Cliente API"
    assert body["rejections"] == []

    db = SessionLocal()
    try:
        party = db.scalar(select(PartyRecord).where(PartyRecord.company_id == company_id))
        batch = db.scalar(select(ImportBatchRecord).where(ImportBatchRecord.id == body["batch_id"]))
        assert party is not None
        assert party.name == "Cliente API"
        assert batch is not None
        assert batch.content_sha256
    finally:
        db.close()


def test_data_source_endpoints_require_an_admin(client):
    response = client.get(f"/api/v1/admin/data-sources?company_id={uuid4()}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING_TOKEN"
