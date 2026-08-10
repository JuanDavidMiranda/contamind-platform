"""API de captura manual para entidades del núcleo contable."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.data_sources.models import CompanyDataSource
from app.database.database import get_db
from app.models.user import User
from app.providers.canonical import (
    Currency,
    Invoice,
    InvoiceLine,
    InvoiceType,
    Item,
    ItemType,
    JournalEntry,
    JournalEntryLine,
    Payment,
    Tax,
)
from app.services.company_service import CompanyService
from app.services.data_source_service import DataSourceService
from app.services.manual_accounting_service import ManualAccountingService
from app.shared.company_access import OPERATE_SOURCES_ROLES, require_company_role
from app.shared.errors import app_error
from app.shared.security import get_current_user

router = APIRouter(prefix="/data-sources", tags=["Manual accounting"])


class ManualTaxCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    rate: Decimal = Field(ge=0, le=100)


class ManualItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    item_type: ItemType
    unit: str | None = Field(default=None, max_length=50)
    unit_price: Decimal = Field(ge=0)
    tax_ids: tuple[UUID, ...] = ()
    ledger_account: str | None = Field(default=None, max_length=100)


class ManualInvoiceCreate(BaseModel):
    invoice_type: InvoiceType
    issue_date: date
    issuer_party_id: UUID | None = None
    recipient_party_id: UUID | None = None
    lines: tuple[InvoiceLine, ...] = Field(min_length=1)
    currency: Currency = Field(default_factory=Currency)
    tax_total: Decimal = Field(default=Decimal("0"), ge=0)
    withholding_total: Decimal = Field(default=Decimal("0"), ge=0)
    number: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=50)


class ManualPaymentCreate(BaseModel):
    payment_date: date
    amount: Decimal = Field(gt=0)
    currency: Currency = Field(default_factory=Currency)
    invoice_id: UUID | None = None
    payment_method: str | None = Field(default=None, max_length=100)


class ManualJournalEntryCreate(BaseModel):
    entry_date: date
    description: str = Field(min_length=1, max_length=500)
    lines: tuple[JournalEntryLine, ...] = Field(min_length=2)
    source_reference: str | None = Field(default=None, max_length=255)


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


def _idempotency_key(value: str | None) -> str:
    if value is None:
        raise app_error("VALIDATION_ERROR", message="El encabezado Idempotency-Key es obligatorio.")
    return value


def _manual_source_for_user(data_source_id: UUID, user: User, db: Session) -> CompanyDataSource:
    source = DataSourceService(db).get_source(data_source_id)
    companies = CompanyService(db)
    companies.require_company_in_tenant(source.company_id, source.tenant_id)
    companies.require_active_company(source.company_id)
    require_company_role(user, db, source.company_id, OPERATE_SOURCES_ROLES)
    return source


@router.post("/{data_source_id}/manual/taxes", response_model=Tax, status_code=status.HTTP_201_CREATED)
def create_tax(
    data_source_id: UUID,
    payload: ManualTaxCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _manual_source_for_user(data_source_id, user, db)
    return ManualAccountingService(db).create_tax(
        data_source_id,
        **payload.model_dump(),
        actor_user_id=user.id,
        idempotency_key=_idempotency_key(idempotency_key),
    )


@router.post("/{data_source_id}/manual/items", response_model=Item, status_code=status.HTTP_201_CREATED)
def create_item(
    data_source_id: UUID,
    payload: ManualItemCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _manual_source_for_user(data_source_id, user, db)
    return ManualAccountingService(db).create_item(
        data_source_id,
        **payload.model_dump(),
        actor_user_id=user.id,
        idempotency_key=_idempotency_key(idempotency_key),
    )


@router.post("/{data_source_id}/manual/invoices", response_model=Invoice, status_code=status.HTTP_201_CREATED)
def create_invoice(
    data_source_id: UUID,
    payload: ManualInvoiceCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _manual_source_for_user(data_source_id, user, db)
    values = payload.model_dump(exclude={"lines", "currency"})
    return ManualAccountingService(db).create_invoice(
        data_source_id,
        **values,
        lines=payload.lines,
        currency=payload.currency,
        actor_user_id=user.id,
        idempotency_key=_idempotency_key(idempotency_key),
    )


@router.post("/{data_source_id}/manual/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(
    data_source_id: UUID,
    payload: ManualPaymentCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _manual_source_for_user(data_source_id, user, db)
    values = payload.model_dump(exclude={"currency"})
    return ManualAccountingService(db).create_payment(
        data_source_id,
        **values,
        currency=payload.currency,
        actor_user_id=user.id,
        idempotency_key=_idempotency_key(idempotency_key),
    )


@router.post("/{data_source_id}/manual/journal-entries", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    data_source_id: UUID,
    payload: ManualJournalEntryCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _manual_source_for_user(data_source_id, user, db)
    values = payload.model_dump(exclude={"lines"})
    return ManualAccountingService(db).create_journal_entry(
        data_source_id,
        **values,
        lines=payload.lines,
        actor_user_id=user.id,
        idempotency_key=_idempotency_key(idempotency_key),
    )
