"""API autenticada para registrar seguimiento operativo de cobro."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.collection_followup import CollectionFollowUpRecord
from app.models.user import User
from app.services.collection_followup_service import (
    CollectionFollowUpService,
    CollectionFollowUpStatus,
)
from app.services.company_service import CompanyService
from app.shared.company_access import (
    OPERATE_SOURCES_ROLES,
    VIEW_COMPANY_ROLES,
    require_company_role,
)
from app.shared.security import get_current_user


router = APIRouter(prefix="/companies", tags=["Collection follow-ups"])


class CollectionFollowUpCreate(BaseModel):
    invoice_id: UUID
    status: CollectionFollowUpStatus
    promised_date: date | None = None
    note: str | None = Field(
        default=None,
        description=(
            "Resumen operativo de m\u00e1ximo 280 caracteres, sin nombres, datos de contacto, "
            "documentos, cuentas ni enlaces."
        ),
    )
    confirmed: Literal[True] = Field(
        description="Confirmaci\u00f3n expl\u00edcita del registro; debe ser true."
    )


class CollectionFollowUpUpdate(BaseModel):
    status: CollectionFollowUpStatus | None = None
    promised_date: date | None = None
    note: str | None = Field(
        default=None,
        description=(
            "Resumen operativo de m\u00e1ximo 280 caracteres, sin nombres, datos de contacto, "
            "documentos, cuentas ni enlaces."
        ),
    )
    confirmed: Literal[True] = Field(
        description="Confirmaci\u00f3n expl\u00edcita de la actualizaci\u00f3n; debe ser true."
    )


class CollectionFollowUpResponse(BaseModel):
    id: UUID
    company_id: UUID
    invoice_id: UUID
    status: CollectionFollowUpStatus
    promised_date: date | None
    note: str | None
    created_by_user_id: int
    updated_by_user_id: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: CollectionFollowUpRecord) -> "CollectionFollowUpResponse":
        return cls(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            invoice_id=UUID(record.invoice_id),
            status=CollectionFollowUpStatus(record.status),
            promised_date=record.promised_date,
            note=record.note,
            created_by_user_id=record.created_by_user_id,
            updated_by_user_id=record.updated_by_user_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


def _authorize_company(
    company_id: UUID,
    user: User,
    db: Session,
    allowed_roles,
    *,
    require_active: bool,
) -> None:
    companies = CompanyService(db)
    companies.get_company(company_id)
    if require_active:
        companies.require_active_company(company_id)
    require_company_role(user, db, company_id, allowed_roles)


@router.get("/{company_id}/collection-followups", response_model=list[CollectionFollowUpResponse])
def list_collection_followups(
    company_id: UUID,
    invoice_id: UUID | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Lista seguimientos de la empresa; no devuelve datos de terceros ni factura completa."""

    user = _current_user(authorization, db)
    _authorize_company(company_id, user, db, VIEW_COMPANY_ROLES, require_active=False)
    records = CollectionFollowUpService(db).list_followups(company_id, invoice_id=invoice_id)
    return [CollectionFollowUpResponse.from_record(record) for record in records]


@router.post(
    "/{company_id}/collection-followups",
    response_model=CollectionFollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_collection_followup(
    company_id: UUID,
    payload: CollectionFollowUpCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Registra una promesa o seguimiento confirmado; no env\u00eda cobros."""

    user = _current_user(authorization, db)
    _authorize_company(company_id, user, db, OPERATE_SOURCES_ROLES, require_active=True)
    record = CollectionFollowUpService(db).create_followup(
        company_id,
        invoice_id=payload.invoice_id,
        status=payload.status,
        promised_date=payload.promised_date,
        note=payload.note,
        actor_user_id=user.id,
    )
    return CollectionFollowUpResponse.from_record(record)


@router.patch(
    "/{company_id}/collection-followups/{followup_id}",
    response_model=CollectionFollowUpResponse,
)
def update_collection_followup(
    company_id: UUID,
    followup_id: UUID,
    payload: CollectionFollowUpUpdate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Actualiza un seguimiento confirmado; no modifica la factura ni genera pagos."""

    user = _current_user(authorization, db)
    _authorize_company(company_id, user, db, OPERATE_SOURCES_ROLES, require_active=True)
    record = CollectionFollowUpService(db).update_followup(
        company_id,
        followup_id,
        status=payload.status,
        promised_date=payload.promised_date,
        note=payload.note,
        fields_set=set(payload.model_fields_set),
        actor_user_id=user.id,
    )
    return CollectionFollowUpResponse.from_record(record)
