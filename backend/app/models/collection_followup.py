"""Seguimientos operativos de cobro, separados del n\u00facleo contable can\u00f3nico."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionFollowUpRecord(Base):
    """Registra una promesa o seguimiento sin datos de contacto del tercero.

    La referencia a la factura conserva el alcance contable. La nota se limita
    en la capa de servicio para evitar almacenar identificadores personales o
    instrucciones de cobro.
    """

    __tablename__ = "collection_follow_ups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'contacted', 'promise_to_pay', 'resolved', 'cancelled')",
            name="ck_collection_follow_ups_status",
        ),
        CheckConstraint(
            "(status = 'promise_to_pay' AND promised_date IS NOT NULL) OR "
            "(status != 'promise_to_pay' AND promised_date IS NULL)",
            name="ck_collection_follow_ups_promise_date",
        ),
        Index(
            "ix_collection_follow_ups_company_invoice_updated",
            "company_id",
            "invoice_id",
            "updated_at",
        ),
        Index(
            "ix_collection_follow_ups_company_status_promised",
            "company_id",
            "status",
            "promised_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    promised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    updated_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
