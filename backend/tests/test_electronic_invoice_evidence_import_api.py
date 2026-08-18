"""Cobertura de carga auditable y revisión operativa de evidencia electrónica."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord
from app.models.electronic_invoicing import ElectronicInvoiceEvidenceImportRowRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Electronic evidence test user",
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


def _invoice(company_id: str, source_id: str, owner_id: int, number: str) -> InvoiceRecord:
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type="sale",
        issue_date=date(2026, 8, 1),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=Decimal("100"),
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=Decimal("100"),
        number=number,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def _xlsx_content() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["numero_factura", "estado_electronico", "cufe", "fecha_respuesta"])
    sheet.append(["FE-003", "rejected", "private-cufe-003", "2026-08-02T10:15:00Z"])
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    return content.getvalue()


def test_electronic_evidence_import_is_auditable_idempotent_and_keeps_private_values_out_of_views(client):
    suffix = uuid4().hex
    owner = _user(f"evidence-owner-{suffix}@test.local")
    viewer = _user(f"evidence-viewer-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant evidencia {suffix}", "company_name": "Empresa evidencia"},
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
            "connector_id": "electronic_evidence_test",
            "display_name": "Datos electrónicos de prueba",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["invoices"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]
    db = SessionLocal()
    try:
        db.add_all([
            _invoice(company_id, source_id, owner.id, "FE-001"),
            _invoice(company_id, source_id, owner.id, "FE-002"),
            _invoice(company_id, source_id, owner.id, "FE-003"),
        ])
        db.commit()
    finally:
        db.close()

    endpoint = f"/api/v1/companies/{company_id}/electronic-invoicing/imports"
    content = (
        "numero_factura,estado_electronico,cufe,fecha_respuesta\n"
        "FE-001,accepted,private-cufe-001,2026-08-02T10:15:00Z\n"
        "FE-002,pending,,\n"
        "FE-001,accepted,private-cufe-001,2026-08-02T10:15:00Z\n"
        "FE-404,accepted,private-cufe-404,\n"
        "FE-003,not-a-status,private-cufe-003,\n"
    ).encode()
    imported = client.post(
        endpoint,
        headers=_headers(owner),
        files={"file": ("evidencia.csv", content, "text/csv")},
    )
    assert imported.status_code == 200
    body = imported.json()
    assert body["accepted_rows"] == 2
    assert body["duplicate_rows"] == 1
    assert body["rejections"] == [
        {"row_number": 5, "message": "No existe una factura de venta con ese número en la empresa."},
        {"row_number": 6, "message": "El estado electrónico no es reconocido."},
    ]
    assert "private-cufe" not in imported.text

    repeated = client.post(
        endpoint,
        headers=_headers(owner),
        files={"file": ("evidencia.csv", content, "text/csv")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["accepted_rows"] == 0
    assert repeated.json()["duplicate_rows"] == 3

    xlsx = client.post(
        endpoint,
        headers=_headers(owner),
        files={
            "file": (
                "evidencia.xlsx",
                _xlsx_content(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert xlsx.status_code == 200
    assert xlsx.json()["accepted_rows"] == 1

    assert client.post(
        endpoint,
        headers=_headers(viewer),
        files={"file": ("evidencia.csv", content, "text/csv")},
    ).status_code == 403

    exceptions_endpoint = f"/api/v1/companies/{company_id}/electronic-invoicing/exceptions"
    exceptions = client.get(exceptions_endpoint, headers=_headers(owner))
    assert exceptions.status_code == 200
    exception_body = exceptions.json()
    rejected = next(item for item in exception_body["items"] if item["invoice_number"] == "FE-003")
    assert "ELECTRONIC_STATUS_REJECTED" in rejected["issue_codes"]
    assert "electronic_reference" not in rejected
    assert "private-cufe" not in exceptions.text
    viewer_exceptions = client.get(exceptions_endpoint, headers=_headers(viewer))
    assert viewer_exceptions.status_code == 200
    assert viewer_exceptions.json()["can_import"] is False

    imports = client.get(endpoint, headers=_headers(owner))
    assert imports.status_code == 200
    assert imports.json()["total"] == 3
    import_id = body["import_id"]
    audit = client.get(f"{endpoint}/{import_id}/rows", headers=_headers(owner))
    assert audit.status_code == 200
    assert audit.json()["total"] == 5
    assert "private-cufe" not in audit.text
    assert any(item["outcome"] == "rejected" for item in audit.json()["items"])

    db = SessionLocal()
    try:
        invoices = {
            record.number: record
            for record in db.scalars(
                select(InvoiceRecord).where(InvoiceRecord.company_id == company_id)
            )
        }
        assert invoices["FE-001"].electronic_status == "accepted"
        assert invoices["FE-002"].electronic_status == "pending"
        assert invoices["FE-003"].electronic_status == "rejected"
        audit_rows = list(
            db.scalars(
                select(ElectronicInvoiceEvidenceImportRowRecord).where(
                    ElectronicInvoiceEvidenceImportRowRecord.import_id == import_id
                )
            )
        )
        assert len(audit_rows) == 5
        assert all("private-cufe" not in (row.reason or "") for row in audit_rows)
    finally:
        db.close()
