"""Operación protegida de evidencias para facturación electrónica."""

from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.database import get_db
from app.models.user import User
from app.services.company_service import CompanyService
from app.services.electronic_invoice_evidence_import_service import (
    ElectronicInvoiceEvidenceImportItem,
    ElectronicInvoiceEvidenceImportResult,
    ElectronicInvoiceEvidenceImportRowItem,
    ElectronicInvoiceEvidenceImportService,
    ElectronicInvoiceExceptionsPage,
)
from app.shared.company_access import OPERATE_SOURCES_ROLES, VIEW_COMPANY_ROLES, require_company_role
from app.shared.errors import app_error
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Electronic invoicing"])


class ElectronicInvoiceEvidenceRejectionResponse(BaseModel):
    row_number: int = Field(ge=2)
    message: str


class ElectronicInvoiceEvidenceImportResponse(BaseModel):
    import_id: UUID
    accepted_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    rejections: list[ElectronicInvoiceEvidenceRejectionResponse]

    @classmethod
    def from_result(
        cls, result: ElectronicInvoiceEvidenceImportResult
    ) -> "ElectronicInvoiceEvidenceImportResponse":
        return cls(
            import_id=result.import_id,
            accepted_rows=result.accepted_rows,
            duplicate_rows=result.duplicate_rows,
            rejections=[
                ElectronicInvoiceEvidenceRejectionResponse(
                    row_number=rejection.row_number,
                    message=rejection.message,
                )
                for rejection in result.rejections
            ],
        )


class ElectronicInvoiceEvidenceImportItemResponse(BaseModel):
    id: UUID
    file_format: Literal["csv", "xlsx"]
    accepted_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    created_at: datetime

    @classmethod
    def from_item(
        cls, item: ElectronicInvoiceEvidenceImportItem
    ) -> "ElectronicInvoiceEvidenceImportItemResponse":
        return cls(**item.__dict__)


class ElectronicInvoiceEvidenceImportsResponse(BaseModel):
    total: int = Field(ge=0)
    can_import: bool
    items: list[ElectronicInvoiceEvidenceImportItemResponse]


class ElectronicInvoiceEvidenceImportRowResponse(BaseModel):
    row_number: int = Field(ge=2)
    outcome: Literal["accepted", "duplicate", "rejected"]
    reason: str | None
    created_at: datetime

    @classmethod
    def from_item(
        cls, item: ElectronicInvoiceEvidenceImportRowItem
    ) -> "ElectronicInvoiceEvidenceImportRowResponse":
        return cls(**item.__dict__)


class ElectronicInvoiceEvidenceImportRowsResponse(BaseModel):
    total: int = Field(ge=0)
    items: list[ElectronicInvoiceEvidenceImportRowResponse]


class ElectronicInvoiceExceptionResponse(BaseModel):
    invoice_id: UUID
    invoice_number: str | None
    issue_date: date
    electronic_status: str | None
    electronic_status_at: datetime | None
    has_electronic_reference: bool
    issue_codes: list[str]


class ElectronicInvoiceExceptionsResponse(BaseModel):
    total: int = Field(ge=0)
    can_import: bool
    items: list[ElectronicInvoiceExceptionResponse]


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.post(
    "/{company_id}/electronic-invoicing/imports",
    response_model=ElectronicInvoiceEvidenceImportResponse,
)
async def import_electronic_invoice_evidence(
    company_id: UUID,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).require_active_company(company_id)
    require_company_role(user, db, company.id, OPERATE_SOURCES_ROLES)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise app_error("VALIDATION_ERROR", message="Carga un archivo CSV o XLSX.")
    content = await file.read(settings.MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > settings.MAX_IMPORT_FILE_BYTES:
        raise app_error("VALIDATION_ERROR", message="El archivo supera el tamaño máximo permitido.")
    result = ElectronicInvoiceEvidenceImportService(db).import_content(
        company.id,
        content,
        uploaded_format=suffix.removeprefix("."),
        actor_user_id=user.id,
    )
    return ElectronicInvoiceEvidenceImportResponse.from_result(result)


@router.get(
    "/{company_id}/electronic-invoicing/imports",
    response_model=ElectronicInvoiceEvidenceImportsResponse,
)
def list_electronic_invoice_imports(
    company_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    total, items = ElectronicInvoiceEvidenceImportService(db).list_imports(
        company.id, limit=limit, offset=offset
    )
    return ElectronicInvoiceEvidenceImportsResponse(
        total=total,
        can_import=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        items=[ElectronicInvoiceEvidenceImportItemResponse.from_item(item) for item in items],
    )


@router.get(
    "/{company_id}/electronic-invoicing/imports/{import_id}/rows",
    response_model=ElectronicInvoiceEvidenceImportRowsResponse,
)
def list_electronic_invoice_import_rows(
    company_id: UUID,
    import_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    total, items = ElectronicInvoiceEvidenceImportService(db).list_import_rows(
        company.id, import_id, limit=limit, offset=offset
    )
    return ElectronicInvoiceEvidenceImportRowsResponse(
        total=total,
        items=[ElectronicInvoiceEvidenceImportRowResponse.from_item(item) for item in items],
    )


@router.get(
    "/{company_id}/electronic-invoicing/exceptions",
    response_model=ElectronicInvoiceExceptionsResponse,
)
def list_electronic_invoice_exceptions(
    company_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    role = require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    page: ElectronicInvoiceExceptionsPage = ElectronicInvoiceEvidenceImportService(db).exceptions(
        company.id, limit=limit, offset=offset
    )
    return ElectronicInvoiceExceptionsResponse(
        total=page.total,
        can_import=user.is_platform_admin or role in OPERATE_SOURCES_ROLES,
        items=[
            ElectronicInvoiceExceptionResponse(
                invoice_id=item.invoice_id,
                invoice_number=item.invoice_number,
                issue_date=item.issue_date,
                electronic_status=item.electronic_status,
                electronic_status_at=item.electronic_status_at,
                has_electronic_reference=item.has_electronic_reference,
                issue_codes=list(item.issue_codes),
            )
            for item in page.items
        ],
    )
