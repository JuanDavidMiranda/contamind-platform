"""Casos de uso persistentes para configurar e importar fuentes de datos."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.data_sources.csv_import import CsvPartyImportSource
from app.data_sources.models import (
    AccountingImportResult,
    CompanyDataSource,
    DataSourceContext,
    DataSourceKind,
    DataSourceStatus,
    FileFormat,
    ImportEntity,
    ImportProfile,
    PartyImportResult,
)
from app.data_sources.xlsx_import import XlsxPartyImportSource
from app.models.data_source import (
    CompanyDataSourceRecord,
    ImportBatchRecord,
    ImportProfileRecord,
    PartyRecord,
)
from app.providers.canonical import Party, PartyType
from app.shared.errors import app_error


class DataSourceService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._csv_importer = CsvPartyImportSource()
        self._xlsx_importer = XlsxPartyImportSource()

    def create_source(
        self, source: CompanyDataSource, *, actor_user_id: int | None = None
    ) -> CompanyDataSource:
        if source.provider_id is not None:
            source = source.model_copy(
                update={
                    "credential_reference": None,
                    "status": DataSourceStatus.PENDING,
                    "last_connection_checked_at": None,
                    "last_synced_at": None,
                    "last_sync_cursor": None,
                }
            )
        self._db.add(
            CompanyDataSourceRecord(
                id=str(source.id),
                tenant_id=str(source.tenant_id),
                company_id=str(source.company_id),
                connector_id=source.connector_id,
                display_name=source.display_name,
                kind=source.kind.value,
                mode=source.mode.value,
                capabilities=sorted(capability.value for capability in source.capabilities),
                provider_id=source.provider_id,
                credential_reference=source.credential_reference,
                status=source.status.value,
                created_by_user_id=actor_user_id,
                last_connection_checked_at=source.last_connection_checked_at,
                last_synced_at=source.last_synced_at,
                last_sync_cursor=source.last_sync_cursor,
            )
        )
        self._db.commit()
        return source

    def list_sources(self, company_id: UUID) -> list[CompanyDataSource]:
        records = self._db.scalars(
            select(CompanyDataSourceRecord)
            .where(CompanyDataSourceRecord.company_id == str(company_id))
            .order_by(CompanyDataSourceRecord.created_at)
        )
        return [self._source_from_record(record) for record in records]

    def get_source(self, source_id: UUID) -> CompanyDataSource:
        """Expone la fuente solo para que la capa API determine su ámbito."""

        return self._get_source(source_id)

    def create_profile(self, profile: ImportProfile) -> ImportProfile:
        self._get_source(profile.data_source_id)
        self._db.add(
            ImportProfileRecord(
                id=str(profile.id),
                data_source_id=str(profile.data_source_id),
                entity=profile.entity.value,
                file_format=profile.file_format.value,
                column_mapping=profile.column_mapping,
                default_party_type=profile.default_party_type.value,
            )
        )
        self._db.commit()
        return profile

    async def import_parties(
        self,
        data_source_id: UUID,
        profile_id: UUID,
        content: bytes,
        uploaded_format: FileFormat | None = None,
        actor_user_id: int | None = None,
    ) -> tuple[UUID, PartyImportResult]:
        source = self._get_source(data_source_id)
        profile = self._get_profile(profile_id)
        if uploaded_format is not None and uploaded_format is not profile.file_format:
            raise app_error(
                "CONFLICT", message="La extensión del archivo no coincide con el perfil de importación."
            )
        context = DataSourceContext(
            tenant_id=source.tenant_id,
            company_id=source.company_id,
            data_source_id=source.id,
            connector_id=source.connector_id,
        )
        if profile.file_format is FileFormat.CSV:
            if source.connector_id != self._csv_importer.connector_id:
                raise app_error("CONFLICT", message="La fuente no está configurada para importar CSV.")
            try:
                result = await self._csv_importer.import_parties(
                    context, source, profile, content.decode("utf-8-sig")
                )
            except UnicodeDecodeError as exc:
                raise app_error(
                    "VALIDATION_ERROR", message="El archivo CSV debe usar codificación UTF-8."
                ) from exc
        else:
            if source.connector_id != self._xlsx_importer.connector_id:
                raise app_error("CONFLICT", message="La fuente no está configurada para importar XLSX.")
            result = await self._xlsx_importer.import_parties(context, source, profile, content)

        persisted_parties = tuple(
            self._upsert_party(source.id, party, actor_user_id=actor_user_id)
            for party in result.parties
        )
        batch_id = uuid4()
        self._db.add(
            ImportBatchRecord(
                id=str(batch_id),
                data_source_id=str(source.id),
                company_id=str(source.company_id),
                entity=ImportEntity.PARTIES.value,
                file_format=profile.file_format.value,
                content_sha256=hashlib.sha256(content).hexdigest(),
                accepted_rows=len(persisted_parties),
                rejected_rows=len(result.rejections),
                correlation_id=context.correlation_id,
                created_by_user_id=actor_user_id,
            )
        )
        self._db.commit()
        return batch_id, result.model_copy(update={"parties": persisted_parties})

    def import_accounting(
        self,
        data_source_id: UUID,
        profile_id: UUID,
        content: bytes,
        *,
        uploaded_format: FileFormat,
        actor_user_id: int,
    ) -> tuple[UUID, AccountingImportResult]:
        source = self._get_source(data_source_id)
        profile = self._get_profile(profile_id)
        if uploaded_format is not profile.file_format:
            raise app_error(
                "CONFLICT", message="La extensión del archivo no coincide con el perfil de importación."
            )
        from app.services.accounting_file_import_service import AccountingFileImportService

        result = AccountingFileImportService(self._db).import_content(
            source,
            profile,
            content,
            uploaded_format=uploaded_format,
            actor_user_id=actor_user_id,
        )
        batch_id = uuid4()
        self._db.add(
            ImportBatchRecord(
                id=str(batch_id),
                data_source_id=str(source.id),
                company_id=str(source.company_id),
                entity=profile.entity.value,
                file_format=profile.file_format.value,
                content_sha256=hashlib.sha256(content).hexdigest(),
                accepted_rows=result.accepted_rows,
                rejected_rows=len(result.rejections),
                correlation_id=None,
                created_by_user_id=actor_user_id,
            )
        )
        self._db.commit()
        return batch_id, result

    def capture_manual_party(
        self,
        data_source_id: UUID,
        *,
        party_type: PartyType,
        name: str,
        document_type: str | None = None,
        document_number: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        address: str | None = None,
        fiscal_responsibility: str | None = None,
        actor_user_id: int | None = None,
    ) -> Party:
        """Registra o actualiza un tercero desde una fuente manual de la empresa."""

        source = self._get_source(data_source_id)
        if source.kind is not DataSourceKind.MANUAL_ENTRY:
            raise app_error(
                "CONFLICT",
                message="La fuente no está configurada para captura manual.",
            )
        party = Party(
            company_id=source.company_id,
            party_type=party_type,
            name=name,
            document_type=document_type,
            document_number=document_number,
            email=email,
            phone=phone,
            city=city,
            address=address,
            fiscal_responsibility=fiscal_responsibility,
        )
        persisted_party = self._upsert_party(source.id, party, actor_user_id=actor_user_id)
        self._db.commit()
        return persisted_party

    def upsert_provider_party(
        self,
        data_source_id: UUID,
        party: Party,
        *,
        actor_user_id: int,
    ) -> Party:
        """Persiste un tercero ya normalizado por un adaptador de proveedor."""

        source = self._get_source(data_source_id)
        if party.company_id != source.company_id:
            raise app_error(
                "CONFLICT",
                message="El tercero retornado no pertenece a la empresa de la fuente.",
            )
        return self._upsert_party(data_source_id, party, actor_user_id=actor_user_id)

    def _get_source(self, source_id: UUID) -> CompanyDataSource:
        record = self._db.get(CompanyDataSourceRecord, str(source_id))
        if record is None:
            raise app_error("NOT_FOUND", message="Fuente de datos no encontrada.")
        return self._source_from_record(record)

    def _get_profile(self, profile_id: UUID) -> ImportProfile:
        record = self._db.get(ImportProfileRecord, str(profile_id))
        if record is None:
            raise app_error("NOT_FOUND", message="Perfil de importación no encontrado.")
        return ImportProfile(
            id=UUID(record.id),
            data_source_id=UUID(record.data_source_id),
            entity=record.entity,
            file_format=record.file_format,
            column_mapping=record.column_mapping,
            default_party_type=record.default_party_type,
        )

    @staticmethod
    def _source_from_record(record: CompanyDataSourceRecord) -> CompanyDataSource:
        return CompanyDataSource(
            id=UUID(record.id),
            tenant_id=UUID(record.tenant_id),
            company_id=UUID(record.company_id),
            connector_id=record.connector_id,
            display_name=record.display_name,
            kind=record.kind,
            mode=record.mode,
            capabilities=set(record.capabilities),
            provider_id=record.provider_id,
            credential_reference=record.credential_reference,
            status=record.status,
            last_connection_checked_at=record.last_connection_checked_at,
            last_synced_at=record.last_synced_at,
            last_sync_cursor=record.last_sync_cursor,
        )

    def _upsert_party(
        self, data_source_id: UUID, party: Party, *, actor_user_id: int | None = None
    ) -> Party:
        filters = [PartyRecord.company_id == str(party.company_id)]
        if party.external_id:
            filters.append(PartyRecord.external_id == party.external_id)
        elif party.document_number:
            filters.extend(
                [
                    PartyRecord.document_type == party.document_type,
                    PartyRecord.document_number == party.document_number,
                ]
            )
        else:
            return self._create_party(data_source_id, party, actor_user_id=actor_user_id)

        record = self._db.scalar(select(PartyRecord).where(and_(*filters)))
        if record is None:
            return self._create_party(data_source_id, party, actor_user_id=actor_user_id)
        self._copy_party_to_record(record, data_source_id, party, actor_user_id=actor_user_id)
        return party.model_copy(update={"id": UUID(record.id)})

    def _create_party(
        self, data_source_id: UUID, party: Party, *, actor_user_id: int | None = None
    ) -> Party:
        record = PartyRecord(
            id=str(party.id),
            company_id=str(party.company_id),
            party_type=party.party_type.value,
            name=party.name,
            created_by_user_id=actor_user_id,
        )
        self._copy_party_to_record(record, data_source_id, party, actor_user_id=actor_user_id)
        self._db.add(record)
        return party

    @staticmethod
    def _copy_party_to_record(
        record: PartyRecord,
        data_source_id: UUID,
        party: Party,
        *,
        actor_user_id: int | None = None,
    ) -> None:
        record.data_source_id = str(data_source_id)
        record.party_type = party.party_type.value
        record.name = party.name
        record.document_type = party.document_type
        record.document_number = party.document_number
        record.email = party.email
        record.phone = party.phone
        record.city = party.city
        record.address = party.address
        record.fiscal_responsibility = party.fiscal_responsibility
        record.external_id = party.external_id
        record.integration_id = party.integration_id
        record.updated_by_user_id = actor_user_id
