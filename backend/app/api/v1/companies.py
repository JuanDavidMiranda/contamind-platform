"""Onboarding, ciclo de vida y consulta de empresas accesibles."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import CompanyRole, User
from app.providers.canonical import Company, CompanyStatus, Tenant
from app.services.company_audit_service import CompanyAuditService
from app.services.company_service import CompanyService
from app.shared.company_access import (
    VIEW_COMPANY_ROLES,
    require_company_role,
    require_tenant_owner,
)
from app.shared.security import get_current_user

router = APIRouter(prefix="/companies", tags=["Companies"])
tenant_router = APIRouter(prefix="/tenants", tags=["Companies"])


class CompanyOnboardingCreate(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(default="CO", pattern=r"^[A-Z]{2}$")
    company_name: str = Field(min_length=1, max_length=255)
    functional_currency: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    provider_company_id: str | None = Field(default=None, max_length=255)


class CompanyOnboardingResponse(BaseModel):
    tenant: Tenant
    company: Company


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    functional_currency: str = Field(default="COP", pattern=r"^[A-Z]{3}$")
    provider_company_id: str | None = Field(default=None, max_length=255)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    functional_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    provider_company_id: str | None = Field(default=None, max_length=255)


class SourceAuditEntry(BaseModel):
    id: UUID
    display_name: str
    connector_id: str
    created_by_user_id: int | None
    created_at: datetime


class ImportAuditEntry(BaseModel):
    id: UUID
    data_source_id: UUID
    entity: str
    file_format: str
    accepted_rows: int
    rejected_rows: int
    created_by_user_id: int | None
    created_at: datetime


class ManualCaptureAuditEntry(BaseModel):
    id: UUID
    data_source_id: UUID
    name: str
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CompanyAuditResponse(BaseModel):
    sources: list[SourceAuditEntry]
    imports: list[ImportAuditEntry]
    manual_captures: list[ManualCaptureAuditEntry]


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.post("/onboarding", response_model=CompanyOnboardingResponse, status_code=status.HTTP_201_CREATED)
def onboard_company(
    payload: CompanyOnboardingCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    tenant, company = CompanyService(db).onboard_company(user, **payload.model_dump())
    return CompanyOnboardingResponse(tenant=tenant, company=company)


@router.get("/mine", response_model=list[Company])
def list_my_companies(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    return CompanyService(db).list_companies_for_user(user)


@tenant_router.post("/{tenant_id}/companies", response_model=Company, status_code=status.HTTP_201_CREATED)
def create_company_in_tenant(
    tenant_id: UUID,
    payload: CompanyCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    CompanyService(db).get_tenant(tenant_id)
    require_tenant_owner(user, db, tenant_id)
    return CompanyService(db).create_company_in_tenant(user, tenant_id=tenant_id, **payload.model_dump())


@router.patch("/{company_id}", response_model=Company)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, {CompanyRole.OWNER})
    changes = payload.model_dump(exclude_unset=True)
    return CompanyService(db).update_company(
        company_id,
        **changes,
        update_provider_company_id="provider_company_id" in payload.model_fields_set,
    )


@router.post("/{company_id}/disable", response_model=Company)
def disable_company(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_tenant_owner(user, db, company.tenant_id)
    return CompanyService(db).set_company_status(company_id, CompanyStatus.DISABLED)


@router.post("/{company_id}/activate", response_model=Company)
def activate_company(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_tenant_owner(user, db, company.tenant_id)
    return CompanyService(db).set_company_status(company_id, CompanyStatus.ACTIVE)


@router.get("/{company_id}/audit", response_model=CompanyAuditResponse)
def get_company_audit(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    audit = CompanyAuditService(db)
    return CompanyAuditResponse(
        sources=[
            SourceAuditEntry(
                id=UUID(source.id),
                display_name=source.display_name,
                connector_id=source.connector_id,
                created_by_user_id=source.created_by_user_id,
                created_at=source.created_at,
            )
            for source in audit.sources(str(company.id))
        ],
        imports=[
            ImportAuditEntry(
                id=UUID(batch.id),
                data_source_id=UUID(batch.data_source_id),
                entity=batch.entity,
                file_format=batch.file_format,
                accepted_rows=batch.accepted_rows,
                rejected_rows=batch.rejected_rows,
                created_by_user_id=batch.created_by_user_id,
                created_at=batch.created_at,
            )
            for batch in audit.imports(str(company.id))
        ],
        manual_captures=[
            ManualCaptureAuditEntry(
                id=UUID(party.id),
                data_source_id=UUID(party.data_source_id),
                name=party.name,
                created_by_user_id=party.created_by_user_id,
                updated_by_user_id=party.updated_by_user_id,
                created_at=party.created_at,
                updated_at=party.updated_at,
            )
            for party in audit.manual_parties(str(company.id))
        ],
    )


@router.get("/{company_id}", response_model=Company)
def get_company(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    return company
