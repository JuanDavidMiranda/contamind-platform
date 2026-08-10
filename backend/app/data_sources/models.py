"""Contratos neutrales para conectar o importar datos de cada empresa."""

import re
from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from app.providers.canonical import CanonicalModel, Party, PartyType


class DataSourceKind(str, Enum):
    ACCOUNTING_SOFTWARE = "accounting_software"
    FILE_IMPORT = "file_import"
    DATABASE_CONNECTION = "database_connection"
    MANUAL_ENTRY = "manual_entry"
    FISCAL_AUTHORITY = "fiscal_authority"


class ConnectionMode(str, Enum):
    CLOUD_API = "cloud_api"
    FILE_UPLOAD = "file_upload"
    LOCAL_AGENT = "local_agent"
    DATABASE_CONNECTOR = "database_connector"
    MANUAL = "manual"
    FISCAL_SERVICE = "fiscal_service"


class DataSourceStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"
    DISABLED = "disabled"


class ProviderOperation(str, Enum):
    CONNECTION_TEST = "connection_test"
    SYNC_PARTIES = "sync_parties"


class ProviderRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DataCapability(str, Enum):
    PARTIES = "parties"
    TAXES = "taxes"
    ITEMS = "items"
    INVOICES = "invoices"
    PAYMENTS = "payments"
    JOURNALS = "journals"
    PAYROLL = "payroll"
    FILE_IMPORT_EXPORT = "file_import_export"


class FileFormat(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"


class ImportEntity(str, Enum):
    PARTIES = "parties"
    TAXES = "taxes"
    ITEMS = "items"
    INVOICES = "invoices"
    PAYMENTS = "payments"
    JOURNAL_ENTRIES = "journal_entries"


_CONNECTOR_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ConnectorId = Annotated[str, Field(pattern=_CONNECTOR_ID_PATTERN.pattern)]


def normalize_connector_id(value: str) -> str:
    normalized = value.strip().lower()
    if not _CONNECTOR_ID_PATTERN.fullmatch(normalized):
        raise ValueError("El identificador de conector debe usar minúsculas, números y guiones bajos.")
    return normalized


class CompanyDataSource(CanonicalModel):
    """Configuración no sensible de una fuente que alimenta a una empresa."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    company_id: UUID
    connector_id: ConnectorId
    display_name: str = Field(min_length=1, max_length=255)
    kind: DataSourceKind
    mode: ConnectionMode
    capabilities: frozenset[DataCapability] = frozenset()
    provider_id: str | None = Field(default=None, max_length=64)
    credential_reference: str | None = Field(default=None, max_length=255)
    status: DataSourceStatus = DataSourceStatus.PENDING
    last_connection_checked_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_sync_cursor: str | None = Field(default=None, max_length=512)

    @field_validator("connector_id", "provider_id", mode="before")
    @classmethod
    def normalize_ids(cls, value: str | None) -> str | None:
        return normalize_connector_id(value) if value is not None else None

    @model_validator(mode="after")
    def validate_source(self) -> "CompanyDataSource":
        if self.kind in (DataSourceKind.ACCOUNTING_SOFTWARE, DataSourceKind.FISCAL_AUTHORITY):
            if self.provider_id is None:
                raise ValueError("Las fuentes de software o autoridad fiscal requieren provider_id.")
        if self.kind is DataSourceKind.FILE_IMPORT and self.mode is not ConnectionMode.FILE_UPLOAD:
            raise ValueError("Una fuente de archivos debe usar el modo file_upload.")
        if self.kind is DataSourceKind.MANUAL_ENTRY and self.mode is not ConnectionMode.MANUAL:
            raise ValueError("La captura manual debe usar el modo manual.")
        return self


class DataSourceContext(CanonicalModel):
    tenant_id: UUID
    company_id: UUID
    data_source_id: UUID
    connector_id: ConnectorId
    correlation_id: str | None = Field(default=None, max_length=64)

    @field_validator("connector_id", mode="before")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_connector_id(value)


class ImportProfile(CanonicalModel):
    """Mapeo explícito entre columnas de archivo y campos canónicos."""

    id: UUID = Field(default_factory=uuid4)
    data_source_id: UUID
    entity: ImportEntity
    file_format: FileFormat
    column_mapping: dict[str, str] = Field(min_length=1)
    default_party_type: PartyType = PartyType.CUSTOMER


class ImportRejection(CanonicalModel):
    row_number: int = Field(ge=2)
    message: str = Field(min_length=1, max_length=500)


class PartyImportResult(CanonicalModel):
    parties: tuple[Party, ...]
    rejections: tuple[ImportRejection, ...]


class AccountingImportResult(CanonicalModel):
    entity: ImportEntity
    accepted_rows: int = Field(ge=0)
    rejections: tuple[ImportRejection, ...]


class ImportAuditEvent(CanonicalModel):
    data_source_id: UUID
    company_id: UUID
    entity: ImportEntity
    accepted_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    correlation_id: str | None = Field(default=None, max_length=64)


class ProviderOperationResult(CanonicalModel):
    id: UUID
    data_source_id: UUID
    provider_id: str
    operation: ProviderOperation
    status: ProviderRunStatus
    processed_records: int = Field(ge=0)
    cursor_before: str | None = None
    cursor_after: str | None = None
    error_code: str | None = None
    correlation_id: str | None = None
    completed_at: datetime
