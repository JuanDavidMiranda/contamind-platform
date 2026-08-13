"""Cobertura integrada de importación, revisión y agente bancario."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.agent import AgentExecutionRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        record = User(
            email=email,
            full_name="Bank reconciliation user",
            password_hash=hash_password("password123"),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
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
    amount: str,
) -> InvoiceRecord:
    value = Decimal(amount)
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type=invoice_type,
        issue_date=date(2026, 8, 1),
        due_date=date(2026, 8, 13),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=value,
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=value,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def test_bank_reconciliation_imports_suggests_and_requires_human_confirmation(client):
    suffix = uuid4().hex
    owner = _user(f"bank-owner-{suffix}@test.local")
    viewer = _user(f"bank-viewer-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant banco {suffix}", "company_name": "Empresa banco"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    assert client.put(
        "/api/v1/company-memberships",
        headers=_headers(owner),
        json={"user_id": viewer.id, "company_id": company_id, "role": "viewer"},
    ).status_code == 200
    source = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "bank_reconciliation_test",
            "display_name": "Contabilidad prueba bancaria",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]

    sale = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        amount="100",
    )
    purchase = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="purchase",
        amount="50",
    )
    ambiguous_one = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        amount="200",
    )
    ambiguous_two = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        amount="200",
    )
    db = SessionLocal()
    try:
        db.add_all([sale, purchase, ambiguous_one, ambiguous_two])
        db.flush()
        for invoice, amount in (
            (sale, "100"),
            (purchase, "50"),
            (ambiguous_one, "200"),
            (ambiguous_two, "200"),
        ):
            db.add(
                PaymentRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    data_source_id=source_id,
                    payment_date=date(2026, 8, 13),
                    amount=Decimal(amount),
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    invoice_id=invoice.id,
                    idempotency_key=uuid4().hex,
                    created_by_user_id=owner.id,
                )
            )
        db.commit()
    finally:
        db.close()

    accounts_endpoint = f"/api/v1/companies/{company_id}/bank-reconciliation/accounts"
    account_response = client.post(
        accounts_endpoint,
        headers=_headers(owner),
        json={
            "name": "Cuenta operativa COP",
            "bank_name": "Banco de prueba",
            "currency_code": "COP",
            "confirmed": True,
        },
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]
    sensitive_alias = client.post(
        accounts_endpoint,
        headers=_headers(owner),
        json={
            "name": "Cuenta 1234 5678 9012",
            "currency_code": "COP",
            "confirmed": True,
        },
    )
    assert sensitive_alias.status_code == 422
    assert client.post(
        accounts_endpoint,
        headers=_headers(viewer),
        json={"name": "No autorizada", "currency_code": "COP", "confirmed": True},
    ).status_code == 403
    viewer_accounts = client.get(accounts_endpoint, headers=_headers(viewer))
    assert viewer_accounts.status_code == 200
    assert viewer_accounts.json()["can_manage"] is False
    assert viewer_accounts.json()["can_configure"] is False

    csv_content = (
        "fecha,valor,descripcion,referencia,moneda\n"
        "2026-08-13,100,Recaudo registrado,TX-001,COP\n"
        "2026-08-13,-50,Pago registrado,TX-002,COP\n"
        "2026-08-13,200,Recaudo ambiguo,TX-003,COP\n"
        "2026-08-13,75,Movimiento sin pago,TX-004,COP\n"
        "fecha-invalida,30,Fila rechazada,TX-005,COP\n"
    ).encode()
    import_endpoint = (
        f"/api/v1/companies/{company_id}/bank-reconciliation/"
        f"accounts/{account_id}/imports"
    )
    imported = client.post(
        import_endpoint,
        headers=_headers(owner),
        files={"file": ("extracto.csv", csv_content, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["accepted_rows"] == 4
    assert imported.json()["duplicate_rows"] == 0
    assert imported.json()["rejections"] == [
        {
            "row_number": 6,
            "message": "La fecha debe usar AAAA-MM-DD o DD/MM/AAAA.",
        }
    ]
    repeated = client.post(
        import_endpoint,
        headers=_headers(owner),
        files={"file": ("extracto.csv", csv_content, "text/csv")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["accepted_rows"] == 0
    assert repeated.json()["duplicate_rows"] == 4

    competing = client.post(
        import_endpoint,
        headers=_headers(owner),
        files={
            "file": (
                "extracto-adicional.csv",
                (
                    "fecha,valor,descripcion,referencia,moneda\n"
                    "2026-08-14,100,Segundo recaudo posible,TX-006,COP\n"
                ).encode(),
                "text/csv",
            )
        },
    )
    assert competing.status_code == 200
    assert competing.json()["accepted_rows"] == 1

    transactions_endpoint = (
        f"/api/v1/companies/{company_id}/bank-reconciliation/transactions"
    )
    transactions = client.get(transactions_endpoint, headers=_headers(owner))
    assert transactions.status_code == 200
    body = transactions.json()
    assert body["total"] == 5
    by_reference = {item["reference"]: item for item in body["items"]}
    assert by_reference["TX-001"]["status"] == "suggested"
    assert by_reference["TX-006"]["status"] == "suggested"
    assert by_reference["TX-002"]["status"] == "suggested"
    assert by_reference["TX-003"]["status"] == "pending"
    assert by_reference["TX-003"]["match_candidate_count"] == 2
    assert by_reference["TX-004"]["status"] == "pending"
    assert by_reference["TX-004"]["match_candidate_count"] == 0

    suggested_id = by_reference["TX-001"]["id"]
    review_endpoint = f"{transactions_endpoint}/{suggested_id}"
    assert client.patch(
        review_endpoint,
        headers=_headers(viewer),
        json={"action": "confirm", "confirmed": True},
    ).status_code == 403
    confirmed = client.patch(
        review_endpoint,
        headers=_headers(owner),
        json={"action": "confirm", "confirmed": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "reconciled"
    assert confirmed.json()["matched_payment_id"] is not None
    stale_suggestion = client.patch(
        f"{transactions_endpoint}/{by_reference['TX-006']['id']}",
        headers=_headers(owner),
        json={"action": "confirm", "confirmed": True},
    )
    assert stale_suggestion.status_code == 409
    refreshed = client.get(transactions_endpoint, headers=_headers(owner)).json()
    refreshed_by_reference = {
        item["reference"]: item for item in refreshed["items"]
    }
    assert refreshed_by_reference["TX-006"]["status"] == "pending"
    assert refreshed_by_reference["TX-006"]["match_candidate_count"] == 0

    chat_endpoint = (
        f"/api/v1/companies/{company_id}/agents/bank-reconciliation/chat"
    )
    diagnostic = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "¿Cuál es la cobertura de conciliación?"},
    )
    assert diagnostic.status_code == 200
    diagnostic_body = diagnostic.json()
    assert diagnostic_body["agent_id"] == "bank_reconciliation"
    assert diagnostic_body["workflow"] == "bank_reconciliation"
    metrics = diagnostic_body["report"]["metrics"]
    assert metrics["imported_transactions"] == 5
    assert metrics["reconciled_transactions"] == 1
    assert metrics["suggested_matches"] == 1
    assert metrics["ambiguous_transactions"] == 1
    assert metrics["unmatched_transactions"] == 2
    assert metrics["reconciliation_rate"] == "20.00"
    assert "confirmación humana" in diagnostic_body["conversation"]["response"]

    pending = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "¿Cuántos movimientos siguen sin conciliar?"},
    )
    assert pending.status_code == 200
    assert pending.json()["conversation"]["outcome"] == "answered"
    assert "movimientos pendientes" in pending.json()["conversation"]["response"]

    balance = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "¿Cuál es mi saldo bancario disponible?"},
    )
    assert balance.status_code == 200
    assert balance.json()["conversation"]["outcome"] == "out_of_scope"

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord).where(
                    AgentExecutionRecord.company_id == company_id,
                    AgentExecutionRecord.agent_id == "bank_reconciliation",
                )
            )
        )
        assert len(executions) == 3
        assert all(execution.status == "succeeded" for execution in executions)
    finally:
        db.close()
