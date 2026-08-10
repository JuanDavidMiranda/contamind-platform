from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest

from app.providers.canonical import (
    Invoice,
    InvoiceLine,
    InvoiceType,
    PageRequest,
    Party,
    PartyType,
    ProviderContext,
    ProviderKind,
)
from app.providers.mock_financial import MockFinancialProvider
from app.providers.secrets import InMemorySecretStore, ProviderSecret
from app.providers.transport import ProviderHttpClient
from app.shared.errors import AppError

pytestmark = pytest.mark.unit


def _context(*, tenant_id: UUID | None = None, company_id: UUID | None = None) -> ProviderContext:
    return ProviderContext(
        tenant_id=tenant_id or uuid4(),
        company_id=company_id or uuid4(),
        provider=ProviderKind.SIIGO,
        correlation_id="compliance-trace-1",
    )


def _party(context: ProviderContext, external_id: str, name: str = "Cliente Demo") -> Party:
    return Party(
        company_id=context.company_id,
        party_type=PartyType.CUSTOMER,
        name=name,
        document_type="31",
        document_number="900123456",
        email="contacto@ejemplo.co",
        city="Bogotá",
        external_id=external_id,
    )


def _invoice(context: ProviderContext) -> Invoice:
    return Invoice(
        company_id=context.company_id,
        invoice_type=InvoiceType.SALE,
        issue_date=date(2026, 8, 10),
        lines=(InvoiceLine(description="Servicio", quantity=Decimal("1"), unit_price=Decimal("100")),),
        subtotal=Decimal("100"),
        total=Decimal("100"),
    )


def test_01_autenticar_con_secreto_por_empresa():
    store = InMemorySecretStore()
    context = _context()
    adapter = MockFinancialProvider(secret_store=store)
    store.save(context, ProviderSecret({"token": "test-only"}))

    assert adapter.authenticate(context) == "mock-authenticated-transport"


@pytest.mark.asyncio
async def test_02_consultar_tercero_retorna_party_canonico():
    context = _context()
    adapter = MockFinancialProvider()
    party = _party(context, "customer-1")
    adapter.register_party(context, party)

    assert await adapter.get_party(context, "customer-1") == party


@pytest.mark.asyncio
async def test_03_listar_terceros_retorna_pagina_canonica():
    context = _context()
    adapter = MockFinancialProvider()
    adapter.register_party(context, _party(context, "customer-1"))

    result = await adapter.list_parties(context, PageRequest())

    assert result.total == 1
    assert result.items[0].party_type is PartyType.CUSTOMER


def test_04_mapear_tercero_canonico_no_pierde_campos_nucleo():
    context = _context()
    adapter = MockFinancialProvider()
    source = _party(context, "customer-1")

    restored = adapter.from_provider_party(context, adapter.to_provider_party(source))

    for field in (
        "company_id",
        "party_type",
        "document_type",
        "document_number",
        "name",
        "email",
        "city",
        "external_id",
    ):
        assert getattr(restored, field) == getattr(source, field)


@pytest.mark.asyncio
async def test_05_paginacion_respeta_los_limites_solicitados():
    context = _context()
    adapter = MockFinancialProvider()
    adapter.register_party(context, _party(context, "1"))
    adapter.register_party(context, _party(context, "2"))

    result = await adapter.list_parties(context, PageRequest(page=2, page_size=1))

    assert result.total == 2
    assert [party.external_id for party in result.items] == ["2"]


@pytest.mark.asyncio
async def test_06_rate_limits_reintenta_429_y_normaliza_el_error():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    async def no_sleep(seconds):
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = ProviderHttpClient(client, retries=1, sleep=no_sleep)
        with pytest.raises(AppError) as error:
            await transport.request(_context(), "GET", "https://provider.test/parties")

    assert calls == 2
    assert error.value.code == "PROVIDER_RATE_LIMITED"


def test_07_credencial_invalida_no_expone_el_secreto():
    context = _context()
    adapter = MockFinancialProvider(secret_store=InMemorySecretStore())

    with pytest.raises(AppError) as error:
        adapter.authenticate(context)

    assert error.value.code == "PROVIDER_AUTH_FAILED"
    assert "secret" not in str(error.value.details).lower()


@pytest.mark.asyncio
async def test_08_idempotencia_retorna_la_misma_factura():
    context = _context()
    adapter = MockFinancialProvider()
    invoice = _invoice(context)

    first = await adapter.create_invoice(context, invoice, idempotency_key="request-0001")
    repeated = await adapter.create_invoice(context, _invoice(context), idempotency_key="request-0001")

    assert repeated is first


@pytest.mark.asyncio
async def test_09_auditoria_no_guarda_payload_ni_secretos():
    context = _context()
    adapter = MockFinancialProvider()
    adapter.register_party(context, _party(context, "customer-1"))
    await adapter.get_party(context, "customer-1")

    event = adapter.audit_events[-1]
    assert event.company_id == str(context.company_id)
    assert event.correlation_id == "compliance-trace-1"
    assert set(event.__dict__) == {"company_id", "provider", "operation", "correlation_id"}


@pytest.mark.asyncio
async def test_10_aislar_por_empresa_impide_ver_terceros_ajenos():
    tenant_id = uuid4()
    first = _context(tenant_id=tenant_id)
    second = _context(tenant_id=tenant_id)
    adapter = MockFinancialProvider()
    adapter.register_party(first, _party(first, "customer-1"))

    with pytest.raises(AppError) as error:
        await adapter.get_party(second, "customer-1")

    assert error.value.code == "NOT_FOUND"
