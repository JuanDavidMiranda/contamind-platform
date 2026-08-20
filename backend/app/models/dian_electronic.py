"""Persistencia aislada para facturación electrónica DIAN por software propio.

Este modelo conserva estados, huellas y artefactos cifrados por empresa. No
almacena PIN, PFX, contraseñas ni claves técnicas: esos secretos viven en la
fuente DIAN asociada, cifrados por ``ProviderCredentialRecord``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DianFiscalProfileRecord(Base):
    """Perfil público del emisor para el ambiente de habilitación."""

    __tablename__ = "dian_fiscal_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_dian_fiscal_profiles_company"),
        UniqueConstraint("data_source_id", name="uq_dian_fiscal_profiles_source"),
        CheckConstraint(
            "environment = 'habilitation'",
            name="ck_dian_fiscal_profiles_habilitation_only",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(String(20), default="habilitation")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    software_test_set_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signature_policy_identifier: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    signature_policy_digest_base64: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signature_policy_qualifier_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    legal_name: Mapped[str] = mapped_column(String(255))
    nit: Mapped[str] = mapped_column(String(30), index=True)
    check_digit: Mapped[str] = mapped_column(String(1))
    document_type: Mapped[str] = mapped_column(String(2), default="31")
    tax_regime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str] = mapped_column(String(255))
    city_code: Mapped[str] = mapped_column(String(10))
    city_name: Mapped[str] = mapped_column(String(100))
    department_code: Mapped[str] = mapped_column(String(10))
    department_name: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(2), default="CO")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DianNumberingRangeRecord(Base):
    """Rango de prueba reservado con consecutivos no reutilizables."""

    __tablename__ = "dian_numbering_ranges"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "prefix",
            "range_from",
            "range_to",
            name="uq_dian_numbering_ranges_profile_prefix_bounds",
        ),
        CheckConstraint("range_from > 0", name="ck_dian_numbering_ranges_from_positive"),
        CheckConstraint("range_to >= range_from", name="ck_dian_numbering_ranges_bounds"),
        CheckConstraint(
            "next_number >= range_from AND next_number <= range_to + 1",
            name="ck_dian_numbering_ranges_next_bounds",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("dian_fiscal_profiles.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    prefix: Mapped[str] = mapped_column(String(20), index=True)
    resolution_number: Mapped[str] = mapped_column(String(100))
    resolution_date: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    range_from: Mapped[int] = mapped_column(Integer)
    range_to: Mapped[int] = mapped_column(Integer)
    next_number: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DianElectronicDocumentRecord(Base):
    """Documento inmutable ya construido y firmado para la cola de DIAN."""

    __tablename__ = "dian_electronic_documents"
    __table_args__ = (
        UniqueConstraint("source_invoice_id", name="uq_dian_electronic_documents_invoice"),
        # Un consecutivo queda bloqueado mientras exista una versión no rechazada.
        # DIAN permite corregir un rechazo definitivo conservando la combinación
        # prefijo + consecutivo, pero nunca permite crear en paralelo dos
        # versiones enviables de la misma prueba.
        Index(
            "uq_dian_electronic_documents_unrejected_number",
            "company_id",
            "prefix",
            "consecutive",
            unique=True,
            sqlite_where=text("status <> 'rejected'"),
            postgresql_where=text("status <> 'rejected'"),
        ),
        UniqueConstraint(
            "corrects_document_id", name="uq_dian_electronic_documents_correction"
        ),
        CheckConstraint("consecutive > 0", name="ck_dian_electronic_documents_consecutive_positive"),
        Index("ix_dian_electronic_documents_company_status", "company_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("dian_fiscal_profiles.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    source_invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    corrects_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("dian_electronic_documents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(30), default="invoice")
    prefix: Mapped[str] = mapped_column(String(20))
    consecutive: Mapped[int] = mapped_column(Integer)
    document_number: Mapped[str] = mapped_column(String(50), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    currency_code: Mapped[str] = mapped_column(String(3))
    payable_amount: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(30), default="prepared", index=True)
    source_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    unsigned_xml_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signed_xml_sha256: Mapped[str] = mapped_column(String(64))
    signed_xml_ciphertext: Mapped[str] = mapped_column(Text)
    signed_zip_ciphertext: Mapped[str] = mapped_column(Text)
    artifact_key_version: Mapped[str] = mapped_column(String(32))
    dian_document_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DianElectronicOutboxJobRecord(Base):
    """Trabajo durable de transmisión o consulta con una única ejecución activa."""

    __tablename__ = "dian_electronic_outbox_jobs"
    __table_args__ = (
        UniqueConstraint("active_document_id", name="uq_dian_electronic_outbox_active_document"),
        Index("ix_dian_electronic_outbox_ready", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("dian_electronic_documents.id", ondelete="CASCADE"), index=True
    )
    active_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DianElectronicSubmissionRecord(Base):
    """Bitácora de respuesta normalizada, sin almacenar el SOAP completo."""

    __tablename__ = "dian_electronic_submissions"
    __table_args__ = (
        Index("ix_dian_electronic_submissions_document_created", "document_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("dian_electronic_documents.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("dian_electronic_outbox_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(30))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    track_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_description: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    status_message: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DianElectronicDocumentStatusEventRecord(Base):
    """Historial inmutable de las transiciones de cada documento electrónico."""

    __tablename__ = "dian_electronic_document_status_events"
    __table_args__ = (
        Index("ix_dian_electronic_status_events_document_created", "document_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("dian_electronic_documents.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
