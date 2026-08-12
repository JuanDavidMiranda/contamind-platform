"""Cartera operativa: vencimientos, antigüedad y trazabilidad de seguimiento."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.user import User
from app.services.receivables_service import ReceivablesService
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Receivables operations test user",
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


def _onboard(client, owner: User, suffix: str) -> tuple[str, str]:
    response = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant cartera operativa {suffix}", "company_name": "Empresa cartera"},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload["tenant"]["id"], payload["company"]["id"]


def _source(client, owner: User, tenant_id: str, company_id: str) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "receivables_operations_manual",
            "display_name": "Datos de cartera operativa",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices", "payments"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _add_viewer(client, owner: User, viewer: User, company_id: str) -> None:
    response = client.put(
        "/api/v1/company-memberships",
        headers=_headers(owner),
        json={"user_id": viewer.id, "company_id": company_id, "role": "viewer"},
    )
    assert response.status_code == 200


def _invoice(
    *,
    company_id: str,
    source_id: str,
    owner_id: int,
    issue_date: date,
    due_date: date | None,
    total: str,
    key: str,
) -> InvoiceRecord:
    amount = Decimal(total)
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type="sale",
        issue_date=issue_date,
        due_date=due_date,
        payment_terms_days=(due_date - issue_date).days if due_date else None,
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=amount,
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=amount,
        idempotency_key=key,
        created_by_user_id=owner_id,
        updated_by_user_id=owner_id,
    )


def _payment(
    *,
    company_id: str,
    source_id: str,
    owner_id: int,
    invoice_id: str,
    payment_date: date,
    amount: str,
    key: str,
) -> PaymentRecord:
    return PaymentRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        payment_date=payment_date,
        amount=Decimal(amount),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        invoice_id=invoice_id,
        idempotency_key=key,
        created_by_user_id=owner_id,
    )


def test_open_items_expose_aging_without_notes_and_terms_changes_are_confirmed(client):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-operations-owner-{suffix}@test.local")
    viewer = _create_user(f"receivables-operations-viewer-{suffix}@test.local")
    tenant_id, company_id = _onboard(client, owner, suffix)
    _add_viewer(client, owner, viewer, company_id)
    source_id = _source(client, owner, tenant_id, company_id)
    as_of = date(2026, 8, 12)

    overdue = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        issue_date=date(2026, 1, 1),
        due_date=date(2026, 5, 1),
        total="100",
        key="ops-overdue",
    )
    missing_terms = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        issue_date=date(2026, 8, 1),
        due_date=None,
        total="50",
        key="ops-missing-terms",
    )
    due_today = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        issue_date=date(2026, 7, 1),
        due_date=as_of,
        total="75",
        key="ops-due-today",
    )
    future = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        issue_date=date(2026, 8, 1),
        due_date=date(2026, 9, 1),
        total="80",
        key="ops-future",
    )
    settled = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        issue_date=date(2026, 8, 1),
        due_date=date(2026, 8, 31),
        total="100",
        key="ops-settled",
    )
    overdue_id = overdue.id
    missing_terms_id = missing_terms.id
    db = SessionLocal()
    try:
        db.add_all([overdue, missing_terms, due_today, future, settled])
        db.add_all(
            [
                _payment(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_id=overdue.id,
                    payment_date=date(2026, 5, 3),
                    amount="20",
                    key="ops-partial-payment",
                ),
                _payment(
                    company_id=company_id,
                    source_id=source_id,
                    owner_id=owner.id,
                    invoice_id=settled.id,
                    payment_date=date(2026, 8, 11),
                    amount="100",
                    key="ops-settled-payment",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    followup_response = client.post(
        f"/api/v1/companies/{company_id}/collection-followups",
        headers=_headers(owner),
        json={
            "invoice_id": overdue_id,
            "status": "promise_to_pay",
            "promised_date": "2026-08-01",
            "note": "Validar el soporte de pago antes de conciliar.",
            "confirmed": True,
        },
    )
    assert followup_response.status_code == 201

    endpoint = f"/api/v1/companies/{company_id}/receivables/open-items?as_of=2026-08-12"
    first_page = client.get(f"{endpoint}&limit=2", headers=_headers(viewer))
    second_page = client.get(f"{endpoint}&limit=2&offset=2", headers=_headers(viewer))
    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total"] == 4
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 2
    assert {
        item["invoice_id"] for item in first_page.json()["items"]
    }.isdisjoint({item["invoice_id"] for item in second_page.json()["items"]})

    viewer_response = client.get(endpoint, headers=_headers(viewer))
    assert viewer_response.status_code == 200
    payload = viewer_response.json()
    assert payload["can_manage"] is False
    assert payload["as_of"] == "2026-08-12"
    assert payload["total"] == 4
    assert {item["aging_bucket"] for item in payload["items"]} == {
        "overdue_91_plus",
        "missing_due_date",
        "due_today",
        "not_due",
    }
    overdue_item = next(item for item in payload["items"] if item["invoice_id"] == overdue_id)
    assert overdue_item["outstanding_amount"] == "80.00"
    assert overdue_item["latest_followup_status"] == "promise_to_pay"
    assert overdue_item["promised_date"] == "2026-08-01"
    assert "note" not in overdue_item
    assert "recipient" not in overdue_item

    owner_response = client.get(endpoint, headers=_headers(owner))
    assert owner_response.status_code == 200
    assert owner_response.json()["can_manage"] is True

    terms_endpoint = f"/api/v1/companies/{company_id}/receivables/invoices/{missing_terms_id}/terms"
    assert client.patch(
        terms_endpoint,
        headers=_headers(owner),
        json={"due_date": "2026-09-01", "confirmed": False},
    ).status_code == 422
    assert client.patch(
        terms_endpoint,
        headers=_headers(viewer),
        json={"due_date": "2026-09-01", "confirmed": True},
    ).status_code == 403

    updated = client.patch(
        terms_endpoint,
        headers=_headers(owner),
        json={"due_date": "2026-09-01", "confirmed": True},
    )
    assert updated.status_code == 200
    assert updated.json()["due_date"] == "2026-09-01"
    assert updated.json()["payment_terms_days"] is None
    assert updated.json()["updated_by_user_id"] == owner.id

    derived = client.patch(
        terms_endpoint,
        headers=_headers(owner),
        json={"payment_terms_days": 30, "confirmed": True},
    )
    assert derived.status_code == 200
    assert derived.json()["due_date"] == "2026-08-31"
    assert derived.json()["payment_terms_days"] == 30
    assert client.patch(
        terms_endpoint,
        headers=_headers(owner),
        json={"due_date": "2026-08-20", "payment_terms_days": 30, "confirmed": True},
    ).status_code == 422

    db = SessionLocal()
    try:
        invoice = db.scalar(select(InvoiceRecord).where(InvoiceRecord.id == missing_terms_id))
        assert invoice is not None
        assert invoice.due_date == date(2026, 8, 31)
        assert invoice.payment_terms_days == 30
        assert invoice.updated_by_user_id == owner.id

        report = ReceivablesService(db).analyze(UUID(company_id), as_of=as_of)
    finally:
        db.close()

    metrics = report.metrics
    assert metrics.open_sales_invoices == 4
    assert metrics.partially_paid_sales_invoices == 1
    assert metrics.sales_invoices_missing_due_date == 0
    assert metrics.due_today_sales_invoices == 1
    assert metrics.overdue_sales_invoices == 1
    assert metrics.seriously_overdue_sales_invoices == 1
    assert metrics.broken_payment_promises == 1
    assert metrics.open_payment_promises == 0
    assert metrics.settled_sales_invoices == 1
    assert metrics.average_days_to_collect == Decimal("10.00")
    assert {bucket.key for bucket in metrics.aging_buckets} == {
        "overdue_91_plus",
        "due_today",
        "not_due",
    }
    assert "SERIOUSLY_OVERDUE_SALES_INVOICES" in {finding.code for finding in report.findings}
    assert "BROKEN_PAYMENT_PROMISES" in {finding.code for finding in report.findings}
