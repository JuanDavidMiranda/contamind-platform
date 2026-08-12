"""Vista operativa de cartera: lectura agregada por factura y ajustes confirmados."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.accounting import InvoiceRecord
from app.models.user import User
from app.services.company_service import CompanyService
from app.services.receivables_operations_service import (
    OpenReceivableItem,
    ReceivablesOperationsService,
)
from app.shared.company_access import (
    OPERATE_SOURCES_ROLES,
    VIEW_COMPANY_ROLES,
    require_company_role,
)
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Receivables"])


class OpenReceivableItemResponse(BaseModel):
    invoice_id: UUID
    invoice_number: str | None
    issue_date: date
    due_date: date | None
    payment_terms_days: int | None
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    total_amount: Decimal = Field(ge=0)
    paid_amount: Decimal = Field(ge=0)
    outstanding_amount: Decimal = Field(gt=0)
    days_overdue: int | None = Field(default=None, ge=0)
    aging_bucket: str
    latest_followup_status: str | None = None
    promised_date: date | None = None
    mismatched_payment_count: int = Field(ge=0)

    @classmethod
    def from_item(cls, item: OpenReceivableItem) -> "OpenReceivableItemResponse":
        return cls(**item.__dict__)


class OpenReceivablesResponse(BaseModel):
    as_of: date
    total: int = Field(ge=0)
    can_manage: bool
    items: list[OpenReceivableItemResponse]


class InvoiceTermsUpdate(BaseModel):
    due_date: date | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=3650)
    confirmed: Literal[True] = Field(
        description="Confirmación explícita del cambio de vencimiento; debe ser true."
    )


class InvoiceTermsResponse(BaseModel):
    invoice_id: UUID
    due_date: date | None
    payment_terms_days: int | None
    updated_by_user_id: int | None
    updated_at: datetime

    @classmethod
    def from_record(cls, record: InvoiceRecord) -> "InvoiceTermsResponse":
        return cls(
            invoice_id=UUID(record.id),
            due_date=record.due_date,
            payment_terms_days=record.payment_terms_days,
            updated_by_user_id=record.updated_by_user_id,
            updated_at=record.updated_at,
        )


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.get("/{company_id}/receivables/open-items", response_model=OpenReceivablesResponse)
def list_open_receivables(
    company_id: UUID,
    as_of: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Lista facturas abiertas autorizadas; las notas quedan en su API de seguimiento."""

    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    page = ReceivablesOperationsService(db).open_items(
        company.id,
        as_of=as_of or date.today(),
        limit=limit,
        offset=offset,
    )
    return OpenReceivablesResponse(
        as_of=page.as_of,
        total=page.total,
        can_manage=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        items=[OpenReceivableItemResponse.from_item(item) for item in page.items],
    )


@router.patch(
    "/{company_id}/receivables/invoices/{invoice_id}/terms",
    response_model=InvoiceTermsResponse,
)
def update_invoice_terms(
    company_id: UUID,
    invoice_id: UUID,
    payload: InvoiceTermsUpdate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Corrige condiciones de una factura de venta sólo tras confirmación humana."""

    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, OPERATE_SOURCES_ROLES)
    record = ReceivablesOperationsService(db).update_terms(
        company.id,
        invoice_id,
        due_date=payload.due_date,
        payment_terms_days=payload.payment_terms_days,
        fields_set=set(payload.model_fields_set),
        actor_user_id=user.id,
    )
    return InvoiceTermsResponse.from_record(record)
