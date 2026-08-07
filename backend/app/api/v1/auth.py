from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.database import get_db
from app.models.user import User
from app.shared.errors import app_error
from app.shared.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


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
    }
