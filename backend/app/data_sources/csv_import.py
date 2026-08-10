"""Ingreso universal de terceros desde CSV mediante perfiles de mapeo explícitos."""

import csv
from collections.abc import Iterable
from io import StringIO

from app.data_sources.models import (
    CompanyDataSource,
    ConnectionMode,
    DataSourceContext,
    DataSourceKind,
    FileFormat,
    ImportAuditEvent,
    ImportEntity,
    ImportProfile,
    ImportRejection,
    PartyImportResult,
)
from app.data_sources.ports import DataSourcePort
from app.providers.canonical import Party
from app.shared.errors import app_error


class CsvPartyImportSource(DataSourcePort):
    """Importador sin I/O externo; el controlador entrega el contenido cargado por el cliente."""

    connector_id = "csv_import"
    supported_modes = frozenset({ConnectionMode.FILE_UPLOAD})

    def __init__(self) -> None:
        self._audit_events: list[ImportAuditEvent] = []

    @property
    def audit_events(self) -> tuple[ImportAuditEvent, ...]:
        return tuple(self._audit_events)

    async def import_parties(
        self,
        context: DataSourceContext,
        source: CompanyDataSource,
        profile: ImportProfile,
        content: str,
    ) -> PartyImportResult:
        self._validate_request(context, source, profile, FileFormat.CSV)
        rows = enumerate(csv.DictReader(StringIO(content)), start=2)
        return self._process_rows(context, source, profile, rows)

    def _process_rows(
        self,
        context: DataSourceContext,
        source: CompanyDataSource,
        profile: ImportProfile,
        rows: Iterable[tuple[int, dict[str, str | None]]],
    ) -> PartyImportResult:
        parties: list[Party] = []
        rejections: list[ImportRejection] = []

        for row_number, row in rows:
            try:
                parties.append(self._map_party(context, profile, row))
            except (KeyError, ValueError) as exc:
                rejections.append(ImportRejection(row_number=row_number, message=str(exc)))

        result = PartyImportResult(parties=tuple(parties), rejections=tuple(rejections))
        self._audit_events.append(
            ImportAuditEvent(
                data_source_id=source.id,
                company_id=context.company_id,
                entity=ImportEntity.PARTIES,
                accepted_rows=len(result.parties),
                rejected_rows=len(result.rejections),
                correlation_id=context.correlation_id,
            )
        )
        return result

    @staticmethod
    def _validate_request(
        context: DataSourceContext,
        source: CompanyDataSource,
        profile: ImportProfile,
        expected_format: FileFormat,
    ) -> None:
        if source.id != context.data_source_id or source.company_id != context.company_id:
            raise app_error("CONFLICT", message="La fuente no pertenece al contexto de empresa.")
        if source.kind is not DataSourceKind.FILE_IMPORT or source.mode is not ConnectionMode.FILE_UPLOAD:
            raise app_error("CONFLICT", message="La fuente no está configurada para importar archivos.")
        if profile.data_source_id != source.id:
            raise app_error("CONFLICT", message="El perfil no pertenece a la fuente de datos.")
        if profile.entity is not ImportEntity.PARTIES or profile.file_format is not expected_format:
            raise app_error("CONFLICT", message="El perfil no corresponde al formato de importación solicitado.")

    @staticmethod
    def _map_party(
        context: DataSourceContext,
        profile: ImportProfile,
        row: dict[str, str | None],
    ) -> Party:
        def value(field: str, *, required: bool = False) -> str | None:
            column = profile.column_mapping.get(field)
            if column is None:
                if required:
                    raise ValueError(f"Falta el mapeo obligatorio para '{field}'.")
                return None
            content = (row.get(column) or "").strip()
            if required and not content:
                raise ValueError(f"La columna '{column}' es obligatoria.")
            return content or None

        return Party(
            company_id=context.company_id,
            party_type=profile.default_party_type,
            name=value("name", required=True) or "",
            document_type=value("document_type"),
            document_number=value("document_number"),
            email=value("email"),
            phone=value("phone"),
            city=value("city"),
            address=value("address"),
            external_id=value("external_id"),
        )
