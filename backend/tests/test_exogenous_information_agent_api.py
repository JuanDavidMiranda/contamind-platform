"""Cobertura del diagnóstico y revisión protegida de información exógena."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.agent import AgentExecutionRecord
from app.models.data_source import PartyRecord
from app.models.user import User
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Exogenous information test user",
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
    number: str | None,
    issuer_party_id: str | None,
    recipient_party_id: str | None,
    total: str = "100",
) -> InvoiceRecord:
    return InvoiceRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        invoice_type=invoice_type,
        issue_date=date(2025, 8, 1),
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal=Decimal("100"),
        tax_total=Decimal("0"),
        withholding_total=Decimal("0"),
        total=Decimal(total),
        number=number,
        issuer_party_id=issuer_party_id,
        recipient_party_id=recipient_party_id,
        idempotency_key=uuid4().hex,
        created_by_user_id=owner_id,
    )


def test_exogenous_information_agent_reviews_data_without_claiming_dian_rules(client):
    suffix = uuid4().hex
    owner = _user(f"exogenous-owner-{suffix}@test.local")
    viewer = _user(f"exogenous-viewer-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant exógena {suffix}", "company_name": "Empresa exógena"},
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
            "connector_id": "exogenous_information_test",
            "display_name": "Datos exógena de prueba",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["parties", "invoices", "payments"],
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]
    complete_party = PartyRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        party_type="customer",
        name="Tercero completo",
        document_type="NIT",
        document_number="900123456",
        city="Bogotá",
        address="Dirección de prueba",
        created_by_user_id=owner.id,
        updated_by_user_id=owner.id,
    )
    incomplete_party = PartyRecord(
        id=str(uuid4()),
        company_id=company_id,
        data_source_id=source_id,
        party_type="supplier",
        name="Tercero pendiente",
        created_by_user_id=owner.id,
        updated_by_user_id=owner.id,
    )
    healthy_invoice = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        number="FV-2025-001",
        issuer_party_id=None,
        recipient_party_id=complete_party.id,
    )
    inconsistent_invoice = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="sale",
        number=None,
        issuer_party_id=None,
        recipient_party_id=None,
        total="99",
    )
    purchase_without_supplier = _invoice(
        company_id=company_id,
        source_id=source_id,
        owner_id=owner.id,
        invoice_type="purchase",
        number="FC-2025-001",
        issuer_party_id=None,
        recipient_party_id=None,
    )
    db = SessionLocal()
    try:
        db.add_all([complete_party, incomplete_party, healthy_invoice, inconsistent_invoice, purchase_without_supplier])
        db.add_all([
            PaymentRecord(
                id=str(uuid4()), company_id=company_id, data_source_id=source_id,
                payment_date=date(2025, 8, 2), amount=Decimal("100"), currency_code="COP",
                exchange_rate=Decimal("1"), invoice_id=healthy_invoice.id,
                idempotency_key=uuid4().hex, created_by_user_id=owner.id,
            ),
            PaymentRecord(
                id=str(uuid4()), company_id=company_id, data_source_id=source_id,
                payment_date=date(2025, 8, 3), amount=Decimal("99"), currency_code="COP",
                exchange_rate=Decimal("1"), invoice_id=None,
                idempotency_key=uuid4().hex, created_by_user_id=owner.id,
            ),
        ])
        db.commit()
    finally:
        db.close()

    chat_endpoint = f"/api/v1/companies/{company_id}/agents/exogenous-information/chat"
    diagnostic = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "¿Qué debo revisar primero para información exógena en 2025?"},
    )
    assert diagnostic.status_code == 200
    body = diagnostic.json()
    assert body["agent_id"] == "exogenous_information"
    assert body["workflow"] == "exogenous_information"
    metrics = body["report"]["metrics"]
    assert metrics == {
        "tax_year": 2025,
        "registered_parties": 2,
        "parties_with_complete_identification": 1,
        "parties_missing_document_type": 1,
        "parties_missing_document_number": 1,
        "parties_missing_city": 1,
        "parties_missing_address": 1,
        "party_identification_coverage": "50.00",
        "invoices_in_tax_year": 3,
        "invoices_missing_number": 1,
        "invoices_missing_counterparty": 2,
        "invoices_with_total_mismatch": 1,
        "payments_in_tax_year": 2,
        "payments_without_invoice": 1,
    }
    finding_codes = {item["code"] for item in body["report"]["findings"]}
    assert {
        "EXOGENA_OFFICIAL_RULES_NOT_CONFIGURED",
        "EXOGENA_OFFICIAL_FILES_NOT_GENERATED",
        "EXOGENA_PARTIES_MISSING_IDENTIFICATION",
        "EXOGENA_INVOICES_WITH_TOTAL_MISMATCH",
        "EXOGENA_PAYMENTS_WITHOUT_INVOICE",
    } <= finding_codes

    official_rules = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "¿Qué formatos de exógena exige la DIAN para 2025?"},
    )
    assert official_rules.status_code == 200
    assert official_rules.json()["conversation"]["outcome"] == "answered"
    assert "no determinamos" in official_rules.json()["conversation"]["response"]

    individual = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "Muéstrame el NIT del tercero pendiente"},
    )
    assert individual.status_code == 200
    assert individual.json()["conversation"]["outcome"] == "out_of_scope"

    write = client.post(
        chat_endpoint,
        headers=_headers(owner),
        json={"message": "Genera el archivo de exógena para la DIAN"},
    )
    assert write.status_code == 200
    assert write.json()["conversation"]["outcome"] == "out_of_scope"

    exceptions_endpoint = f"/api/v1/companies/{company_id}/exogenous-information/exceptions?tax_year=2025"
    exceptions = client.get(exceptions_endpoint, headers=_headers(viewer))
    assert exceptions.status_code == 200
    exception_body = exceptions.json()
    assert exception_body["total"] == 4
    assert "name" not in exception_body["items"][0]
    assert "document_number" not in exceptions.text
    assert any(item["record_type"] == "party" for item in exception_body["items"])
    assert any(item["record_type"] == "invoice" for item in exception_body["items"])
    assert any(item["record_type"] == "payment" for item in exception_body["items"])

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord).where(
                    AgentExecutionRecord.company_id == company_id,
                    AgentExecutionRecord.agent_id == "exogenous_information",
                )
            )
        )
        assert len(executions) == 4
        assert all(record.status == "succeeded" for record in executions)
    finally:
        db.close()
