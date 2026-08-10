from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.data_source import PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str, *, is_admin: bool = False) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="RBAC Test User",
            password_hash=hash_password("password123"),
            is_platform_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _membership(client, admin: User, member: User, company_id: str, role: str) -> None:
    response = client.put(
        "/api/v1/company-memberships",
        headers=_headers(admin),
        json={"user_id": member.id, "company_id": company_id, "role": role},
    )
    assert response.status_code == 200


def _manual_source_payload(tenant_id: str, company_id: str, display_name: str) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "company_id": company_id,
        "connector_id": "manual_entry",
        "display_name": display_name,
        "kind": "manual_entry",
        "mode": "manual",
        "capabilities": ["parties"],
    }


def test_company_roles_scope_sources_imports_and_manual_capture(client):
    suffix = uuid4().hex
    platform_admin = _create_user(f"rbac-platform-{suffix}@test.local", is_admin=True)
    owner = _create_user(f"rbac-owner-{suffix}@test.local")
    operator = _create_user(f"rbac-operator-{suffix}@test.local")
    viewer = _create_user(f"rbac-viewer-{suffix}@test.local")
    tenant_id = str(uuid4())
    company_id = str(uuid4())
    other_company_id = str(uuid4())

    _membership(client, platform_admin, owner, company_id, "owner")
    _membership(client, platform_admin, operator, company_id, "operator")
    _membership(client, platform_admin, viewer, company_id, "viewer")

    membership_response = client.get(
        f"/api/v1/company-memberships?company_id={company_id}",
        headers=_headers(owner),
    )
    assert membership_response.status_code == 200
    assert {item["role"] for item in membership_response.json()} == {"owner", "operator", "viewer"}

    source_response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json=_manual_source_payload(tenant_id, company_id, "Terceros manuales"),
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    assert client.get(
        f"/api/v1/data-sources?company_id={company_id}", headers=_headers(operator)
    ).status_code == 200
    assert client.get(
        f"/api/v1/data-sources?company_id={other_company_id}", headers=_headers(operator)
    ).status_code == 403

    capture_response = client.post(
        f"/api/v1/data-sources/{source_id}/parties",
        headers=_headers(operator),
        json={
            "party_type": "customer",
            "name": "Tercero capturado",
            "document_type": "NIT",
            "document_number": "900123456",
        },
    )
    assert capture_response.status_code == 201
    assert capture_response.json()["company_id"] == company_id

    db = SessionLocal()
    try:
        party = db.scalar(select(PartyRecord).where(PartyRecord.id == capture_response.json()["id"]))
        assert party is not None
        assert party.company_id == company_id
        assert party.data_source_id == source_id
    finally:
        db.close()

    assert client.post(
        "/api/v1/data-sources",
        headers=_headers(operator),
        json=_manual_source_payload(tenant_id, company_id, "No permitido"),
    ).status_code == 403
    assert client.post(
        f"/api/v1/data-sources/{source_id}/parties",
        headers=_headers(viewer),
        json={"party_type": "customer", "name": "No permitido"},
    ).status_code == 403


def test_operator_can_import_on_a_member_company_and_not_another(client):
    suffix = uuid4().hex
    platform_admin = _create_user(f"rbac-import-admin-{suffix}@test.local", is_admin=True)
    owner = _create_user(f"rbac-import-owner-{suffix}@test.local")
    operator = _create_user(f"rbac-import-operator-{suffix}@test.local")
    tenant_id = str(uuid4())
    company_id = str(uuid4())
    other_company_id = str(uuid4())
    _membership(client, platform_admin, owner, company_id, "owner")
    _membership(client, platform_admin, operator, company_id, "operator")

    source_response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "csv_import",
            "display_name": "Carga compartida",
            "kind": "file_import",
            "mode": "file_upload",
            "capabilities": ["parties", "file_import_export"],
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    profile_response = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=_headers(owner),
        json={
            "entity": "parties",
            "file_format": "csv",
            "column_mapping": {"name": "Nombre", "document_number": "Documento"},
        },
    )
    assert profile_response.status_code == 201

    import_response = client.post(
        f"/api/v1/data-sources/{source_id}/imports/parties",
        headers=_headers(operator),
        data={"profile_id": profile_response.json()["id"]},
        files={"file": ("terceros.csv", b"Nombre,Documento\nCliente operador,800123456\n", "text/csv")},
    )
    assert import_response.status_code == 200

    forbidden_source_response = client.post(
        "/api/v1/data-sources",
        headers=_headers(platform_admin),
        json=_manual_source_payload(tenant_id, other_company_id, "Empresa ajena"),
    )
    assert forbidden_source_response.status_code == 201
    assert client.post(
        f"/api/v1/data-sources/{forbidden_source_response.json()['id']}/parties",
        headers=_headers(operator),
        json={"party_type": "customer", "name": "No debe entrar"},
    ).status_code == 403
