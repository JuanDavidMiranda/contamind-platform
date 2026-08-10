"""Modelo contable canónico v1, independiente de cualquier proveedor."""

from datetime import date
from decimal import Decimal
from enum import Enum
import re
from typing import Annotated, Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

CANONICAL_VERSION = "1.0.0"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderKind(str, Enum):
    SIIGO = "siigo"
    ALEGRA = "alegra"
    WORLD_OFFICE_CLOUD = "worldoffice_cloud"
    DIAN = "dian"
    NOVASOFT = "novasoft"
    SYSCAFE = "syscafe"


_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ProviderId = Annotated[str, Field(pattern=_PROVIDER_ID_PATTERN.pattern)]


def normalize_provider_id(provider: str | ProviderKind) -> str:
    value = provider.value if isinstance(provider, ProviderKind) else str(provider)
    normalized = value.strip().lower()
    if not _PROVIDER_ID_PATTERN.fullmatch(normalized):
        raise ValueError("El identificador del proveedor debe usar minúsculas, números y guiones bajos.")
    return normalized


class IntegrationMode(str, Enum):
    CLOUD_API = "cloud_api"
    FILE_EXCHANGE = "file_exchange"
    LOCAL_AGENT = "local_agent"
    DATABASE_CONNECTOR = "database_connector"
    VENDOR_MANAGED = "vendor_managed"


class ProviderCapability(str, Enum):
    PARTIES = "parties"
    INVOICES = "invoices"
    PAYMENTS = "payments"
    JOURNALS = "journals"
    PAYROLL = "payroll"
    FILE_IMPORT_EXPORT = "file_import_export"


class PartyType(str, Enum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    BOTH = "both"


class ItemType(str, Enum):
    PRODUCT = "product"
    SERVICE = "service"


class InvoiceType(str, Enum):
    SALE = "sale"
    PURCHASE = "purchase"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    SUPPORT_DOCUMENT = "support_document"


class Tenant(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(default="CO", pattern=r"^[A-Z]{2}$")


class CompanyStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Company(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=255)
    functional_currency: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    provider_company_id: str | None = Field(default=None, max_length=255)
    status: CompanyStatus = CompanyStatus.ACTIVE


class ProviderDescriptor(CanonicalModel):
    """Metadatos declarativos de un proveedor, sin acoplar el dominio a su marca."""

    provider_id: ProviderId
    display_name: str = Field(min_length=1, max_length=255)
    mode: IntegrationMode
    capabilities: frozenset[ProviderCapability] = frozenset()

    @field_validator("provider_id", mode="before")
    @classmethod
    def normalize_id(cls, value: str | ProviderKind) -> str:
        return normalize_provider_id(value)


class Party(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    party_type: PartyType
    name: str = Field(min_length=1, max_length=255)
    document_type: str | None = Field(default=None, max_length=10)
    document_number: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    fiscal_responsibility: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=255)
    integration_id: str | None = Field(default=None, max_length=512)


class Tax(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    rate: Decimal = Field(ge=0, le=100)
    external_id: str | None = Field(default=None, max_length=255)


class Item(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    item_type: ItemType
    unit: str | None = Field(default=None, max_length=50)
    unit_price: Decimal = Field(ge=0)
    tax_ids: tuple[UUID, ...] = ()
    ledger_account: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=255)


class Currency(CanonicalModel):
    code: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    exchange_rate: Decimal = Field(default=Decimal("1"), gt=0)
    as_of: date | None = None


class InvoiceLine(CanonicalModel):
    item_id: UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_ids: tuple[UUID, ...] = ()
    withholding_ids: tuple[UUID, ...] = ()


class Invoice(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    invoice_type: InvoiceType
    issue_date: date
    issuer_party_id: UUID | None = None
    recipient_party_id: UUID | None = None
    lines: tuple[InvoiceLine, ...] = Field(min_length=1)
    currency: Currency = Field(default_factory=Currency)
    subtotal: Decimal = Field(ge=0)
    tax_total: Decimal = Field(default=Decimal("0"), ge=0)
    withholding_total: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(ge=0)
    number: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=50)
    dian_reference: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)


class Payment(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    payment_date: date
    amount: Decimal = Field(gt=0)
    currency: Currency = Field(default_factory=Currency)
    invoice_id: UUID | None = None
    payment_method: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=255)


class JournalEntryLine(CanonicalModel):
    account_code: str = Field(min_length=1, max_length=100)
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    party_id: UUID | None = None
    cost_center: str | None = Field(default=None, max_length=100)


class JournalEntry(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    entry_date: date
    description: str = Field(min_length=1, max_length=500)
    lines: tuple[JournalEntryLine, ...] = Field(min_length=2)
    source_reference: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)


class ProviderContext(CanonicalModel):
    tenant_id: UUID
    company_id: UUID
    provider: ProviderId
    data_source_id: UUID | None = None
    canonical_version: str = CANONICAL_VERSION
    correlation_id: str | None = Field(default=None, max_length=64)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_id(cls, value: str | ProviderKind) -> str:
        return normalize_provider_id(value)


class PageRequest(CanonicalModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


ModelT = TypeVar("ModelT", bound=CanonicalModel)


class Page(CanonicalModel, Generic[ModelT]):
    items: tuple[ModelT, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int | None = Field(default=None, ge=0)


class PartySyncPage(CanonicalModel):
    """Página de terceros y cursor opaco para sincronizaciones incrementales."""

    items: tuple[Party, ...]
    next_cursor: str | None = Field(default=None, max_length=512)
