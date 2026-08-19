"""Auditoría mínima de consultas individuales al servicio GetAcquirer DIAN."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DianAcquirerLookupRecord(Base):
    """Nunca almacena el número consultado ni la información devuelta por DIAN."""

    __tablename__ = "dian_acquirer_lookups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        ForeignKey("company_data_sources.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(10))
    document_number_hmac: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
