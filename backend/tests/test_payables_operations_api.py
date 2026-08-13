"""Contrato de cuentas por pagar: sólo compras, RBAC y vencimientos confirmados."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(email=email, full_name="Payables user", password_hash=hash_password("password123"))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _invoice(company_id: str, source_id: str, owner_id: int, invoice_type: str, total: str, due_date: date | None) -> InvoiceRecord:
    amount = Decimal(total)
    return InvoiceRecord(
        id=str(uuid4()), company_id=company_id, data_source_id=source_id,
        invoice_type=invoice_type, issue_date=date(2026, 8, 1), due_date=due_date,
        payment_terms_days=(due_date - date(2026, 8, 1)).days if due_date else None,
        currency_code="COP", exchange_rate=Decimal("1"), subtotal=amount,
        tax_total=Decimal("0"), withholding_total=Decimal("0"), total=amount,
        idempotency_key=uuid4().hex, created_by_user_id=owner_id,
    )


def test_payables_exposes_only_open_purchase_invoices_and_confirms_term_changes(client):
    suffix = uuid4().hex
    owner = _user(f"payables-owner-{suffix}@test.local")
    viewer = _user(f"payables-viewer-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding", headers=_headers(owner),
        json={"tenant_name": f"Payables {suffix}", "company_name": "Compras"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source = client.post(
        "/api/v1/data-sources", headers=_headers(owner), json={
            "tenant_id": tenant_id, "company_id": company_id, "connector_id": "payables_test",
            "display_name": "Compras", "kind": "manual_entry", "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]
    assert client.put(
        "/api/v1/company-memberships", headers=_headers(owner),
        json={"user_id": viewer.id, "company_id": company_id, "role": "viewer"},
    ).status_code == 200

    purchase = _invoice(company_id, source_id, owner.id, "purchase", "120", date(2026, 8, 10))
    missing_due = _invoice(company_id, source_id, owner.id, "purchase", "50", None)
    sale = _invoice(company_id, source_id, owner.id, "sale", "999", date(2026, 8, 5))
    settled = _invoice(company_id, source_id, owner.id, "purchase", "70", date(2026, 8, 5))
    purchase_id = purchase.id
    missing_due_id = missing_due.id
    db: Session = SessionLocal()
    try:
        db.add_all([purchase, missing_due, sale, settled])
        db.flush()
        db.add(PaymentRecord(
            id=str(uuid4()), company_id=company_id, data_source_id=source_id,
            payment_date=date(2026, 8, 6), amount=Decimal("70"), currency_code="COP",
            exchange_rate=Decimal("1"), invoice_id=settled.id, idempotency_key=uuid4().hex,
            created_by_user_id=owner.id,
        ))
        db.commit()
    finally:
        db.close()

    endpoint = f"/api/v1/companies/{company_id}/payables/open-items?as_of=2026-08-12"
    response = client.get(endpoint, headers=_headers(viewer))
    assert response.status_code == 200
    payload = response.json()
    assert payload["can_manage"] is False
    assert payload["total"] == 2
    assert {item["invoice_id"] for item in payload["items"]} == {purchase_id, missing_due_id}
    overdue = next(item for item in payload["items"] if item["invoice_id"] == purchase_id)
    assert overdue["outstanding_amount"] == "120.00"
    assert overdue["aging_bucket"] == "overdue_1_30"
    assert "latest_followup_status" not in overdue

    terms_endpoint = f"/api/v1/companies/{company_id}/payables/invoices/{missing_due_id}/terms"
    assert client.patch(terms_endpoint, headers=_headers(viewer), json={"payment_terms_days": 30, "confirmed": True}).status_code == 403
    updated = client.patch(terms_endpoint, headers=_headers(owner), json={"payment_terms_days": 30, "confirmed": True})
    assert updated.status_code == 200
    assert updated.json()["due_date"] == "2026-08-31"
    assert updated.json()["updated_by_user_id"] == owner.id
