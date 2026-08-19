"""Operación controlada del piloto GetAcquirer DIAN."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.dian import DianAcquirerLookupRecord
from app.services.company_service import CompanyService
from app.services.dian_acquirer_service import DianAcquirerService
from app.shared.company_access import OPERATE_SOURCES_ROLES, VIEW_COMPANY_ROLES, require_company_role
from app.shared.security import get_current_user

router = APIRouter(prefix="/companies/{company_id}/dian", tags=["DIAN"])

_DOCUMENT_TYPE_PATTERN = r"^(11|12|13|21|22|31|41|42|47|48|50|91)$"
_DOCUMENT_NUMBER_PATTERN = r"^[A-Za-z0-9-]{1,50}$"


class DianAcquirerLookupRequest(BaseModel):
    data_source_id: UUID
    document_type: str = Field(pattern=_DOCUMENT_TYPE_PATTERN)
    document_number: str = Field(pattern=_DOCUMENT_NUMBER_PATTERN)
    purpose: Literal["electronic_invoice_issuance"]
    confirmed: Literal[True]


class DianAcquirerLookupResponse(BaseModel):
    lookup_id: UUID
    name: str
    email: str | None = None
    purpose: Literal["electronic_invoice_issuance"] = "electronic_invoice_issuance"


class DianAcquirerLookupAuditEntry(BaseModel):
    id: UUID
    data_source_id: UUID
    document_type: str
    status: Literal["succeeded", "failed"]
    error_code: str | None = None
    correlation_id: str | None = None
    requested_at: datetime


class DianAcquirerLookupAuditResponse(BaseModel):
    total: int
    items: list[DianAcquirerLookupAuditEntry]


@router.post("/acquirers/lookup", response_model=DianAcquirerLookupResponse)
async def lookup_acquirer(
    company_id: UUID,
    payload: DianAcquirerLookupRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Completa datos para una FEV/DEE; no admite lotes ni conserva la respuesta."""

    user = get_current_user(authorization, db)
    companies = CompanyService(db)
    companies.get_company(company_id)
    companies.require_active_company(company_id)
    require_company_role(user, db, company_id, OPERATE_SOURCES_ROLES)
    result = await DianAcquirerService(db).lookup(
        company_id=company_id,
        data_source_id=payload.data_source_id,
        actor_user_id=user.id,
        document_type=payload.document_type,
        document_number=payload.document_number,
        correlation_id=(x_request_id or "")[:64] or None,
    )
    return DianAcquirerLookupResponse(
        lookup_id=result.id,
        name=result.name,
        email=result.email,
    )


@router.get("/acquirers/lookups", response_model=DianAcquirerLookupAuditResponse)
def list_acquirer_lookups(
    company_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Expone trazabilidad operativa, nunca el documento ni los datos retornados."""

    user = get_current_user(authorization, db)
    companies = CompanyService(db)
    companies.get_company(company_id)
    require_company_role(user, db, company_id, VIEW_COMPANY_ROLES)
    statement = (
        select(DianAcquirerLookupRecord)
        .where(DianAcquirerLookupRecord.company_id == str(company_id))
        .order_by(DianAcquirerLookupRecord.requested_at.desc(), DianAcquirerLookupRecord.id.desc())
        .offset(offset)
        .limit(limit)
    )
    records = list(db.scalars(statement))
    total = db.scalar(
        select(func.count()).select_from(DianAcquirerLookupRecord).where(
            DianAcquirerLookupRecord.company_id == str(company_id)
        )
    )
    return DianAcquirerLookupAuditResponse(
        total=int(total or 0),
        items=[
            DianAcquirerLookupAuditEntry(
                id=UUID(record.id),
                data_source_id=UUID(record.data_source_id),
                document_type=record.document_type,
                status=record.status,
                error_code=record.error_code,
                correlation_id=record.correlation_id,
                requested_at=record.requested_at,
            )
            for record in records
        ],
    )
