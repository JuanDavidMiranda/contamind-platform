"""API operativa para importar y revisar conciliaciones bancarias."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.database import get_db
from app.models.bank_reconciliation import BankAccountRecord, BankTransactionRecord
from app.models.user import User
from app.services.bank_reconciliation_service import (
    BankImportResult,
    BankReconciliationService,
    BankTransactionItem,
)
from app.services.company_service import CompanyService
from app.shared.company_access import (
    MANAGE_SOURCES_ROLES,
    OPERATE_SOURCES_ROLES,
    VIEW_COMPANY_ROLES,
    require_company_role,
)
from app.shared.errors import app_error
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Bank reconciliation"])


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    bank_name: str | None = Field(default=None, max_length=100)
    currency_code: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    confirmed: Literal[True]


class BankAccountResponse(BaseModel):
    id: UUID
    name: str
    bank_name: str | None
    currency_code: str
    status: Literal["active", "disabled"]
    created_by_user_id: int
    created_at: datetime

    @classmethod
    def from_record(cls, record: BankAccountRecord) -> "BankAccountResponse":
        return cls(
            id=UUID(record.id),
            name=record.name,
            bank_name=record.bank_name,
            currency_code=record.currency_code,
            status=record.status,
            created_by_user_id=record.created_by_user_id,
            created_at=record.created_at,
        )


class BankAccountsResponse(BaseModel):
    can_manage: bool
    can_configure: bool
    accounts: list[BankAccountResponse]


class BankImportRejectionResponse(BaseModel):
    row_number: int = Field(ge=2)
    message: str


class BankImportResponse(BaseModel):
    import_id: UUID
    accepted_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    rejections: list[BankImportRejectionResponse]

    @classmethod
    def from_result(cls, result: BankImportResult) -> "BankImportResponse":
        return cls(
            import_id=result.import_id,
            accepted_rows=result.accepted_rows,
            duplicate_rows=result.duplicate_rows,
            rejections=[
                BankImportRejectionResponse(
                    row_number=rejection.row_number,
                    message=rejection.message,
                )
                for rejection in result.rejections
            ],
        )


class BankTransactionResponse(BaseModel):
    id: UUID
    bank_account_id: UUID
    transaction_date: date
    amount: Decimal
    currency_code: str
    description: str | None
    reference: str | None
    status: Literal["pending", "suggested", "reconciled", "dismissed", "excluded"]
    match_candidate_count: int = Field(ge=0)
    suggested_payment_id: UUID | None
    suggested_payment_date: date | None
    matched_payment_id: UUID | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None

    @classmethod
    def from_item(cls, item: BankTransactionItem) -> "BankTransactionResponse":
        return cls(**item.__dict__)

    @classmethod
    def from_record(cls, record: BankTransactionRecord) -> "BankTransactionResponse":
        return cls(
            id=UUID(record.id),
            bank_account_id=UUID(record.bank_account_id),
            transaction_date=record.transaction_date,
            amount=record.amount,
            currency_code=record.currency_code,
            description=record.description,
            reference=record.reference,
            status=record.status,
            match_candidate_count=record.match_candidate_count,
            suggested_payment_id=(
                UUID(record.suggested_payment_id) if record.suggested_payment_id else None
            ),
            suggested_payment_date=None,
            matched_payment_id=(
                UUID(record.matched_payment_id) if record.matched_payment_id else None
            ),
            reviewed_by_user_id=record.reviewed_by_user_id,
            reviewed_at=record.reviewed_at,
        )


class BankTransactionsResponse(BaseModel):
    total: int = Field(ge=0)
    can_manage: bool
    items: list[BankTransactionResponse]


class BankTransactionReview(BaseModel):
    action: Literal["confirm", "dismiss", "exclude", "reopen"]
    confirmed: Literal[True]


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.get(
    "/{company_id}/bank-reconciliation/accounts",
    response_model=BankAccountsResponse,
)
def list_bank_accounts(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    accounts = BankReconciliationService(db).list_accounts(company.id)
    return BankAccountsResponse(
        can_manage=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        can_configure=user.is_platform_admin or role in MANAGE_SOURCES_ROLES,
        accounts=[BankAccountResponse.from_record(record) for record in accounts],
    )


@router.post(
    "/{company_id}/bank-reconciliation/accounts",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_bank_account(
    company_id: UUID,
    payload: BankAccountCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, MANAGE_SOURCES_ROLES)
    record = BankReconciliationService(db).create_account(
        company.id,
        name=payload.name,
        bank_name=payload.bank_name,
        currency_code=payload.currency_code,
        actor_user_id=user.id,
    )
    return BankAccountResponse.from_record(record)


@router.post(
    "/{company_id}/bank-reconciliation/accounts/{bank_account_id}/imports",
    response_model=BankImportResponse,
)
async def import_bank_statement(
    company_id: UUID,
    bank_account_id: UUID,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, OPERATE_SOURCES_ROLES)
    if Path(file.filename or "").suffix.lower() != ".csv":
        raise app_error(
            "VALIDATION_ERROR", message="La primera versión admite extractos CSV."
        )
    content = await file.read(settings.MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > settings.MAX_IMPORT_FILE_BYTES:
        raise app_error(
            "VALIDATION_ERROR", message="El archivo supera el tamaño máximo permitido."
        )
    result = BankReconciliationService(db).import_csv(
        company.id,
        bank_account_id,
        content,
        actor_user_id=user.id,
    )
    return BankImportResponse.from_result(result)


@router.get(
    "/{company_id}/bank-reconciliation/transactions",
    response_model=BankTransactionsResponse,
)
def list_bank_transactions(
    company_id: UUID,
    bank_account_id: UUID | None = Query(default=None),
    reconciliation_status: Literal[
        "pending", "suggested", "reconciled", "dismissed", "excluded"
    ]
    | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    page = BankReconciliationService(db).list_transactions(
        company.id,
        bank_account_id=bank_account_id,
        status=reconciliation_status,
        limit=limit,
        offset=offset,
    )
    return BankTransactionsResponse(
        total=page.total,
        can_manage=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        items=[BankTransactionResponse.from_item(item) for item in page.items],
    )


@router.patch(
    "/{company_id}/bank-reconciliation/transactions/{transaction_id}",
    response_model=BankTransactionResponse,
)
def review_bank_transaction(
    company_id: UUID,
    transaction_id: UUID,
    payload: BankTransactionReview,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, OPERATE_SOURCES_ROLES)
    record = BankReconciliationService(db).review(
        company.id,
        transaction_id,
        action=payload.action,
        actor_user_id=user.id,
    )
    return BankTransactionResponse.from_record(record)
