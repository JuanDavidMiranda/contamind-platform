"""Modelo contable canónico v1, independiente de cualquier proveedor."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

CANONICAL_VERSION = "1.0.0"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderKind(str, Enum):
    SIIGO = "siigo"
    ALEGRA = "alegra"
    WORLD_OFFICE_CLOUD = "worldoffice_cloud"
    DIAN = "dian"


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


class Company(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=255)
    functional_currency: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    provider_company_id: str | None = Field(default=None, max_length=255)


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
    provider: ProviderKind
    canonical_version: str = CANONICAL_VERSION
    correlation_id: str | None = Field(default=None, max_length=64)


class PageRequest(CanonicalModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


ModelT = TypeVar("ModelT", bound=CanonicalModel)


class Page(CanonicalModel, Generic[ModelT]):
    items: tuple[ModelT, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int | None = Field(default=None, ge=0)
