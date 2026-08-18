"""Auditoría de importaciones de evidencia de facturación electrónica."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ElectronicInvoiceEvidenceImportRecord(Base):
    __tablename__ = "electronic_invoice_evidence_imports"
    __table_args__ = (
        CheckConstraint(
            "file_format IN ('csv', 'xlsx')",
            name="ck_electronic_invoice_evidence_imports_file_format",
        ),
        Index(
            "ix_electronic_invoice_evidence_imports_company_created",
            "company_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    file_format: Mapped[str] = mapped_column(String(10))
    content_sha256: Mapped[str] = mapped_column(String(64))
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ElectronicInvoiceEvidenceImportRowRecord(Base):
    __tablename__ = "electronic_invoice_evidence_import_rows"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'rejected')",
            name="ck_electronic_invoice_evidence_import_rows_outcome",
        ),
        Index(
            "ix_electronic_invoice_evidence_import_rows_import_outcome",
            "import_id",
            "outcome",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("electronic_invoice_evidence_imports.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
