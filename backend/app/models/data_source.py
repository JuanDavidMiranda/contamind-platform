"""Persistencia de fuentes, perfiles, lotes y terceros canónicos importados."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CompanyDataSourceRecord(Base):
    __tablename__ = "company_data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    connector_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(50))
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    last_connection_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProviderCredentialRecord(Base):
    """Secreto cifrado y aislado por fuente; nunca conserva valores en claro."""

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("data_source_id", name="uq_provider_credentials_data_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        ForeignKey("company_data_sources.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    key_version: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProviderSyncRunRecord(Base):
    """Bitácora sin payload para pruebas de conexión y sincronizaciones."""

    __tablename__ = "provider_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        ForeignKey("company_data_sources.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    cursor_before: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processed_records: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProviderSyncJobRecord(Base):
    """Cola persistente de sincronizaci\u00f3n, aislada por fuente de datos.

    ``active_data_source_id`` es nulo cuando el trabajo ya termin\u00f3. Su
    restricci\u00f3n \u00fanica impide que se encole o ejecute m\u00e1s de una sincronizaci\u00f3n
    activa para una misma fuente, tanto en SQLite como en PostgreSQL.
    """

    __tablename__ = "provider_sync_jobs"
    __table_args__ = (
        UniqueConstraint("active_data_source_id", name="uq_provider_sync_jobs_active_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        ForeignKey("company_data_sources.id", ondelete="CASCADE"), index=True
    )
    active_data_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    page_size: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processed_records: Mapped[int] = mapped_column(Integer, default=0)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ImportProfileRecord(Base):
    __tablename__ = "import_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(String(36), index=True)
    entity: Mapped[str] = mapped_column(String(50))
    file_format: Mapped[str] = mapped_column(String(20))
    column_mapping: Mapped[dict[str, str]] = mapped_column(JSON)
    default_party_type: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ImportBatchRecord(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(String(36), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    entity: Mapped[str] = mapped_column(String(50))
    file_format: Mapped[str] = mapped_column(String(20))
    content_sha256: Mapped[str] = mapped_column(String(64))
    accepted_rows: Mapped[int] = mapped_column(Integer)
    rejected_rows: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PartyRecord(Base):
    __tablename__ = "parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    party_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fiscal_responsibility: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    integration_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
