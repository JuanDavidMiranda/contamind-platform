from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import Subscription, User
from app.shared.errors import app_error
from app.shared.security import get_current_user, hash_password, validate_new_password

router = APIRouter(prefix="/admin", tags=["Administration"])


class SubscriptionUpdate(BaseModel):
    plan_code: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, min_length=1, max_length=50)
    company_limit: int | None = Field(default=None, ge=1)


class BetaAccessCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=5, max_length=255)
    temporary_password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Ingresa un correo electrónico válido.")
        return normalized

    @field_validator("temporary_password")
    @classmethod
    def validate_temporary_password(cls, value: str) -> str:
        return validate_new_password(value)


class BetaAccessResponse(BaseModel):
    id: int
    full_name: str
    email: str


def require_admin(authorization: str | None, db: Session) -> User:
    user = get_current_user(authorization, db)
    if not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere un administrador de plataforma.",
        )
    return user


@router.get("/subscriptions")
def list_subscriptions(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(authorization, db)
    return list(db.scalars(select(Subscription).order_by(Subscription.account_id)))


@router.patch("/subscriptions/{account_id}")
def update_subscription(
    account_id: int,
    payload: SubscriptionUpdate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(authorization, db)
    subscription = db.scalar(select(Subscription).where(Subscription.account_id == account_id))
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada.")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(subscription, field, value)

    db.commit()
    db.refresh(subscription)
    return subscription


@router.post("/beta-access", response_model=BetaAccessResponse, status_code=status.HTTP_201_CREATED)
def create_beta_access(
    payload: BetaAccessCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Crea acceso cerrado de beta; no envía ni expone la contraseña temporal."""

    require_admin(authorization, db)
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise app_error("CONFLICT", message="Ya existe una cuenta con ese correo electrónico.")

    user = User(
        full_name=payload.full_name.strip(),
        email=payload.email,
        password_hash=hash_password(payload.temporary_password),
        is_platform_admin=False,
        requires_password_change=True,
    )
    db.add(user)
    db.flush()
    db.add(
        Subscription(
            account_id=user.id,
            plan_code="beta_privada",
            status="trialing",
            company_limit=1,
        )
    )
    db.commit()
    db.refresh(user)
    return BetaAccessResponse(id=user.id, full_name=user.full_name, email=user.email)
