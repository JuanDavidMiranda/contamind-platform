from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, ItemRecord, JournalEntryRecord, PaymentRecord, TaxRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Manual Accounting Test User",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _manual_source(client, owner: User, tenant_id: str, company_id: str) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "manual_accounting",
            "display_name": "Contabilidad manual",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["parties", "taxes", "items", "invoices", "payments", "journals"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_operator_captures_accounting_core_idempotently(client):
    suffix = uuid4().hex
    owner = _create_user(f"manual-owner-{suffix}@test.local")
    operator = _create_user(f"manual-operator-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant manual {suffix}", "company_name": "Empresa manual"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    membership = client.put(
        "/api/v1/company-memberships",
        headers=_headers(owner),
        json={"user_id": operator.id, "company_id": company_id, "role": "operator"},
    )
    assert membership.status_code == 200
    source_id = _manual_source(client, owner, tenant_id, company_id)

    party_response = client.post(
        f"/api/v1/data-sources/{source_id}/parties",
        headers=_headers(operator),
        json={"party_type": "customer", "name": "Cliente manual", "document_number": "900123456"},
    )
    assert party_response.status_code == 201
    party_id = party_response.json()["id"]

    tax_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/taxes",
        headers=_headers(operator, "tax-iva-19"),
        json={"code": "IVA19", "name": "IVA 19%", "rate": "19"},
    )
    assert tax_response.status_code == 201
    tax_id = tax_response.json()["id"]
    retry_tax = client.post(
        f"/api/v1/data-sources/{source_id}/manual/taxes",
        headers=_headers(operator, " tax-iva-19 "),
        json={"code": "DIFERENTE", "name": "No debe duplicarse", "rate": "0"},
    )
    assert retry_tax.status_code == 201
    assert retry_tax.json()["id"] == tax_id

    item_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/items",
        headers=_headers(operator, "item-consultoria"),
        json={
            "code": "CONS-01",
            "name": "Consultoría",
            "item_type": "service",
            "unit_price": "100",
            "tax_ids": [tax_id],
            "ledger_account": "4135",
        },
    )
    assert item_response.status_code == 201
    item_id = item_response.json()["id"]

    invoice_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/invoices",
        headers=_headers(operator, "factura-manual-001"),
        json={
            "invoice_type": "sale",
            "issue_date": "2026-08-10",
            "recipient_party_id": party_id,
            "lines": [
                {
                    "item_id": item_id,
                    "description": "Servicio de consultoría",
                    "quantity": "2",
                    "unit_price": "100",
                    "tax_ids": [tax_id],
                }
            ],
            "tax_total": "38",
            "number": "FV-001",
        },
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.json()["id"]
    assert invoice_response.json()["subtotal"] == "200.00"
    assert invoice_response.json()["total"] == "238.00"

    payment_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/payments",
        headers=_headers(operator, "pago-manual-001"),
        json={
            "payment_date": "2026-08-10",
            "amount": "238",
            "invoice_id": invoice_id,
            "payment_method": "transferencia",
        },
    )
    assert payment_response.status_code == 201

    journal_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/journal-entries",
        headers=_headers(operator, "asiento-manual-001"),
        json={
            "entry_date": "2026-08-10",
            "description": "Registro de factura manual",
            "lines": [
                {"account_code": "1305", "debit": "238", "credit": "0", "party_id": party_id},
                {"account_code": "4135", "debit": "0", "credit": "238"},
            ],
            "source_reference": "FV-001",
        },
    )
    assert journal_response.status_code == 201

    unbalanced_response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/journal-entries",
        headers=_headers(operator, "asiento-invalido"),
        json={
            "entry_date": "2026-08-10",
            "description": "No cuadra",
            "lines": [
                {"account_code": "1305", "debit": "100", "credit": "0"},
                {"account_code": "4135", "debit": "0", "credit": "90"},
            ],
        },
    )
    assert unbalanced_response.status_code == 422
    assert unbalanced_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post(
        f"/api/v1/data-sources/{source_id}/manual/taxes",
        headers=_headers(operator),
        json={"code": "SIN-KEY", "name": "Sin llave", "rate": "0"},
    ).status_code == 422

    db = SessionLocal()
    try:
        tax = db.get(TaxRecord, tax_id)
        item = db.get(ItemRecord, item_id)
        invoice = db.get(InvoiceRecord, invoice_id)
        payment = db.get(PaymentRecord, payment_response.json()["id"])
        journal = db.get(JournalEntryRecord, journal_response.json()["id"])
        assert tax is not None and tax.created_by_user_id == operator.id
        assert item is not None and item.created_by_user_id == operator.id
        assert invoice is not None and invoice.created_by_user_id == operator.id
        assert payment is not None and payment.created_by_user_id == operator.id
        assert journal is not None and journal.created_by_user_id == operator.id
        assert db.scalar(
            select(func.count()).select_from(TaxRecord).where(TaxRecord.company_id == company_id)
        ) == 1
    finally:
        db.close()
