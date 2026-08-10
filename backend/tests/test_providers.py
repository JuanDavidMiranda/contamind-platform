from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.providers.canonical import (
    CANONICAL_VERSION,
    Company,
    Currency,
    Invoice,
    InvoiceLine,
    InvoiceType,
    Page,
    PageRequest,
    Party,
    PartyType,
    ProviderDescriptor,
    ProviderCapability,
    ProviderContext,
    ProviderKind,
    IntegrationMode,
)
from app.providers.factory import ProviderFactory
from app.providers.ports import FinancialProviderPort, FiscalProviderPort
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


class _FinancialStub(FinancialProviderPort):
    provider = ProviderKind.SIIGO
    canonical_version = CANONICAL_VERSION

    async def get_party(self, context, external_id):
        return Party(company_id=context.company_id, party_type=PartyType.CUSTOMER, name="Demo")

    async def list_parties(self, context, page):
        return Page(items=(), page=page.page, page_size=page.page_size, total=0)

    async def create_invoice(self, context, invoice, *, idempotency_key=None):
        return invoice

    async def list_journal_entries(self, context, page):
        return Page(items=(), page=page.page, page_size=page.page_size, total=0)


class _FiscalStub(FiscalProviderPort):
    provider = ProviderKind.DIAN
    canonical_version = CANONICAL_VERSION

    async def get_acquirer_information(self, context, document_type, document_number):
        return Party(company_id=context.company_id, party_type=PartyType.CUSTOMER, name="Demo")


def _context(provider=ProviderKind.SIIGO, version=CANONICAL_VERSION):
    return ProviderContext(
        tenant_id=uuid4(),
        company_id=uuid4(),
        provider=provider,
        canonical_version=version,
    )


def test_canonical_entities_keep_internal_and_external_ids_separate():
    company = Company(tenant_id=uuid4(), name="ContaMind SAS")
    party = Party(
        company_id=company.id,
        party_type=PartyType.CUSTOMER,
        name="Cliente Demo",
        external_id="siigo-123",
        integration_id=f"{company.id}:siigo:siigo-123",
    )

    assert party.id != party.external_id
    assert party.integration_id.endswith(":siigo:siigo-123")


def test_invoice_uses_canonical_currency_and_lines():
    invoice = Invoice(
        company_id=uuid4(),
        invoice_type=InvoiceType.SALE,
        issue_date=date(2026, 8, 10),
        lines=(InvoiceLine(description="Servicio", quantity=Decimal("1"), unit_price=Decimal("100")),),
        currency=Currency(),
        subtotal=Decimal("100"),
        total=Decimal("100"),
    )

    assert invoice.currency.code == "COP"
    assert invoice.lines[0].description == "Servicio"


def test_page_request_bounds_are_validated():
    with pytest.raises(ValueError):
        PageRequest(page=0)


def test_factory_resolves_enabled_financial_provider():
    factory = ProviderFactory(feature_checker=lambda provider: provider == ProviderKind.SIIGO)
    adapter = _FinancialStub()
    factory.register(adapter)

    assert factory.resolve_financial(_context()) is adapter


def test_factory_rejects_disabled_provider():
    factory = ProviderFactory(feature_checker=lambda provider: False)
    factory.register(_FinancialStub())

    with pytest.raises(AppError, match="deshabilitada") as error:
        factory.resolve_financial(_context())
    assert error.value.code == "DEPENDENCY_DISABLED"


def test_factory_rejects_wrong_port_type():
    factory = ProviderFactory(feature_checker=lambda provider: True)
    factory.register(_FiscalStub())

    with pytest.raises(AppError) as error:
        factory.resolve_financial(_context(ProviderKind.DIAN))
    assert error.value.code == "CONFLICT"


def test_factory_rejects_incompatible_canonical_major_version():
    adapter = _FinancialStub()
    adapter.canonical_version = "2.0.0"
    factory = ProviderFactory(feature_checker=lambda provider: True)
    factory.register(adapter)

    with pytest.raises(AppError) as error:
        factory.resolve_financial(_context(version="1.1.0"))
    assert error.value.code == "CONFLICT"


def test_provider_descriptor_accepts_configurable_provider_id():
    descriptor = ProviderDescriptor(
        provider_id="Acme_Erp",
        display_name="Acme ERP",
        mode=IntegrationMode.CLOUD_API,
        capabilities={ProviderCapability.PARTIES, ProviderCapability.INVOICES},
    )

    assert descriptor.provider_id == "acme_erp"


def test_factory_resolves_provider_outside_known_catalog():
    adapter = _FinancialStub()
    adapter.provider = "acme_erp"
    factory = ProviderFactory()
    factory.register(adapter)
    context = _context()
    context = context.model_copy(update={"provider": "acme_erp"})

    assert factory.resolve_financial(context) is adapter
