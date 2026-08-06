from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import Subscription, User
from app.shared.security import get_current_user

router = APIRouter(prefix="/admin", tags=["Administration"])


class SubscriptionUpdate(BaseModel):
    plan_code: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, min_length=1, max_length=50)
    company_limit: int | None = Field(default=None, ge=1)


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
