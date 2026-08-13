"""Vista operativa de cuentas por pagar, aislada de cartera y del chat."""

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
from app.services.payables_operations_service import OpenPayableItem, PayablesOperationsService
from app.shared.company_access import OPERATE_SOURCES_ROLES, VIEW_COMPANY_ROLES, require_company_role
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Payables"])


class OpenPayableItemResponse(BaseModel):
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
    mismatched_payment_count: int = Field(ge=0)

    @classmethod
    def from_item(cls, item: OpenPayableItem) -> "OpenPayableItemResponse":
        return cls(
            invoice_id=item.invoice_id,
            invoice_number=item.invoice_number,
            issue_date=item.issue_date,
            due_date=item.due_date,
            payment_terms_days=item.payment_terms_days,
            currency_code=item.currency_code,
            total_amount=item.total_amount,
            paid_amount=item.paid_amount,
            outstanding_amount=item.outstanding_amount,
            days_overdue=item.days_overdue,
            aging_bucket=item.aging_bucket,
            mismatched_payment_count=item.mismatched_payment_count,
        )


class OpenPayablesResponse(BaseModel):
    as_of: date
    total: int = Field(ge=0)
    can_manage: bool
    items: list[OpenPayableItemResponse]


class InvoiceTermsUpdate(BaseModel):
    due_date: date | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=3650)
    confirmed: Literal[True]


class InvoiceTermsResponse(BaseModel):
    invoice_id: UUID
    due_date: date | None
    payment_terms_days: int | None
    updated_by_user_id: int | None
    updated_at: datetime

    @classmethod
    def from_record(cls, record: InvoiceRecord) -> "InvoiceTermsResponse":
        return cls(
            invoice_id=UUID(record.id), due_date=record.due_date,
            payment_terms_days=record.payment_terms_days,
            updated_by_user_id=record.updated_by_user_id, updated_at=record.updated_at,
        )


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.get("/{company_id}/payables/open-items", response_model=OpenPayablesResponse)
def list_open_payables(
    company_id: UUID,
    as_of: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    page = PayablesOperationsService(db).open_items(
        company.id, as_of=as_of or date.today(), limit=limit, offset=offset,
    )
    return OpenPayablesResponse(
        as_of=page.as_of,
        total=page.total,
        can_manage=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        items=[OpenPayableItemResponse.from_item(item) for item in page.items],
    )


@router.patch("/{company_id}/payables/invoices/{invoice_id}/terms", response_model=InvoiceTermsResponse)
def update_payable_terms(
    company_id: UUID,
    invoice_id: UUID,
    payload: InvoiceTermsUpdate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, OPERATE_SOURCES_ROLES)
    record = PayablesOperationsService(db).update_terms(
        company.id,
        invoice_id,
        due_date=payload.due_date,
        payment_terms_days=payload.payment_terms_days,
        fields_set=set(payload.model_fields_set),
        actor_user_id=user.id,
    )
    return InvoiceTermsResponse.from_record(record)
