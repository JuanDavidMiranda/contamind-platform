"""El agente de pagos sólo expone agregados de compras."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(email=email, full_name="Payables agent", password_hash=hash_password("password123"))
        db.add(user); db.commit(); db.refresh(user)
        return user
    finally:
        db.close()


def test_payables_agent_reports_aggregates_and_blocks_individual_requests(client):
    suffix = uuid4().hex
    user = _user(f"payables-agent-{suffix}@test.local")
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    onboard = client.post("/api/v1/companies/onboarding", headers=headers, json={"tenant_name": f"Payables {suffix}", "company_name": "Compras"})
    assert onboard.status_code == 201
    company_id, tenant_id = onboard.json()["company"]["id"], onboard.json()["tenant"]["id"]
    source = client.post("/api/v1/data-sources", headers=headers, json={"tenant_id": tenant_id, "company_id": company_id, "connector_id": "payables_agent", "display_name": "Compras", "kind": "manual_entry", "mode": "manual", "capabilities": ["invoices"]})
    assert source.status_code == 201
    amount = Decimal("100")
    db = SessionLocal()
    try:
        db.add(InvoiceRecord(id=str(uuid4()), company_id=company_id, data_source_id=source.json()["id"], invoice_type="purchase", issue_date=date(2026, 8, 1), due_date=date(2026, 8, 5), currency_code="COP", exchange_rate=Decimal("1"), subtotal=amount, tax_total=Decimal("0"), withholding_total=Decimal("0"), total=amount, idempotency_key=uuid4().hex, created_by_user_id=user.id))
        db.commit()
    finally:
        db.close()
    response = client.post(f"/api/v1/companies/{company_id}/agents/payables/chat", headers=headers, json={"message": "¿Qué obligaciones debo revisar primero?"})
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "payables"
    assert body["report"]["metrics"]["overdue_purchase_invoices"] == 1
    assert "OVERDUE_PURCHASE_INVOICES" in {item["code"] for item in body["report"]["findings"]}
    blocked = client.post(f"/api/v1/companies/{company_id}/agents/payables/chat", headers=headers, json={"message": "Dame la factura del proveedor 900123456"})
    assert blocked.status_code == 200
    assert blocked.json()["conversation"]["outcome"] == "clarification_needed"
    assert "900123456" not in response.text
