"""Cobertura integrada del diagnóstico de tesorería y liquidez."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.agent import AgentExecutionRecord
from app.models.bank_reconciliation import (
    BankAccountRecord,
    BankStatementImportRecord,
    BankTransactionRecord,
)
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Treasury test user",
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
) -> InvoiceRecord:
    amount = Decimal(total)
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type=invoice_type,
        issue_date=date.today() - timedelta(days=10),
        due_date=due_date,
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=amount,
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=amount,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def test_treasury_agent_combines_projection_and_reconciliation_without_claiming_availability(client):
    suffix = uuid4().hex
    owner = _create_user(f"treasury-{suffix}@test.local")
    headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={
            "tenant_name": f"Tenant tesorería {suffix}",
            "company_name": "Empresa tesorería",
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
            "connector_id": "treasury_manual",
            "display_name": "Datos para tesorería",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    today = date.today()

    db = SessionLocal()
    try:
        account = BankAccountRecord(
            id=str(uuid4()),
            company_id=company_id,
            name="Cuenta tesorería COP",
            currency_code="COP",
            created_by_user_id=owner.id,
        )
        statement_import = BankStatementImportRecord(
            id=str(uuid4()),
            company_id=company_id,
            bank_account_id=account.id,
            accepted_rows=3,
            created_by_user_id=owner.id,
        )
        reconciled_payment = PaymentRecord(
            id=str(uuid4()),
            company_id=company_id,
            data_source_id=source_id,
            payment_date=today,
            amount=Decimal("100"),
            currency_code="COP",
            exchange_rate=Decimal("1"),
            idempotency_key=uuid4().hex,
            created_by_user_id=owner.id,
        )
        db.add_all(
            [
                _invoice(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_type="sale",
                    due_date=today + timedelta(days=5),
                    total="1000",
                ),
                _invoice(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_type="sale",
                    due_date=today - timedelta(days=1),
                    total="20",
                ),
                _invoice(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_type="purchase",
                    due_date=today + timedelta(days=10),
                    total="1500",
                ),
                _invoice(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_type="purchase",
                    due_date=None,
                    total="100",
                ),
                account,
                statement_import,
                reconciled_payment,
            ]
        )
        db.flush()
        db.add_all(
            [
                BankTransactionRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    bank_account_id=account.id,
                    import_id=statement_import.id,
                    transaction_date=today,
                    amount=Decimal("100"),
                    currency_code="COP",
                    fingerprint=uuid4().hex,
                    status="reconciled",
                    matched_payment_id=reconciled_payment.id,
                    created_by_user_id=owner.id,
                ),
                BankTransactionRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    bank_account_id=account.id,
                    import_id=statement_import.id,
                    transaction_date=today,
                    amount=Decimal("-50"),
                    currency_code="COP",
                    fingerprint=uuid4().hex,
                    status="suggested",
                    match_candidate_count=1,
                    created_by_user_id=owner.id,
                ),
                BankTransactionRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    bank_account_id=account.id,
                    import_id=statement_import.id,
                    transaction_date=today,
                    amount=Decimal("75"),
                    currency_code="COP",
                    fingerprint=uuid4().hex,
                    status="pending",
                    match_candidate_count=0,
                    created_by_user_id=owner.id,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    endpoint = f"/api/v1/companies/{company_id}/agents/treasury/chat"
    projection = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Qué movimiento neto se proyecta a 30 días por moneda?"},
    )
    assert projection.status_code == 200
    body = projection.json()
    assert body["agent_id"] == "treasury"
    assert body["workflow"] == "treasury"
    assert body["conversation"]["outcome"] == "answered"
    assert body["report"]["metrics"]["projected_inflows_30d"] == [
        {"currency_code": "COP", "amount": "1020.00"}
    ]
    assert body["report"]["metrics"]["projected_outflows_30d"] == [
        {"currency_code": "COP", "amount": "1500.00"}
    ]
    assert body["report"]["metrics"]["net_projected_movements_30d"] == [
        {"currency_code": "COP", "amount": "-480.00"}
    ]
    assert body["report"]["metrics"]["reconciliation_rate"] == "33.33"
    finding_codes = {finding["code"] for finding in body["report"]["findings"]}
    assert "TREASURY_POSITION_REQUIRES_VERIFIED_BANK_BALANCE" in finding_codes
    assert "TREASURY_RECONCILIATION_REQUIRES_REVIEW" in finding_codes
    assert "TREASURY_PROJECTED_MOVEMENTS_MISSING_DUE_DATE" in finding_codes
    assert "TREASURY_NEGATIVE_PROJECTED_NET_30D" in finding_codes
    assert "saldo disponible" in body["conversation"]["response"]

    priorities = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Qué debo revisar primero para tesorería?"},
    )
    assert priorities.status_code == 200
    priority_response = priorities.json()["conversation"]["response"]
    assert "TREASURY_" not in priority_response
    assert "Qué hacer:" in priority_response
    assert "movimientos por revisar" in priority_response

    availability = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Puedo pagar las obligaciones mañana?"},
    )
    assert availability.status_code == 200
    assert availability.json()["conversation"]["outcome"] == "out_of_scope"
    assert "disponibilidad real" in availability.json()["conversation"]["response"]

    individual = client.post(
        endpoint,
        headers=headers,
        json={"message": "Programa el pago de la factura del proveedor Alfa"},
    )
    assert individual.status_code == 200
    assert individual.json()["conversation"]["outcome"] == "out_of_scope"

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord).where(
                    AgentExecutionRecord.company_id == company_id,
                    AgentExecutionRecord.agent_id == "treasury",
                )
            )
        )
        assert len(executions) == 4
        assert all(execution.status == "succeeded" for execution in executions)
    finally:
        db.close()
