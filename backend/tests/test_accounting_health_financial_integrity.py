"""Cobertura de integridad financiera del agente de salud contable."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.config.features import FEATURE_LLM
from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.accounting import (
    InvoiceLineRecord,
    InvoiceRecord,
    JournalEntryLineRecord,
    JournalEntryRecord,
    PaymentRecord,
)
from app.models.data_source import PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Financial integrity test user",
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


def _manual_source(client, owner: User, tenant_id: str, company_id: str) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "financial_health_manual",
            "display_name": "Contabilidad para integridad financiera",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["parties", "invoices", "payments", "journals"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_accounting_health_agent_detects_financial_integrity_gaps(client, monkeypatch):
    monkeypatch.setitem(settings.FEATURE_FLAGS, FEATURE_LLM, False)
    suffix = uuid4().hex
    owner = _create_user(f"health-financial-{suffix}@test.local")
    owner_headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": f"Tenant financial {suffix}", "company_name": "Empresa financiera"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source_id = _manual_source(client, owner, tenant_id, company_id)

    document_number = "900333444"
    malformed_invoice_id = str(uuid4())
    rounded_invoice_id = str(uuid4())
    db = SessionLocal()
    try:
        party_id = str(uuid4())
        journal_without_lines_id = str(uuid4())
        journal_with_both_sides_id = str(uuid4())
        db.add(
            PartyRecord(
                id=party_id,
                company_id=company_id,
                data_source_id=source_id,
                party_type="customer",
                name="Tercero de prueba financiera",
                document_type="31",
                document_number=document_number,
                created_by_user_id=owner.id,
                updated_by_user_id=owner.id,
            )
        )
        db.add_all(
            [
                InvoiceRecord(
                    id=malformed_invoice_id,
                    company_id=company_id,
                    data_source_id=source_id,
                    invoice_type="sale",
                    issue_date=date(2026, 8, 11),
                    recipient_party_id=party_id,
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    subtotal=Decimal("250"),
                    tax_total=Decimal("10"),
                    withholding_total=Decimal("5"),
                    total=Decimal("260"),
                    idempotency_key="financial-malformed-invoice",
                    created_by_user_id=owner.id,
                ),
                InvoiceRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    data_source_id=source_id,
                    invoice_type="sale",
                    issue_date=date(2026, 8, 11),
                    recipient_party_id=party_id,
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    subtotal=Decimal("100"),
                    tax_total=Decimal("0"),
                    withholding_total=Decimal("0"),
                    total=Decimal("100"),
                    idempotency_key="financial-invoice-without-lines",
                    created_by_user_id=owner.id,
                ),
                InvoiceRecord(
                    id=rounded_invoice_id,
                    company_id=company_id,
                    data_source_id=source_id,
                    invoice_type="sale",
                    issue_date=date(2026, 8, 11),
                    recipient_party_id=party_id,
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    subtotal=Decimal("0.33"),
                    tax_total=Decimal("0"),
                    withholding_total=Decimal("0"),
                    total=Decimal("0.33"),
                    idempotency_key="financial-rounded-invoice",
                    created_by_user_id=owner.id,
                ),
                JournalEntryRecord(
                    id=journal_without_lines_id,
                    company_id=company_id,
                    data_source_id=source_id,
                    entry_date=date(2026, 8, 11),
                    description="Comprobante sin líneas",
                    idempotency_key="financial-journal-without-lines",
                    created_by_user_id=owner.id,
                ),
                JournalEntryRecord(
                    id=journal_with_both_sides_id,
                    company_id=company_id,
                    data_source_id=source_id,
                    entry_date=date(2026, 8, 11),
                    description="Comprobante con línea inválida",
                    idempotency_key="financial-journal-both-sides",
                    created_by_user_id=owner.id,
                ),
                PaymentRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    data_source_id=source_id,
                    payment_date=date(2026, 8, 10),
                    amount=Decimal("300"),
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    invoice_id=malformed_invoice_id,
                    idempotency_key="financial-overpayment",
                    created_by_user_id=owner.id,
                ),
            ]
        )
        db.add_all(
            [
                InvoiceLineRecord(
                    id=str(uuid4()),
                    invoice_id=malformed_invoice_id,
                    description="Detalle inconsistente",
                    quantity=Decimal("1"),
                    unit_price=Decimal("100"),
                ),
                InvoiceLineRecord(
                    id=str(uuid4()),
                    invoice_id=rounded_invoice_id,
                    description="Detalle con redondeo válido",
                    quantity=Decimal("0.333"),
                    unit_price=Decimal("1"),
                ),
                JournalEntryLineRecord(
                    id=str(uuid4()),
                    journal_entry_id=journal_with_both_sides_id,
                    account_code="1105",
                    debit=Decimal("100"),
                    credit=Decimal("100"),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers=owner_headers,
        json={"message": "revisa la integridad financiera"},
    )
    assert response.status_code == 200
    findings = {finding["code"]: finding for finding in response.json()["report"]["findings"]}
    assert {
        "INVOICES_WITHOUT_LINES",
        "INVOICE_SUBTOTAL_MISMATCH",
        "INVOICE_TOTAL_MISMATCH",
        "PAYMENTS_BEFORE_INVOICE",
        "OVERPAID_INVOICES",
        "JOURNALS_WITHOUT_LINES",
        "JOURNAL_LINES_WITH_BOTH_SIDES",
    } <= findings.keys()
    assert findings["INVOICE_SUBTOTAL_MISMATCH"]["evidence"] == {"invoices": 1}
    assert findings["OVERPAID_INVOICES"]["evidence"] == {"invoices": 1}
    assert findings["PAYMENTS_BEFORE_INVOICE"]["evidence"] == {"payments": 1}
    assert findings["JOURNALS_WITHOUT_LINES"]["severity"] == "critical"
    assert findings["JOURNAL_LINES_WITH_BOTH_SIDES"]["severity"] == "critical"
    assert document_number not in response.text
