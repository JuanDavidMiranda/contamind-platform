from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.database import get_db
from app.models.user import User
from app.shared.errors import app_error
from app.shared.security import (
    create_access_token,
    get_current_user,
    hash_password,
    validate_new_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_new_password(value)


def is_configured_admin(email: str) -> bool:
    configured_emails = {
        value.strip().lower()
        for value in settings.PLATFORM_ADMIN_EMAILS.split(",")
        if value.strip()
    }
    return email.lower() in configured_emails


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise app_error("AUTH_INVALID_CREDENTIALS")

    if is_configured_admin(user.email) and not user.is_platform_admin:
        user.is_platform_admin = True
        db.commit()
        db.refresh(user)

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user_id": user.id,
        "is_platform_admin": user.is_platform_admin,
        "requires_password_change": user.requires_password_change,
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Rota una clave temporal y revoca las sesiones anteriores del usuario."""

    user = get_current_user(authorization, db, allow_password_change=True)
    if not verify_password(payload.current_password, user.password_hash):
        raise app_error("AUTH_INVALID_CREDENTIALS", message="La contraseña actual no es válida.")
    if payload.current_password == payload.new_password:
        raise app_error("VALIDATION_ERROR", message="La nueva contraseña debe ser diferente.")

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    user.requires_password_change = False
    db.commit()
    db.refresh(user)
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "requires_password_change": False,
    }
