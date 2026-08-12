from datetime import date
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
import pytest

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Invoice terms test user",
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


def _onboard(client, user: User) -> tuple[str, str]:
    suffix = uuid4().hex
    response = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(user),
        json={"tenant_name": f"Terms tenant {suffix}", "company_name": "Terms company"},
    )
    assert response.status_code == 201
    return response.json()["tenant"]["id"], response.json()["company"]["id"]


def _source(
    client,
    user: User,
    tenant_id: str,
    company_id: str,
    *,
    connector_id: str,
    kind: str,
    mode: str,
) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(user),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": connector_id,
            "display_name": "Invoice terms source",
            "kind": kind,
            "mode": mode,
            "capabilities": ["invoices", "file_import_export"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _profile(client, user: User, source_id: str, file_format: str, mapping: dict[str, str]) -> str:
    response = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=_headers(user),
        json={"entity": "invoices", "file_format": file_format, "column_mapping": mapping},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _import(client, user: User, source_id: str, profile_id: str, filename: str, content: bytes):
    return client.post(
        f"/api/v1/data-sources/{source_id}/imports/accounting",
        headers=_headers(user),
        data={"profile_id": profile_id},
        files={"file": (filename, content, "application/octet-stream")},
    )


def _invoice_payload(**overrides):
    payload = {
        "invoice_type": "sale",
        "issue_date": "2026-08-10",
        "lines": [
            {
                "description": "Servicio de prueba",
                "quantity": "1",
                "unit_price": "100",
            }
        ],
        "number": "FV-TERMS-001",
    }
    payload.update(overrides)
    return payload


def test_manual_invoice_derives_due_date_and_records_update_actor(client):
    suffix = uuid4().hex
    owner = _create_user(f"invoice-terms-manual-{suffix}@test.local")
    tenant_id, company_id = _onboard(client, owner)
    source_id = _source(
        client,
        owner,
        tenant_id,
        company_id,
        connector_id="manual_terms",
        kind="manual_entry",
        mode="manual",
    )

    response = client.post(
        f"/api/v1/data-sources/{source_id}/manual/invoices",
        headers=_headers(owner, "invoice-terms-manual"),
        json=_invoice_payload(payment_terms_days=30),
    )

    assert response.status_code == 201
    assert response.json()["payment_terms_days"] == 30
    assert response.json()["due_date"] == "2026-09-09"

    inconsistent = client.post(
        f"/api/v1/data-sources/{source_id}/manual/invoices",
        headers=_headers(owner, "invoice-terms-inconsistent"),
        json=_invoice_payload(
            number="FV-TERMS-INVALID",
            due_date="2026-08-11",
            payment_terms_days=0,
        ),
    )
    assert inconsistent.status_code == 422
    assert inconsistent.json()["error"]["code"] == "VALIDATION_ERROR"

    db = SessionLocal()
    try:
        invoice = db.get(InvoiceRecord, response.json()["id"])
        assert invoice is not None
        assert invoice.due_date == date(2026, 9, 9)
        assert invoice.payment_terms_days == 30
        assert invoice.updated_by_user_id == owner.id
        assert invoice.updated_at is not None
    finally:
        db.close()


def test_canonical_invoice_derives_due_date_when_only_terms_are_present():
    from app.providers.canonical import Invoice, InvoiceLine, InvoiceType

    invoice = Invoice(
        company_id=uuid4(),
        invoice_type=InvoiceType.SALE,
        issue_date=date(2026, 8, 10),
        payment_terms_days=0,
        lines=(InvoiceLine(description="Servicio", quantity=1, unit_price=100),),
        subtotal=100,
        total=100,
    )

    assert invoice.due_date == date(2026, 8, 10)


def test_csv_invoice_import_derives_due_date_and_rejects_inconsistent_terms(client):
    suffix = uuid4().hex
    owner = _create_user(f"invoice-terms-csv-{suffix}@test.local")
    tenant_id, company_id = _onboard(client, owner)
    source_id = _source(
        client,
        owner,
        tenant_id,
        company_id,
        connector_id="csv_import",
        kind="file_import",
        mode="file_upload",
    )
    profile_id = _profile(
        client,
        owner,
        source_id,
        "csv",
        {
            "number": "Numero",
            "invoice_type": "Tipo",
            "issue_date": "Fecha emision",
            "due_date": "Fecha vencimiento",
            "payment_terms_days": "Dias pago",
            "description": "Descripcion",
            "quantity": "Cantidad",
            "unit_price": "Precio",
        },
    )
    content = (
        b"Numero,Tipo,Fecha emision,Fecha vencimiento,Dias pago,Descripcion,Cantidad,Precio\n"
        b"FV-CSV-VALID,sale,2026-08-10,,30,Servicio principal,1,100\n"
        b"FV-CSV-VALID,sale,2026-08-10,,,Servicio adicional,1,100\n"
        b"FV-CSV-INVALID,sale,2026-08-10,2026-09-10,30,Servicio,1,100\n"
    )

    response = _import(client, owner, source_id, profile_id, "facturas.csv", content)

    assert response.status_code == 200
    assert response.json()["accepted_rows"] == 2
    assert response.json()["rejections"][0]["row_number"] == 4

    db = SessionLocal()
    try:
        invoice = db.query(InvoiceRecord).filter_by(company_id=company_id, number="FV-CSV-VALID").one()
        assert invoice.due_date == date(2026, 9, 9)
        assert invoice.payment_terms_days == 30
    finally:
        db.close()


def test_csv_invoice_import_rejects_inconsistent_terms_between_lines(client):
    suffix = uuid4().hex
    owner = _create_user(f"invoice-terms-conflict-{suffix}@test.local")
    tenant_id, company_id = _onboard(client, owner)
    source_id = _source(
        client,
        owner,
        tenant_id,
        company_id,
        connector_id="csv_import",
        kind="file_import",
        mode="file_upload",
    )
    profile_id = _profile(
        client,
        owner,
        source_id,
        "csv",
        {
            "number": "Numero",
            "invoice_type": "Tipo",
            "issue_date": "Fecha emision",
            "payment_terms_days": "Dias pago",
            "description": "Descripcion",
            "quantity": "Cantidad",
            "unit_price": "Precio",
        },
    )
    content = (
        b"Numero,Tipo,Fecha emision,Dias pago,Descripcion,Cantidad,Precio\n"
        b"FV-CSV-CONFLICT,sale,2026-08-10,30,Servicio uno,1,100\n"
        b"FV-CSV-CONFLICT,sale,2026-08-10,60,Servicio dos,1,100\n"
    )

    response = _import(client, owner, source_id, profile_id, "facturas.csv", content)

    assert response.status_code == 200
    assert response.json()["accepted_rows"] == 0
    assert [rejection["row_number"] for rejection in response.json()["rejections"]] == [2, 3]


def test_xlsx_invoice_import_accepts_zero_day_terms(client):
    suffix = uuid4().hex
    owner = _create_user(f"invoice-terms-xlsx-{suffix}@test.local")
    tenant_id, company_id = _onboard(client, owner)
    source_id = _source(
        client,
        owner,
        tenant_id,
        company_id,
        connector_id="xlsx_import",
        kind="file_import",
        mode="file_upload",
    )
    profile_id = _profile(
        client,
        owner,
        source_id,
        "xlsx",
        {
            "number": "Numero",
            "invoice_type": "Tipo",
            "issue_date": "Fecha emision",
            "due_date": "Fecha vencimiento",
            "payment_terms_days": "Dias pago",
            "description": "Descripcion",
            "quantity": "Cantidad",
            "unit_price": "Precio",
        },
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Numero",
            "Tipo",
            "Fecha emision",
            "Fecha vencimiento",
            "Dias pago",
            "Descripcion",
            "Cantidad",
            "Precio",
        ]
    )
    sheet.append(["FV-XLSX-VALID", "sale", "2026-08-10", "2026-08-10", 0, "Servicio", 1, 100])
    content = BytesIO()
    workbook.save(content)

    response = _import(client, owner, source_id, profile_id, "facturas.xlsx", content.getvalue())

    assert response.status_code == 200
    assert response.json()["accepted_rows"] == 1
    db = SessionLocal()
    try:
        invoice = db.query(InvoiceRecord).filter_by(company_id=company_id, number="FV-XLSX-VALID").one()
        assert invoice.due_date == date(2026, 8, 10)
        assert invoice.payment_terms_days == 0
    finally:
        db.close()
