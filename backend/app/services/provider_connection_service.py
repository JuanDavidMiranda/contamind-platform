"""Ciclo de vida de conexiones externas con secretos cifrados y auditoría."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_sources.models import (
    CompanyDataSource,
    DataSourceStatus,
    ProviderOperation,
    ProviderOperationResult,
    ProviderRunStatus,
)
from app.models.data_source import CompanyDataSourceRecord, ProviderSyncRunRecord
from app.providers.canonical import ProviderContext
from app.providers.credential_store import EncryptedDatabaseSecretStore
from app.providers.factory import ProviderFactory
from app.providers.runtime import default_provider_factory
from app.providers.secrets import ProviderSecret
from app.services.data_source_service import DataSourceService
from app.shared.errors import AppError, app_error


class ProviderConnectionService:
    """Coordina fuentes, secretos y adaptadores sin filtrar credenciales."""

    def __init__(
        self,
        db: Session,
        *,
        provider_factory: ProviderFactory | None = None,
        secret_store: EncryptedDatabaseSecretStore | None = None,
    ) -> None:
        self._db = db
        self._sources = DataSourceService(db)
        self._provider_factory = provider_factory or default_provider_factory()
        self._secret_store = secret_store or EncryptedDatabaseSecretStore(db)

    def save_credentials(
        self,
        data_source_id: UUID,
        values: dict[str, str],
        *,
        actor_user_id: int,
    ) -> CompanyDataSource:
        source, record, context = self._source_context(data_source_id)
        try:
            secret = ProviderSecret(values)
        except ValueError as exc:
            raise app_error("VALIDATION_ERROR", message="Las credenciales no son válidas.") from exc
        self._secret_store.save(context, secret, actor_user_id=actor_user_id)
        record.credential_reference = f"provider-credential:{source.id}"
        record.status = DataSourceStatus.PENDING.value
        record.last_connection_checked_at = None
        record.last_sync_cursor = None
        self._db.commit()
        return self._sources.get_source(data_source_id)

    def revoke_credentials(self, data_source_id: UUID) -> CompanyDataSource:
        source, record, context = self._source_context(data_source_id)
        self._secret_store.revoke(context)
        record.credential_reference = None
        record.status = DataSourceStatus.DISABLED.value
        record.last_connection_checked_at = None
        record.last_sync_cursor = None
        self._db.commit()
        return self._sources.get_source(source.id)

    async def test_connection(
        self,
        data_source_id: UUID,
        *,
        actor_user_id: int,
        correlation_id: str | None = None,
    ) -> ProviderOperationResult:
        source, record, context = self._source_context(data_source_id, correlation_id=correlation_id)
        run = self._new_run(
            source,
            operation=ProviderOperation.CONNECTION_TEST,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        try:
            secret = self._required_secret(context)
            adapter = self._provider_factory.resolve_connection(context)
            await adapter.test_connection(context, secret)
        except Exception as exc:
            completed_at = self._now()
            record.status = DataSourceStatus.FAILED.value
            record.last_connection_checked_at = completed_at
            self._finish_failure(run, exc, completed_at)
            self._db.commit()
            raise

        completed_at = self._now()
        record.status = DataSourceStatus.ACTIVE.value
        record.last_connection_checked_at = completed_at
        self._finish_success(run, completed_at=completed_at)
        self._db.commit()
        return self._result(run)

    async def sync_parties(
        self,
        data_source_id: UUID,
        *,
        actor_user_id: int,
        page_size: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderOperationResult:
        source, record, context = self._source_context(data_source_id, correlation_id=correlation_id)
        if source.status is not DataSourceStatus.ACTIVE:
            raise app_error(
                "CONFLICT",
                message="La fuente debe tener una conexión activa antes de sincronizar.",
            )
        run = self._new_run(
            source,
            operation=ProviderOperation.SYNC_PARTIES,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            cursor_before=source.last_sync_cursor,
        )
        try:
            secret = self._required_secret(context)
            adapter = self._provider_factory.resolve_party_sync(context)
            page = await adapter.fetch_parties(
                context,
                secret,
                cursor=source.last_sync_cursor,
                page_size=page_size,
            )
            for party in page.items:
                self._sources.upsert_provider_party(
                    source.id, party, actor_user_id=actor_user_id
                )
        except Exception as exc:
            completed_at = self._now()
            record.status = DataSourceStatus.FAILED.value
            self._finish_failure(run, exc, completed_at)
            self._db.commit()
            raise

        completed_at = self._now()
        record.status = DataSourceStatus.ACTIVE.value
        record.last_synced_at = completed_at
        record.last_sync_cursor = page.next_cursor
        self._finish_success(
            run,
            completed_at=completed_at,
            processed_records=len(page.items),
            cursor_after=page.next_cursor,
        )
        self._db.commit()
        return self._result(run)

    def list_runs(self, data_source_id: UUID) -> list[ProviderOperationResult]:
        self._sources.get_source(data_source_id)
        records = self._db.scalars(
            select(ProviderSyncRunRecord)
            .where(ProviderSyncRunRecord.data_source_id == str(data_source_id))
            .order_by(ProviderSyncRunRecord.completed_at.desc(), ProviderSyncRunRecord.id.desc())
        )
        return [self._result(record) for record in records]

    def _source_context(
        self, data_source_id: UUID, *, correlation_id: str | None = None
    ) -> tuple[CompanyDataSource, CompanyDataSourceRecord, ProviderContext]:
        source = self._sources.get_source(data_source_id)
        if source.provider_id is None:
            raise app_error(
                "CONFLICT",
                message="La fuente no está configurada para un proveedor externo.",
            )
        record = self._db.get(CompanyDataSourceRecord, str(data_source_id))
        assert record is not None
        return (
            source,
            record,
            ProviderContext(
                tenant_id=source.tenant_id,
                company_id=source.company_id,
                data_source_id=source.id,
                provider=source.provider_id,
                correlation_id=correlation_id,
            ),
        )

    def _required_secret(self, context: ProviderContext) -> ProviderSecret:
        secret = self._secret_store.get(context)
        if secret is None:
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                message="La fuente no tiene credenciales activas para el proveedor.",
                details={"provider": context.provider},
            )
        return secret

    def _new_run(
        self,
        source: CompanyDataSource,
        *,
        operation: ProviderOperation,
        actor_user_id: int,
        correlation_id: str | None,
        cursor_before: str | None = None,
    ) -> ProviderSyncRunRecord:
        run = ProviderSyncRunRecord(
            id=str(uuid4()),
            data_source_id=str(source.id),
            company_id=str(source.company_id),
            provider_id=source.provider_id or "",
            operation=operation.value,
            status=ProviderRunStatus.FAILED.value,
            cursor_before=cursor_before,
            processed_records=0,
            correlation_id=correlation_id,
            created_by_user_id=actor_user_id,
        )
        self._db.add(run)
        return run

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _finish_success(
        run: ProviderSyncRunRecord,
        *,
        completed_at: datetime,
        processed_records: int = 0,
        cursor_after: str | None = None,
    ) -> None:
        run.status = ProviderRunStatus.SUCCEEDED.value
        run.processed_records = processed_records
        run.cursor_after = cursor_after
        run.error_code = None
        run.completed_at = completed_at

    @staticmethod
    def _finish_failure(
        run: ProviderSyncRunRecord, exc: Exception, completed_at: datetime
    ) -> None:
        run.status = ProviderRunStatus.FAILED.value
        run.error_code = exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"
        run.completed_at = completed_at

    @staticmethod
    def _result(record: ProviderSyncRunRecord) -> ProviderOperationResult:
        assert record.completed_at is not None
        return ProviderOperationResult(
            id=UUID(record.id),
            data_source_id=UUID(record.data_source_id),
            provider_id=record.provider_id,
            operation=record.operation,
            status=record.status,
            processed_records=record.processed_records,
            cursor_before=record.cursor_before,
            cursor_after=record.cursor_after,
            error_code=record.error_code,
            correlation_id=record.correlation_id,
            completed_at=record.completed_at,
        )
