"""Autorización RBAC con alcance estricto a una empresa."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import CompanyMembership, CompanyRole, User
from app.shared.errors import app_error


VIEW_COMPANY_ROLES = frozenset(CompanyRole)
OPERATE_SOURCES_ROLES = frozenset({CompanyRole.OWNER, CompanyRole.ADMIN, CompanyRole.OPERATOR})
MANAGE_SOURCES_ROLES = frozenset({CompanyRole.OWNER, CompanyRole.ADMIN})
MANAGE_MEMBERSHIPS_ROLES = frozenset({CompanyRole.OWNER})


def get_company_membership(
    db: Session, *, user_id: int, company_id: UUID
) -> CompanyMembership | None:
    return db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.user_id == user_id,
            CompanyMembership.company_id == str(company_id),
        )
    )


def require_company_role(
    user: User,
    db: Session,
    company_id: UUID,
    allowed_roles: Collection[CompanyRole],
) -> CompanyRole | None:
    """Autoriza el acceso sin confiar nunca en un `company_id` enviado por el cliente.

    Los administradores de plataforma son una excepción operacional explícita;
    cualquier otro usuario debe tener una membresía activa en esa empresa.
    """

    if user.is_platform_admin:
        return None

    membership = get_company_membership(db, user_id=user.id, company_id=company_id)
    if membership is None:
        raise app_error(
            "FORBIDDEN",
            message="No tienes acceso a esta empresa.",
        )

    try:
        role = CompanyRole(membership.role)
    except ValueError:
        raise app_error(
            "FORBIDDEN",
            message="La membresía de la empresa tiene un rol no válido.",
        ) from None

    if role not in allowed_roles:
        raise app_error(
            "FORBIDDEN",
            message="Tu rol no permite realizar esta operación en la empresa.",
        )
    return role

