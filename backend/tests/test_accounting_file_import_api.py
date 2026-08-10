from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
import pytest
from sqlalchemy import func, select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, ItemRecord, JournalEntryRecord, PaymentRecord, TaxRecord
from app.models.data_source import ImportBatchRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Accounting File Import Test User",
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


def _source(client, user: User, tenant_id: str, company_id: str, connector: str, capabilities: list[str]) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(user),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": connector,
            "display_name": f"Carga {connector}",
            "kind": "file_import",
            "mode": "file_upload",
            "capabilities": capabilities,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _profile(client, user: User, source_id: str, entity: str, file_format: str, mapping: dict[str, str]) -> str:
    response = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=_headers(user),
        json={"entity": entity, "file_format": file_format, "column_mapping": mapping},
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


def test_csv_imports_the_accounting_core_with_rejections_and_idempotency(client):
    suffix = uuid4().hex
    owner = _create_user(f"file-owner-{suffix}@test.local")
    operator = _create_user(f"file-operator-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant archivos {suffix}", "company_name": "Empresa archivos"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    assert client.put(
        "/api/v1/company-memberships",
        headers=_headers(owner),
        json={"user_id": operator.id, "company_id": company_id, "role": "operator"},
    ).status_code == 200
    source_id = _source(
        client,
        owner,
        tenant_id,
        company_id,
        "csv_import",
        ["parties", "taxes", "items", "invoices", "payments", "journals", "file_import_export"],
    )

    party_profile = _profile(
        client, owner, source_id, "parties", "csv", {"name": "Nombre", "document_number": "Documento"}
    )
    party_response = client.post(
        f"/api/v1/data-sources/{source_id}/imports/parties",
        headers=_headers(operator),
        data={"profile_id": party_profile},
        files={"file": ("terceros.csv", b"Nombre,Documento\nCliente archivo,900123456\n", "text/csv")},
    )
    assert party_response.status_code == 200

    tax_profile = _profile(
        client,
        owner,
        source_id,
        "taxes",
        "csv",
        {"code": "Codigo", "name": "Nombre", "rate": "Tarifa"},
    )
    tax_content = b"Codigo,Nombre,Tarifa\nIVA19,IVA 19,19\nRET,Retencion,\n"
    tax_response = _import(client, operator, source_id, tax_profile, "impuestos.csv", tax_content)
    assert tax_response.status_code == 200
    assert tax_response.json()["accepted_rows"] == 1
    assert tax_response.json()["rejections"][0]["row_number"] == 3
    retry_tax_response = _import(client, operator, source_id, tax_profile, "impuestos.csv", tax_content)
    assert retry_tax_response.status_code == 200
    assert retry_tax_response.json()["accepted_rows"] == 1

    item_profile = _profile(
        client,
        owner,
        source_id,
        "items",
        "csv",
        {
            "code": "Codigo",
            "name": "Nombre",
            "item_type": "Tipo",
            "unit_price": "Precio",
            "tax_codes": "Impuestos",
            "ledger_account": "Cuenta",
        },
    )
    assert _import(
        client,
        operator,
        source_id,
        item_profile,
        "items.csv",
        b"Codigo,Nombre,Tipo,Precio,Impuestos,Cuenta\nSERV01,Servicio,service,100,IVA19,4135\n",
    ).json()["accepted_rows"] == 1

    invoice_profile = _profile(
        client,
        owner,
        source_id,
        "invoices",
        "csv",
        {
            "number": "Numero",
            "invoice_type": "Tipo",
            "issue_date": "Fecha",
            "recipient_document_number": "Documento",
            "item_code": "Item",
            "description": "Descripcion",
            "quantity": "Cantidad",
            "unit_price": "Precio",
            "tax_codes": "Impuestos",
            "tax_total": "Total impuestos",
        },
    )
    invoice_response = _import(
        client,
        operator,
        source_id,
        invoice_profile,
        "facturas.csv",
        (
            b"Numero,Tipo,Fecha,Documento,Item,Descripcion,Cantidad,Precio,Impuestos,Total impuestos\n"
            b"FV-001,sale,2026-08-10,900123456,SERV01,Linea uno,1,100,IVA19,38\n"
            b"FV-001,sale,2026-08-10,900123456,SERV01,Linea dos,1,100,IVA19,38\n"
        ),
    )
    assert invoice_response.status_code == 200
    assert invoice_response.json()["accepted_rows"] == 2

    payment_profile = _profile(
        client,
        owner,
        source_id,
        "payments",
        "csv",
        {"payment_date": "Fecha", "amount": "Monto", "invoice_number": "Factura", "payment_method": "Medio"},
    )
    assert _import(
        client,
        operator,
        source_id,
        payment_profile,
        "pagos.csv",
        b"Fecha,Monto,Factura,Medio\n2026-08-10,238,FV-001,transferencia\n",
    ).json()["accepted_rows"] == 1

    journal_profile = _profile(
        client,
        owner,
        source_id,
        "journal_entries",
        "csv",
        {
            "source_reference": "Referencia",
            "entry_date": "Fecha",
            "description": "Descripcion",
            "account_code": "Cuenta",
            "debit": "Debito",
            "credit": "Credito",
            "party_document_number": "Documento",
        },
    )
    journal_response = _import(
        client,
        operator,
        source_id,
        journal_profile,
        "asientos.csv",
        (
            b"Referencia,Fecha,Descripcion,Cuenta,Debito,Credito,Documento\n"
            b"AS-001,2026-08-10,Registro factura,1305,238,0,900123456\n"
            b"AS-001,2026-08-10,Registro factura,4135,0,238,\n"
        ),
    )
    assert journal_response.status_code == 200
    assert journal_response.json()["accepted_rows"] == 2

    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(TaxRecord).where(TaxRecord.company_id == company_id)) == 1
        assert db.scalar(select(func.count()).select_from(ItemRecord).where(ItemRecord.company_id == company_id)) == 1
        assert db.scalar(select(func.count()).select_from(InvoiceRecord).where(InvoiceRecord.company_id == company_id)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentRecord).where(PaymentRecord.company_id == company_id)) == 1
        assert db.scalar(select(func.count()).select_from(JournalEntryRecord).where(JournalEntryRecord.company_id == company_id)) == 1
        assert db.scalar(select(ImportBatchRecord).where(ImportBatchRecord.id == journal_response.json()["batch_id"])) is not None
    finally:
        db.close()


def test_xlsx_import_uses_the_same_accounting_profile(client):
    suffix = uuid4().hex
    owner = _create_user(f"xlsx-owner-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant xlsx {suffix}", "company_name": "Empresa xlsx"},
    )
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    source_id = _source(client, owner, tenant_id, company_id, "xlsx_import", ["taxes", "file_import_export"])
    profile_id = _profile(
        client,
        owner,
        source_id,
        "taxes",
        "xlsx",
        {"code": "Codigo", "name": "Nombre", "rate": "Tarifa"},
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Codigo", "Nombre", "Tarifa"])
    sheet.append(["RET10", "Retención", 10])
    content = BytesIO()
    workbook.save(content)

    response = _import(client, owner, source_id, profile_id, "impuestos.xlsx", content.getvalue())
    assert response.status_code == 200
    assert response.json()["entity"] == "taxes"
    assert response.json()["accepted_rows"] == 1
