"""Flujo autenticado de promesas y seguimientos operativos de cobro."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.collection_followup import CollectionFollowUpRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Collection follow-up test user",
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


def _onboard_company(client, user: User, suffix: str) -> tuple[str, str]:
    response = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(user),
        json={
            "tenant_name": f"Tenant seguimiento {suffix}",
            "company_name": f"Empresa seguimiento {suffix}",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["tenant"]["id"], body["company"]["id"]


def _add_membership(client, owner: User, member: User, company_id: str, role: str) -> None:
    response = client.put(
        "/api/v1/company-memberships",
        headers=_headers(owner),
        json={"user_id": member.id, "company_id": company_id, "role": role},
    )
    assert response.status_code == 200


def _manual_source(client, owner: User, tenant_id: str, company_id: str) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "collection_followup_manual",
            "display_name": "Datos para seguimiento de cartera",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _sales_invoice(company_id: str, source_id: str, owner_id: int, key: str) -> InvoiceRecord:
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type="sale",
        issue_date=date(2026, 8, 12),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=Decimal("100"),
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=Decimal("100"),
        idempotency_key=key,
        created_by_user_id=owner_id,
    )


def _persist_invoice(invoice: InvoiceRecord) -> str:
    invoice_id = invoice.id
    db = SessionLocal()
    try:
        db.add(invoice)
        db.commit()
    finally:
        db.close()
    return invoice_id


def test_collection_followups_require_confirmation_and_keep_auditable_metadata(client):
    suffix = uuid4().hex
    owner = _create_user(f"collections-owner-{suffix}@test.local")
    operator = _create_user(f"collections-operator-{suffix}@test.local")
    viewer = _create_user(f"collections-viewer-{suffix}@test.local")
    tenant_id, company_id = _onboard_company(client, owner, suffix)
    _add_membership(client, owner, operator, company_id, "operator")
    _add_membership(client, owner, viewer, company_id, "viewer")
    source_id = _manual_source(client, owner, tenant_id, company_id)
    invoice = _sales_invoice(company_id, source_id, owner.id, "collection-followup-invoice")
    invoice_id = _persist_invoice(invoice)

    endpoint = f"/api/v1/companies/{company_id}/collection-followups"
    create_payload = {
        "invoice_id": invoice_id,
        "status": "promise_to_pay",
        "promised_date": "2026-08-20",
        "note": "Confirmar comprobante de pago antes de conciliar.",
    }
    assert client.post(endpoint, json={**create_payload, "confirmed": True}).status_code == 401
    assert client.post(
        endpoint,
        headers=_headers(owner),
        json={**create_payload, "confirmed": False},
    ).status_code == 422
    assert client.post(
        endpoint,
        headers=_headers(owner),
        json={
            "invoice_id": invoice_id,
            "status": "promise_to_pay",
            "confirmed": True,
        },
    ).status_code == 422
    assert client.post(
        endpoint,
        headers=_headers(owner),
        json={
            "invoice_id": invoice_id,
            "status": "pending",
            "promised_date": "2026-08-20",
            "confirmed": True,
        },
    ).status_code == 422

    created = client.post(
        endpoint,
        headers=_headers(owner),
        json={**create_payload, "confirmed": True},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["company_id"] == company_id
    assert body["invoice_id"] == invoice_id
    assert body["status"] == "promise_to_pay"
    assert body["promised_date"] == "2026-08-20"
    assert body["note"] == create_payload["note"]
    assert body["created_by_user_id"] == owner.id
    assert body["updated_by_user_id"] == owner.id
    assert "recipient" not in body
    assert "customer" not in body

    listed = client.get(endpoint, headers=_headers(viewer))
    assert listed.status_code == 200
    assert [{key: item[key] for key in ("id", "invoice_id", "status")} for item in listed.json()] == [
        {"id": body["id"], "invoice_id": invoice_id, "status": "promise_to_pay"}
    ]
    filtered = client.get(f"{endpoint}?invoice_id={invoice_id}", headers=_headers(viewer))
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [body["id"]]

    # Al dejar de ser una promesa, la fecha debe eliminarse explícitamente.
    assert client.patch(
        f"{endpoint}/{body['id']}",
        headers=_headers(operator),
        json={"status": "contacted", "confirmed": True},
    ).status_code == 422

    update = client.patch(
        f"{endpoint}/{body['id']}",
        headers=_headers(operator),
        json={
            "status": "contacted",
            "promised_date": None,
            "note": "Validar el soporte recibido antes de registrar el pago.",
            "confirmed": True,
        },
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["status"] == "contacted"
    assert updated["promised_date"] is None
    assert updated["created_by_user_id"] == owner.id
    assert updated["updated_by_user_id"] == operator.id

    db = SessionLocal()
    try:
        followup = db.get(CollectionFollowUpRecord, updated["id"])
        assert followup is not None
        assert followup.company_id == company_id
        assert followup.invoice_id == invoice_id
        assert followup.created_by_user_id == owner.id
        assert followup.updated_by_user_id == operator.id
        assert db.scalar(select(PaymentRecord.id).where(PaymentRecord.invoice_id == invoice_id)) is None
    finally:
        db.close()

    assert client.post(
        endpoint,
        headers=_headers(viewer),
        json={**create_payload, "confirmed": True},
    ).status_code == 403
    assert client.patch(
        f"{endpoint}/{body['id']}",
        headers=_headers(owner),
        json={"confirmed": True},
    ).status_code == 422
    assert client.patch(
        f"{endpoint}/{body['id']}",
        headers=_headers(owner),
        json={"status": None, "confirmed": True},
    ).status_code == 422


def test_collection_followups_reject_pii_and_enforce_company_scope(client):
    suffix = uuid4().hex
    owner = _create_user(f"collections-scope-owner-{suffix}@test.local")
    outsider = _create_user(f"collections-scope-outsider-{suffix}@test.local")
    tenant_id, company_id = _onboard_company(client, owner, suffix)
    source_id = _manual_source(client, owner, tenant_id, company_id)
    invoice = _sales_invoice(company_id, source_id, owner.id, "collection-followup-scope")
    invoice_id = _persist_invoice(invoice)
    other_tenant_id, other_company_id = _onboard_company(client, outsider, f"other-{suffix}")
    other_source_id = _manual_source(client, outsider, other_tenant_id, other_company_id)

    endpoint = f"/api/v1/companies/{company_id}/collection-followups"
    pii_note = "Llamar al 300 123 4567 para confirmar el recaudo."
    pii_response = client.post(
        endpoint,
        headers=_headers(owner),
        json={
            "invoice_id": invoice_id,
            "status": "pending",
            "note": pii_note,
            "confirmed": True,
        },
    )
    assert pii_response.status_code == 422
    assert pii_note not in pii_response.text

    too_long_response = client.post(
        endpoint,
        headers=_headers(owner),
        json={
            "invoice_id": invoice_id,
            "status": "pending",
            "note": "a" * 281,
            "confirmed": True,
        },
    )
    assert too_long_response.status_code == 422

    assert client.get(endpoint, headers=_headers(outsider)).status_code == 403
    foreign_invoice = _sales_invoice(
        other_company_id,
        other_source_id,
        outsider.id,
        "collection-followup-foreign",
    )
    foreign_invoice_id = _persist_invoice(foreign_invoice)
    wrong_invoice_response = client.post(
        endpoint,
        headers=_headers(owner),
        json={
            "invoice_id": foreign_invoice_id,
            "status": "pending",
            "confirmed": True,
        },
    )
    assert wrong_invoice_response.status_code == 404
    assert client.get(
        f"/api/v1/companies/{other_company_id}/collection-followups",
        headers=_headers(owner),
    ).status_code == 403
