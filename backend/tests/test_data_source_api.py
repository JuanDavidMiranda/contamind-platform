from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.data_source import ImportBatchRecord, PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _admin_token() -> str:
    db = SessionLocal()
    try:
        email = "data-sources-admin@test.local"
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name="Data Sources Admin",
                password_hash=hash_password("password123"),
                is_platform_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return create_access_token(user)
    finally:
        db.close()


def test_admin_can_configure_and_import_csv_parties(client):
    token = _admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    onboarding_response = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant API", "company_name": "Empresa API"},
    )
    assert onboarding_response.status_code == 201
    tenant_id = onboarding_response.json()["tenant"]["id"]
    company_id = onboarding_response.json()["company"]["id"]
    source_response = client.post(
        "/api/v1/admin/data-sources",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "csv_import",
            "display_name": "Carga inicial",
            "kind": "file_import",
            "mode": "file_upload",
            "capabilities": ["parties", "file_import_export"],
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    profile_response = client.post(
        f"/api/v1/admin/data-sources/{source_id}/profiles",
        headers=headers,
        json={
            "entity": "parties",
            "file_format": "csv",
            "column_mapping": {"name": "Nombre", "document_number": "Documento"},
        },
    )
    assert profile_response.status_code == 201

    response = client.post(
        f"/api/v1/admin/data-sources/{source_id}/imports/parties",
        headers=headers,
        data={"profile_id": profile_response.json()["id"]},
        files={"file": ("terceros.csv", b"Nombre,Documento\nCliente API,900123456\n", "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["parties"][0]["name"] == "Cliente API"
    assert body["rejections"] == []

    db = SessionLocal()
    try:
        party = db.scalar(select(PartyRecord).where(PartyRecord.company_id == company_id))
        batch = db.scalar(select(ImportBatchRecord).where(ImportBatchRecord.id == body["batch_id"]))
        assert party is not None
        assert party.name == "Cliente API"
        assert batch is not None
        assert batch.content_sha256
    finally:
        db.close()


def test_data_source_endpoints_require_an_admin(client):
    response = client.get(f"/api/v1/admin/data-sources?company_id={uuid4()}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING_TOKEN"


def test_standard_beta_csv_contract_imports_parties_invoices_and_payments(client):
    token = _admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Tenant carga beta", "company_name": "Empresa carga beta"},
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
            "connector_id": "csv_import",
            "display_name": "Carga inicial CSV",
            "kind": "file_import",
            "mode": "file_upload",
            "capabilities": ["parties", "invoices", "payments", "file_import_export"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]

    party_profile = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=headers,
        json={
            "entity": "parties",
            "file_format": "csv",
            "default_party_type": "both",
            "column_mapping": {
                "name": "Nombre",
                "document_type": "Tipo documento",
                "document_number": "Documento",
            },
        },
    )
    assert party_profile.status_code == 201
    parties = client.post(
        f"/api/v1/data-sources/{source_id}/imports/parties",
        headers=headers,
        data={"profile_id": party_profile.json()["id"]},
        files={
            "file": (
                "terceros.csv",
                (
                    "Nombre,Tipo documento,Documento\n"
                    "Cliente de ejemplo,31,900123456\n"
                    "Proveedor de ejemplo,31,901654321\n"
                ),
                "text/csv",
            )
        },
    )
    assert parties.status_code == 200
    assert len(parties.json()["parties"]) == 2

    invoice_profile = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=headers,
        json={
            "entity": "invoices",
            "file_format": "csv",
            "column_mapping": {
                "number": "Numero",
                "invoice_type": "Tipo",
                "issue_date": "Fecha emision",
                "due_date": "Fecha vencimiento",
                "description": "Descripcion",
                "quantity": "Cantidad",
                "unit_price": "Precio unitario",
                "currency_code": "Moneda",
                "tax_total": "Total impuestos",
                "issuer_document_number": "Documento emisor",
                "recipient_document_number": "Documento receptor",
            },
        },
    )
    assert invoice_profile.status_code == 201
    invoices = client.post(
        f"/api/v1/data-sources/{source_id}/imports/accounting",
        headers=headers,
        data={"profile_id": invoice_profile.json()["id"]},
        files={
            "file": (
                "facturas.csv",
                (
                    "Numero,Tipo,Fecha emision,Fecha vencimiento,Descripcion,Cantidad,Precio unitario,Moneda,Total impuestos,Documento emisor,Documento receptor\n"
                    "FV-100,sale,2026-08-01,2026-08-31,Servicio de ejemplo,1,100000,COP,19000,,900123456\n"
                    "FC-200,purchase,2026-08-02,2026-08-20,Compra de ejemplo,1,50000,COP,0,901654321,\n"
                ),
                "text/csv",
            )
        },
    )
    assert invoices.status_code == 200
    assert invoices.json()["accepted_rows"] == 2
    assert invoices.json()["rejections"] == []

    repeated_invoice = client.post(
        f"/api/v1/data-sources/{source_id}/imports/accounting",
        headers=headers,
        data={"profile_id": invoice_profile.json()["id"]},
        files={
            "file": (
                "facturas-corregidas.csv",
                (
                    "Numero,Tipo,Fecha emision,Fecha vencimiento,Descripcion,Cantidad,Precio unitario,Moneda,Total impuestos,Documento emisor,Documento receptor\n"
                    "FV-100,sale,2026-08-01,2026-08-31,Servicio corregido,1,120000,COP,22800,,900123456\n"
                ),
                "text/csv",
            )
        },
    )
    assert repeated_invoice.status_code == 200
    assert repeated_invoice.json()["accepted_rows"] == 0
    assert repeated_invoice.json()["rejections"][0]["row_number"] == 2

    payment_profile = client.post(
        f"/api/v1/data-sources/{source_id}/profiles",
        headers=headers,
        json={
            "entity": "payments",
            "file_format": "csv",
            "column_mapping": {
                "payment_date": "Fecha pago",
                "amount": "Valor",
                "currency_code": "Moneda",
                "invoice_number": "Factura",
                "invoice_type": "Tipo factura",
                "payment_reference": "Referencia de pago",
                "payment_method": "Medio de pago",
            },
        },
    )
    assert payment_profile.status_code == 201
    payments = client.post(
        f"/api/v1/data-sources/{source_id}/imports/accounting",
        headers=headers,
        data={"profile_id": payment_profile.json()["id"]},
        files={
            "file": (
                "pagos.csv",
                "Fecha pago,Valor,Moneda,Factura,Tipo factura,Referencia de pago,Medio de pago\n2026-08-10,25000,COP,FV-100,sale,TRX-100,Transferencia\n",
                "text/csv",
            )
        },
    )
    assert payments.status_code == 200
    assert payments.json()["accepted_rows"] == 1

    repeated_payment = client.post(
        f"/api/v1/data-sources/{source_id}/imports/accounting",
        headers=headers,
        data={"profile_id": payment_profile.json()["id"]},
        files={
            "file": (
                "pagos-corregidos.csv",
                "Fecha pago,Valor,Moneda,Factura,Tipo factura,Referencia de pago,Medio de pago\n2026-08-10,26000,COP,FV-100,sale,TRX-100,Transferencia\n",
                "text/csv",
            )
        },
    )
    assert repeated_payment.status_code == 200
    assert repeated_payment.json()["accepted_rows"] == 0
    assert repeated_payment.json()["rejections"][0]["row_number"] == 2

    db = SessionLocal()
    try:
        assert db.scalar(select(PartyRecord).where(PartyRecord.company_id == company_id)) is not None
        records = list(db.scalars(select(InvoiceRecord).where(InvoiceRecord.company_id == company_id)))
        by_number = {record.number: record for record in records}
        assert len(records) == 2
        assert by_number["FV-100"].recipient_party_id is not None
        assert by_number["FV-100"].issuer_party_id is None
        assert by_number["FC-200"].issuer_party_id is not None
        assert by_number["FC-200"].recipient_party_id is None
        assert db.scalar(select(PaymentRecord).where(PaymentRecord.company_id == company_id)) is not None
    finally:
        db.close()
