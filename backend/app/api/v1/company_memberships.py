"""Administración de membresías que otorgan acceso a una empresa."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import CompanyMembership, CompanyRole, User
from app.shared.company_access import MANAGE_MEMBERSHIPS_ROLES, require_company_role
from app.shared.errors import app_error
from app.shared.security import get_current_user

router = APIRouter(prefix="/company-memberships", tags=["Company memberships"])


class CompanyMembershipWrite(BaseModel):
    user_id: int = Field(gt=0)
    company_id: UUID
    role: CompanyRole


class CompanyMembershipResponse(BaseModel):
    user_id: int
    company_id: UUID
    role: CompanyRole

    @classmethod
    def from_record(cls, membership: CompanyMembership) -> "CompanyMembershipResponse":
        return cls(
            user_id=membership.user_id,
            company_id=UUID(membership.company_id),
            role=CompanyRole(membership.role),
        )


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


def _require_membership_manager(user: User, db: Session, company_id: UUID) -> None:
    require_company_role(user, db, company_id, MANAGE_MEMBERSHIPS_ROLES)


@router.put("", response_model=CompanyMembershipResponse)
def upsert_membership(
    payload: CompanyMembershipWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _require_membership_manager(user, db, payload.company_id)
    if db.get(User, payload.user_id) is None:
        raise app_error("NOT_FOUND", message="Usuario no encontrado.")

    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.user_id == payload.user_id,
            CompanyMembership.company_id == str(payload.company_id),
        )
    )
    if membership is None:
        membership = CompanyMembership(
            user_id=payload.user_id,
            company_id=str(payload.company_id),
            role=payload.role.value,
        )
        db.add(membership)
    else:
        membership.role = payload.role.value
    db.commit()
    db.refresh(membership)
    return CompanyMembershipResponse.from_record(membership)


@router.get("", response_model=list[CompanyMembershipResponse])
def list_memberships(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _require_membership_manager(user, db, company_id)
    memberships = db.scalars(
        select(CompanyMembership)
        .where(CompanyMembership.company_id == str(company_id))
        .order_by(CompanyMembership.user_id)
    )
    return [CompanyMembershipResponse.from_record(item) for item in memberships]


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_membership(
    user_id: int,
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _require_membership_manager(user, db, company_id)
    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.user_id == user_id,
            CompanyMembership.company_id == str(company_id),
        )
    )
    if membership is None:
        raise app_error("NOT_FOUND", message="Membresía no encontrada.")
    db.delete(membership)
    db.commit()

