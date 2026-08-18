"""Flujo integrado del agente de facturación electrónica de solo lectura."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord
from app.models.agent import AgentExecutionRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(email=email, full_name="Electronic invoicing test user", password_hash=hash_password("password123"))
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
    number: str | None,
    electronic_status: str | None,
    electronic_reference: str | None,
    issue_date: date | None = None,
    total: str = "100",
) -> InvoiceRecord:
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type="sale",
        issue_date=issue_date or date.today(),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=Decimal("100"),
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=Decimal(total),
        number=number,
        electronic_status=electronic_status,
        electronic_reference=electronic_reference,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def test_electronic_invoicing_agent_reports_aggregate_evidence_without_dian_connection(client):
    suffix = uuid4().hex
    owner = _create_user(f"electronic-invoicing-{suffix}@test.local")
    headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": f"Tenant factura {suffix}", "company_name": "Empresa factura"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source = client.post(
        "/api/v1/data-sources",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "electronic_invoice_manual",
            "display_name": "Datos electrónicos",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]

    db = SessionLocal()
    try:
        db.add_all(
            [
                _invoice(company_id=company_id, source_id=source_id, owner_id=owner.id, number="FE-001", electronic_status="accepted", electronic_reference="cufe-importado-1"),
                _invoice(company_id=company_id, source_id=source_id, owner_id=owner.id, number="FE-002", electronic_status="pending", electronic_reference=None),
                _invoice(company_id=company_id, source_id=source_id, owner_id=owner.id, number="FE-003", electronic_status="rejected", electronic_reference="cufe-importado-3"),
                _invoice(company_id=company_id, source_id=source_id, owner_id=owner.id, number=None, electronic_status=None, electronic_reference=None),
                _invoice(company_id=company_id, source_id=source_id, owner_id=owner.id, number="FE-005", electronic_status="accepted", electronic_reference="cufe-importado-5", issue_date=date.today() + timedelta(days=1), total="99"),
            ]
        )
        db.commit()
    finally:
        db.close()

    endpoint = f"/api/v1/companies/{company_id}/agents/electronic-invoicing/chat"
    status_response = client.post(
        endpoint,
        headers=headers,
        json={"message": "¿Cuántas facturas están pendientes o rechazadas?"},
    )
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["agent_id"] == "electronic_invoicing"
    assert body["workflow"] == "electronic_invoicing"
    assert body["conversation"]["outcome"] == "answered"
    metrics = body["report"]["metrics"]
    assert metrics == {
        "as_of_date": date.today().isoformat(),
        "sales_invoices": 5,
        "electronic_status_recorded": 4,
        "accepted_electronic_invoices": 2,
        "pending_electronic_invoices": 1,
        "rejected_electronic_invoices": 1,
        "invoices_without_electronic_status": 1,
        "invoices_without_electronic_reference": 2,
        "invoices_missing_number": 1,
        "invoices_without_recipient": 5,
        "invoices_with_total_mismatch": 1,
        "future_dated_sales_invoices": 1,
        "electronic_status_coverage": "80.00",
    }
    finding_codes = {item["code"] for item in body["report"]["findings"]}
    assert {
        "DIAN_CONNECTION_NOT_CONFIGURED",
        "ELECTRONIC_INVOICES_REJECTED",
        "ELECTRONIC_INVOICES_PENDING",
        "ELECTRONIC_STATUS_MISSING",
        "ELECTRONIC_INVOICE_TOTAL_MISMATCH",
    } <= finding_codes
    assert "pendientes" in body["conversation"]["response"]

    dian = client.post(endpoint, headers=headers, json={"message": "¿El aplicativo ya valida documentos ante la DIAN?"})
    assert dian.status_code == 200
    assert dian.json()["conversation"]["outcome"] == "answered"
    assert "no está configurada" in dian.json()["conversation"]["response"]

    individual = client.post(endpoint, headers=headers, json={"message": "Muéstrame el CUFE de la factura FE-001"})
    assert individual.status_code == 200
    assert individual.json()["conversation"]["outcome"] == "out_of_scope"

    write = client.post(endpoint, headers=headers, json={"message": "Emite la factura electrónica pendiente"})
    assert write.status_code == 200
    assert write.json()["conversation"]["outcome"] == "out_of_scope"

    db = SessionLocal()
    try:
        executions = list(db.scalars(select(AgentExecutionRecord).where(AgentExecutionRecord.company_id == company_id, AgentExecutionRecord.agent_id == "electronic_invoicing")))
        assert len(executions) == 4
        assert all(execution.status == "succeeded" for execution in executions)
    finally:
        db.close()
