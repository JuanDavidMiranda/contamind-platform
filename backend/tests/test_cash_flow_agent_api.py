"""Flujo integrado del agente determinista de caja."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.services.cash_flow_service import CashFlowService
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.agent import AgentExecutionRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (-1, "overdue"),
        (0, "due_today"),
        (1, "next_7_days"),
        (7, "next_7_days"),
        (8, "days_8_30"),
        (30, "days_8_30"),
        (31, "days_31_60"),
        (60, "days_31_60"),
        (61, "days_61_90"),
        (90, "days_61_90"),
        (91, "beyond_90"),
    ],
)
def test_cash_flow_period_boundaries(offset: int, expected: str):
    as_of = date(2026, 8, 13)
    assert CashFlowService._period_key(as_of + timedelta(days=offset), as_of) == expected


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Cash flow test user",
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


def _invoice(
    *,
    company_id: str,
    source_id: str,
    owner_id: int,
    invoice_type: str,
    due_date: date | None,
    total: str,
    currency: str,
) -> InvoiceRecord:
    amount = Decimal(total)
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type=invoice_type,
        issue_date=date.today() - timedelta(days=10),
        due_date=due_date,
        currency_code=currency,
        exchange_rate=Decimal("1"),
        subtotal=amount,
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=amount,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def test_cash_flow_agent_projects_open_movements_without_claiming_bank_balance(client):
    suffix = uuid4().hex
    owner = _create_user(f"cash-flow-{suffix}@test.local")
    headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={
            "tenant_name": f"Tenant flujo {suffix}",
            "company_name": "Empresa flujo",
        },
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source_response = client.post(
        "/api/v1/data-sources",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "cash_flow_manual",
            "display_name": "Datos para flujo",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    today = date.today()

    sale_cop = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        due_date=today + timedelta(days=5),
        total="1000",
        currency="COP",
    )
    purchase_cop = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="purchase",
        due_date=today + timedelta(days=5),
        total="500",
        currency="COP",
    )
    sale_usd = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        due_date=today + timedelta(days=20),
        total="200",
        currency="USD",
    )
    purchase_usd = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="purchase",
        due_date=today + timedelta(days=20),
        total="300",
        currency="USD",
    )
    missing_due_date = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        due_date=None,
        total="100",
        currency="COP",
    )
    overdue_purchase = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="purchase",
        due_date=today - timedelta(days=3),
        total="50",
        currency="COP",
    )
    db = SessionLocal()
    try:
        db.add_all(
            [
                sale_cop,
                purchase_cop,
                sale_usd,
                purchase_usd,
                missing_due_date,
                overdue_purchase,
            ]
        )
        db.flush()
        db.add(
            PaymentRecord(
                id=str(uuid4()),
                company_id=company_id,
                data_source_id=source_id,
                payment_date=today,
                amount=Decimal("200"),
                currency_code="COP",
                exchange_rate=Decimal("1"),
                invoice_id=sale_cop.id,
                idempotency_key=uuid4().hex,
                created_by_user_id=owner.id,
            )
        )
        db.commit()
    finally:
        db.close()

    endpoint = f"/api/v1/companies/{company_id}/agents/cash-flow/chat"
    response = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Cuál es el movimiento neto proyectado por moneda?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "cash_flow"
    assert body["workflow"] == "cash_flow"
    assert body["conversation"]["outcome"] == "answered"
    metrics = body["report"]["metrics"]
    assert metrics["open_receivables"] == 3
    assert metrics["open_payables"] == 3
    assert metrics["scheduled_receivables"] == 2
    assert metrics["scheduled_payables"] == 3
    assert metrics["receivables_missing_due_date"] == 1
    assert metrics["payables_missing_due_date"] == 0
    assert metrics["net_movements_90d"] == [
        {"currency_code": "COP", "amount": "250.00"},
        {"currency_code": "USD", "amount": "-100.00"},
    ]
    periods = {period["key"]: period for period in metrics["cash_flow_periods"]}
    assert periods["next_7_days"]["net_movements"] == [
        {"currency_code": "COP", "amount": "300.00"}
    ]
    assert periods["days_8_30"]["net_movements"] == [
        {"currency_code": "USD", "amount": "-100.00"}
    ]
    assert periods["overdue"]["projected_outflows"] == [
        {"currency_code": "COP", "amount": "50.00"}
    ]
    finding_codes = {
        finding["code"] for finding in body["report"]["findings"]
    }
    assert "CASH_FLOW_ITEMS_MISSING_DUE_DATE" in finding_codes
    assert "NEGATIVE_NET_MOVEMENT_WITHIN_90_DAYS" in finding_codes
    assert "saldo bancario" in body["conversation"]["response"]

    individual = client.post(
        endpoint,
        headers=headers,
        json={"message": "Muéstrame la factura del proveedor Alfa"},
    )
    assert individual.status_code == 200
    assert individual.json()["conversation"]["outcome"] == "out_of_scope"

    bank_balance = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Cuánto dinero tengo disponible?"},
    )
    assert bank_balance.status_code == 200
    assert bank_balance.json()["conversation"]["outcome"] == "out_of_scope"
    assert "saldo bancario" in bank_balance.json()["conversation"]["response"]

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord).where(
                    AgentExecutionRecord.company_id == company_id,
                    AgentExecutionRecord.agent_id == "cash_flow",
                )
            )
        )
        assert len(executions) == 3
        assert all(execution.status == "succeeded" for execution in executions)
    finally:
        db.close()
