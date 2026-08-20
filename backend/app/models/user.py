from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Incrementar este valor invalida todos los JWT emitidos antes del cambio.
    # Es especialmente importante al rotar una contraseña temporal de beta.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # Una cuenta entregada para la beta no puede operar hasta reemplazar la
    # contraseña temporal compartida por el administrador de plataforma.
    requires_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompanyRole(str, Enum):
    """Roles que delimitan el acceso de un usuario a una empresa concreta."""

    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class CompanyMembership(Base):
    """Relación explícita entre un usuario y una empresa canónica.

    La empresa aún no tiene una tabla propia porque puede provenir de distintas
    fuentes contables. Por eso `company_id` conserva el UUID canónico que usan
    las fuentes de datos y los terceros.
    """

    __tablename__ = "company_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_company_memberships_user_company"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=CompanyRole.OPERATOR.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    plan_code: Mapped[str] = mapped_column(String(50), default="trial")
    status: Mapped[str] = mapped_column(String(50), default="trialing")
    company_limit: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
