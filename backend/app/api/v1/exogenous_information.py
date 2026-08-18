"""Vista operativa protegida para preparar información exógena."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import User
from app.services.company_service import CompanyService
from app.services.exogenous_information_service import ExogenousInformationService
from app.shared.company_access import VIEW_COMPANY_ROLES, require_company_role
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Exogenous information"])


class ExogenousInformationExceptionResponse(BaseModel):
    record_id: UUID
    record_type: Literal["party", "invoice", "payment"]
    record_label: str
    record_date: date | None
    issue_codes: list[str]


class ExogenousInformationExceptionsResponse(BaseModel):
    tax_year: int = Field(ge=2000, le=2100)
    total: int = Field(ge=0)
    items: list[ExogenousInformationExceptionResponse]


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


@router.get(
    "/{company_id}/exogenous-information/exceptions",
    response_model=ExogenousInformationExceptionsResponse,
)
def list_exogenous_information_exceptions(
    company_id: UUID,
    tax_year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    page = ExogenousInformationService(db).exceptions(
        company.id,
        tax_year=tax_year,
        limit=limit,
        offset=offset,
    )
    return ExogenousInformationExceptionsResponse(
        tax_year=page.tax_year,
        total=page.total,
        items=[
            ExogenousInformationExceptionResponse(
                record_id=item.record_id,
                record_type=item.record_type,
                record_label=item.record_label,
                record_date=item.record_date,
                issue_codes=list(item.issue_codes),
            )
            for item in page.items
        ],
    )
