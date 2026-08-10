from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.data_source import CompanyDataSourceRecord, ImportBatchRecord, PartyRecord
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


def _onboard_company(client, user: User, suffix: str) -> tuple[str, str]:
    response = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(user),
        json={
            "tenant_name": f"Tenant RBAC {suffix}",
            "company_name": f"Empresa RBAC {suffix}",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["tenant"]["id"], body["company"]["id"]


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
    tenant_id, company_id = _onboard_company(client, owner, suffix)
    _, other_company_id = _onboard_company(client, platform_admin, f"other-{suffix}")

    _membership(client, platform_admin, operator, company_id, "operator")
    _membership(client, platform_admin, viewer, company_id, "viewer")

    membership_response = client.get(
        f"/api/v1/company-memberships?company_id={company_id}",
        headers=_headers(owner),
    )
    assert membership_response.status_code == 200
    assert {item["role"] for item in membership_response.json()} == {"owner", "operator", "viewer"}
    my_companies_response = client.get("/api/v1/companies/mine", headers=_headers(operator))
    assert my_companies_response.status_code == 200
    assert [company["id"] for company in my_companies_response.json()] == [company_id]
    assert client.put(
        "/api/v1/company-memberships",
        headers=_headers(platform_admin),
        json={"user_id": operator.id, "company_id": str(uuid4()), "role": "operator"},
    ).status_code == 404

    invalid_source_payload = _manual_source_payload(str(uuid4()), company_id, "Tenant incorrecto")
    assert client.post(
        "/api/v1/data-sources", headers=_headers(owner), json=invalid_source_payload
    ).status_code == 409

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
        source = db.get(CompanyDataSourceRecord, source_id)
        assert party is not None
        assert source is not None
        assert party.company_id == company_id
        assert party.data_source_id == source_id
        assert source.created_by_user_id == owner.id
        assert party.created_by_user_id == operator.id
        assert party.updated_by_user_id == operator.id
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
    audit_response = client.get(f"/api/v1/companies/{company_id}/audit", headers=_headers(viewer))
    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["sources"][0]["created_by_user_id"] == owner.id
    assert audit["manual_captures"][0]["updated_by_user_id"] == operator.id


def test_operator_can_import_on_a_member_company_and_not_another(client):
    suffix = uuid4().hex
    platform_admin = _create_user(f"rbac-import-admin-{suffix}@test.local", is_admin=True)
    owner = _create_user(f"rbac-import-owner-{suffix}@test.local")
    operator = _create_user(f"rbac-import-operator-{suffix}@test.local")
    tenant_id, company_id = _onboard_company(client, owner, suffix)
    other_tenant_id, other_company_id = _onboard_company(client, platform_admin, f"other-{suffix}")
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
    db = SessionLocal()
    try:
        batch = db.get(ImportBatchRecord, import_response.json()["batch_id"])
        assert batch is not None
        assert batch.created_by_user_id == operator.id
    finally:
        db.close()
    audit_response = client.get(f"/api/v1/companies/{company_id}/audit", headers=_headers(operator))
    assert audit_response.status_code == 200
    assert audit_response.json()["imports"][0]["created_by_user_id"] == operator.id

    forbidden_source_response = client.post(
        "/api/v1/data-sources",
        headers=_headers(platform_admin),
        json=_manual_source_payload(other_tenant_id, other_company_id, "Empresa ajena"),
    )
    assert forbidden_source_response.status_code == 201
    assert client.post(
        f"/api/v1/data-sources/{forbidden_source_response.json()['id']}/parties",
        headers=_headers(operator),
        json={"party_type": "customer", "name": "No debe entrar"},
    ).status_code == 403


def test_tenant_owner_can_manage_multiple_companies_without_deleting_them(client):
    suffix = uuid4().hex
    owner = _create_user(f"tenant-owner-{suffix}@test.local")
    operator = _create_user(f"tenant-operator-{suffix}@test.local")
    tenant_id, first_company_id = _onboard_company(client, owner, suffix)
    second_company_response = client.post(
        f"/api/v1/tenants/{tenant_id}/companies",
        headers=_headers(owner),
        json={"name": "Segunda razón social", "functional_currency": "COP"},
    )
    assert second_company_response.status_code == 201
    second_company_id = second_company_response.json()["id"]
    assert second_company_response.json()["tenant_id"] == tenant_id
    assert second_company_response.json()["status"] == "active"

    _membership(client, owner, operator, first_company_id, "operator")
    assert client.post(
        f"/api/v1/tenants/{tenant_id}/companies",
        headers=_headers(operator),
        json={"name": "No permitida"},
    ).status_code == 403
    assert [company["id"] for company in client.get(
        "/api/v1/companies/mine", headers=_headers(operator)
    ).json()] == [first_company_id]
    assert {company["id"] for company in client.get(
        "/api/v1/companies/mine", headers=_headers(owner)
    ).json()} == {first_company_id, second_company_id}

    update_response = client.patch(
        f"/api/v1/companies/{second_company_id}",
        headers=_headers(owner),
        json={"name": "Segunda razón social actualizada", "provider_company_id": "empresa_02"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Segunda razón social actualizada"
    assert update_response.json()["provider_company_id"] == "empresa_02"

    disable_response = client.post(
        f"/api/v1/companies/{second_company_id}/disable", headers=_headers(owner)
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "disabled"
    assert client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json=_manual_source_payload(tenant_id, second_company_id, "No operar"),
    ).status_code == 409
    activate_response = client.post(
        f"/api/v1/companies/{second_company_id}/activate", headers=_headers(owner)
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"
