"""Flujo integrado del agente de cartera de ventas."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config.features import FEATURE_LLM
from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.agent import AgentExecutionRecord
from app.models.data_source import PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Receivables test user",
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
            "connector_id": "receivables_manual",
            "display_name": "Contabilidad para cartera",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["parties", "invoices", "payments"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _invoice(
    *,
    company_id: str,
    source_id: str,
    owner_id: int,
    total: str,
    currency: str,
    recipient_party_id: str | None,
    idempotency_key: str,
) -> InvoiceRecord:
    amount = Decimal(total)
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type="sale",
        issue_date=date(2026, 8, 12),
        recipient_party_id=recipient_party_id,
        currency_code=currency,
        exchange_rate=Decimal("1"),
        subtotal=amount,
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=amount,
        idempotency_key=idempotency_key,
        created_by_user_id=owner_id,
    )


def _payment(
    *,
    company_id: str,
    source_id: str,
    owner_id: int,
    invoice_id: str,
    amount: str,
    currency: str,
    idempotency_key: str,
) -> PaymentRecord:
    return PaymentRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        payment_date=date(2026, 8, 12),
        amount=Decimal(amount),
        currency_code=currency,
        exchange_rate=Decimal("1"),
        invoice_id=invoice_id,
        idempotency_key=idempotency_key,
        created_by_user_id=owner_id,
    )


def test_receivables_agent_reports_aggregated_sales_balances(client, monkeypatch):
    monkeypatch.setattr(settings, "FEATURE_FLAGS", {FEATURE_LLM: False})
    suffix = uuid4().hex
    owner = _create_user(f"receivables-{suffix}@test.local")
    owner_headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": f"Tenant cartera {suffix}", "company_name": "Empresa cartera"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source_id = _manual_source(client, owner, tenant_id, company_id)

    customer_document = "900555888"
    db = SessionLocal()
    try:
        customer_id = str(uuid4())
        db.add(
            PartyRecord(
                id=customer_id,
                company_id=company_id,
                data_source_id=source_id,
                party_type="customer",
                name="Cliente de cartera",
                document_type="31",
                document_number=customer_document,
                created_by_user_id=owner.id,
                updated_by_user_id=owner.id,
            )
        )
        unpaid = _invoice(
            company_id=company_id,
            source_id=source_id,
            owner_id=owner.id,
            total="100",
            currency="COP",
            recipient_party_id=None,
            idempotency_key="receivables-unpaid",
        )
        partial = _invoice(
            company_id=company_id,
            source_id=source_id,
            owner_id=owner.id,
            total="200",
            currency="COP",
            recipient_party_id=customer_id,
            idempotency_key="receivables-partial",
        )
        overpaid = _invoice(
            company_id=company_id,
            source_id=source_id,
            owner_id=owner.id,
            total="50",
            currency="COP",
            recipient_party_id=customer_id,
            idempotency_key="receivables-overpaid",
        )
        currency_mismatch = _invoice(
            company_id=company_id,
            source_id=source_id,
            owner_id=owner.id,
            total="20",
            currency="USD",
            recipient_party_id=customer_id,
            idempotency_key="receivables-currency-mismatch",
        )
        db.add_all([unpaid, partial, overpaid, currency_mismatch])
        db.add_all(
            [
                _payment(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_id=partial.id,
                    amount="80",
                    currency="COP",
                    idempotency_key="receivables-partial-payment",
                ),
                _payment(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_id=overpaid.id,
                    amount="60",
                    currency="COP",
                    idempotency_key="receivables-overpaid-payment",
                ),
                _payment(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_id=currency_mismatch.id,
                    amount="20",
                    currency="COP",
                    idempotency_key="receivables-currency-payment",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/companies/{company_id}/agents/receivables/chat",
        headers=owner_headers,
        json={"message": "¿Qué debo revisar en la cartera?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "receivables"
    assert body["workflow"] == "receivables"
    assert body["conversation"]["outcome"] == "answered"
    metrics = body["report"]["metrics"]
    assert {
        "sales_invoices": 4,
        "open_sales_invoices": 3,
        "unpaid_sales_invoices": 2,
        "partially_paid_sales_invoices": 1,
        "overpaid_sales_invoices": 1,
        "payments_with_currency_mismatch": 1,
        "outstanding_balances": [
            {"currency_code": "COP", "amount": "220.00"},
            {"currency_code": "USD", "amount": "20.00"},
        ],
    }.items() <= metrics.items()
    assert metrics["sales_invoices_missing_due_date"] == 4
    assert metrics["overdue_sales_invoices"] == 0
    assert metrics["broken_payment_promises"] == 0
    assert metrics["aging_buckets"] == [
        {
            "key": "missing_due_date",
            "invoices": 3,
            "outstanding_balances": [
                {"currency_code": "COP", "amount": "220.00"},
                {"currency_code": "USD", "amount": "20.00"},
            ],
        }
    ]
    findings = {finding["code"]: finding for finding in body["report"]["findings"]}
    assert {
        "UNPAID_SALES_INVOICES",
        "PARTIALLY_PAID_SALES_INVOICES",
        "OVERPAID_SALES_INVOICES",
        "SALES_INVOICES_MISSING_DUE_DATE",
        "SALES_INVOICES_WITHOUT_CUSTOMER",
        "PAYMENTS_WITH_CURRENCY_MISMATCH",
    } == findings.keys()
    assert findings["UNPAID_SALES_INVOICES"]["evidence"] == {"invoices": 2}
    assert findings["PARTIALLY_PAID_SALES_INVOICES"]["evidence"] == {"invoices": 1}
    assert customer_document not in response.text

    write_request = client.post(
        f"/api/v1/companies/{company_id}/agents/receivables/chat",
        headers=owner_headers,
        json={"message": "Registra un pago para esta factura"},
    )
    assert write_request.status_code == 200
    assert write_request.json()["conversation"]["outcome"] == "out_of_scope"

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord)
                .where(
                    AgentExecutionRecord.company_id == company_id,
                    AgentExecutionRecord.agent_id == "receivables",
                )
                .order_by(AgentExecutionRecord.started_at)
            )
        )
        assert len(executions) == 2
        assert executions[0].finding_codes == sorted(findings)
        assert customer_document not in str(executions[0].finding_codes)
    finally:
        db.close()
