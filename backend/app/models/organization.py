"""Persistencia de tenants y empresas propietarias de los datos canónicos."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TenantRecord(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    country_code: Mapped[str] = mapped_column(String(2), default="CO")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompanyRecord(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    functional_currency: Mapped[str] = mapped_column(String(3), default="COP")
    provider_company_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TenantRole(str, Enum):
    OWNER = "owner"


class TenantMembership(Base):
    """Propiedad del tenant para administrar todas sus empresas."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=TenantRole.OWNER.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
