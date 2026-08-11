"""Ciclo de vida de conexiones externas y cola persistente de sincronizaci\u00f3n."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.data_sources.models import (
    CompanyDataSource,
    DataSourceStatus,
    ProviderOperation,
    ProviderOperationResult,
    ProviderRunStatus,
    ProviderSyncJobResult,
    ProviderSyncJobStatus,
)
from app.models.data_source import (
    CompanyDataSourceRecord,
    ProviderSyncJobRecord,
    ProviderSyncRunRecord,
)
from app.providers.canonical import ProviderContext
from app.providers.credential_store import EncryptedDatabaseSecretStore
from app.providers.factory import ProviderFactory
from app.providers.runtime import default_provider_factory
from app.providers.secrets import ProviderSecret
from app.services.data_source_service import DataSourceService
from app.shared.errors import AppError, app_error


_RETRYABLE_PROVIDER_ERRORS = frozenset(
    {
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_UNREACHABLE",
        "PROVIDER_ERROR",
        "SERVICE_UNAVAILABLE",
    }
)


class ProviderConnectionService:
    """Coordina fuentes, secretos, adaptadores y trabajos sin filtrar secretos."""

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
            raise app_error("VALIDATION_ERROR", message="Las credenciales no son v\u00e1lidas.") from exc
        self._secret_store.save(context, secret, actor_user_id=actor_user_id)
        self._cancel_active_sync_jobs(data_source_id)
        record.credential_reference = f"provider-credential:{source.id}"
        record.status = DataSourceStatus.PENDING.value
        record.last_connection_checked_at = None
        record.last_sync_cursor = None
        self._db.commit()
        return self._sources.get_source(data_source_id)

    def revoke_credentials(self, data_source_id: UUID) -> CompanyDataSource:
        source, record, context = self._source_context(data_source_id)
        self._secret_store.revoke(context)
        self._cancel_active_sync_jobs(data_source_id)
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

    def enqueue_party_sync(
        self,
        data_source_id: UUID,
        *,
        actor_user_id: int,
        page_size: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderSyncJobResult:
        """Encola una sincronizaci\u00f3n sin mantener abierta la solicitud HTTP."""

        source, _, _ = self._source_context(data_source_id, correlation_id=correlation_id)
        if source.status is not DataSourceStatus.ACTIVE:
            raise app_error(
                "CONFLICT",
                message="La fuente debe tener una conexi\u00f3n activa antes de sincronizar.",
            )

        active_job = self._db.scalar(
            select(ProviderSyncJobRecord.id).where(
                ProviderSyncJobRecord.active_data_source_id == str(data_source_id)
            )
        )
        if active_job is not None:
            raise app_error(
                "CONFLICT",
                message="Ya existe una sincronizaci\u00f3n activa para esta fuente.",
            )

        now = self._now()
        job = ProviderSyncJobRecord(
            id=str(uuid4()),
            data_source_id=str(source.id),
            active_data_source_id=str(source.id),
            company_id=str(source.company_id),
            provider_id=source.provider_id or "",
            status=ProviderSyncJobStatus.QUEUED.value,
            page_size=page_size,
            cursor=source.last_sync_cursor,
            processed_records=0,
            pages_processed=0,
            attempt_count=0,
            max_attempts=settings.PROVIDER_SYNC_MAX_ATTEMPTS,
            available_at=now,
            correlation_id=correlation_id,
            created_by_user_id=actor_user_id,
        )
        self._db.add(job)
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise app_error(
                "CONFLICT",
                message="Ya existe una sincronizaci\u00f3n activa para esta fuente.",
            ) from exc
        return self._job_result(job)

    async def process_next_sync_job(self) -> ProviderSyncJobResult | None:
        """Reclama y procesa a lo sumo una p\u00e1gina de un trabajo disponible.

        El worker invoca este m\u00e9todo repetidamente. Cada p\u00e1gina se confirma
        antes de continuar, por lo que un reinicio conserva el cursor y evita
        repetir p\u00e1ginas ya persistidas.
        """

        job = self._claim_next_sync_job()
        if job is None:
            return None

        source: CompanyDataSource | None = None
        source_record: CompanyDataSourceRecord | None = None
        run: ProviderSyncRunRecord | None = None
        try:
            source, source_record, context = self._source_context(
                UUID(job.data_source_id), correlation_id=job.correlation_id
            )
            run = self._new_run(
                source,
                operation=ProviderOperation.SYNC_PARTIES,
                actor_user_id=job.created_by_user_id,
                correlation_id=job.correlation_id,
                cursor_before=job.cursor,
            )
            if source.status is not DataSourceStatus.ACTIVE:
                raise app_error(
                    "CONFLICT",
                    message="La fuente debe tener una conexi\u00f3n activa antes de sincronizar.",
                )
            secret = self._required_secret(context)
            adapter = self._provider_factory.resolve_party_sync(context)
            page = await adapter.fetch_parties(
                context,
                secret,
                cursor=job.cursor,
                page_size=job.page_size,
            )
            for party in page.items:
                self._sources.upsert_provider_party(
                    source.id, party, actor_user_id=job.created_by_user_id
                )
        except Exception as exc:
            completed_at = self._now()
            if run is not None:
                self._finish_failure(run, exc, completed_at)
            job_values, fail_source = self._failure_job_values(job, exc, completed_at)
            with self._db.no_autoflush:
                finalized = self._db.execute(
                    update(ProviderSyncJobRecord)
                    .where(
                        ProviderSyncJobRecord.id == job.id,
                        ProviderSyncJobRecord.status == ProviderSyncJobStatus.RUNNING.value,
                    )
                    .values(**job_values)
                    .execution_options(synchronize_session=False)
                )
            if not finalized.rowcount:
                self._db.rollback()
                current = self._db.get(ProviderSyncJobRecord, job.id)
                assert current is not None
                return self._job_result(current)
            if (
                fail_source
                and source_record is not None
                and source_record.status == DataSourceStatus.ACTIVE.value
            ):
                source_record.status = DataSourceStatus.FAILED.value
            self._db.commit()
            current = self._db.get(ProviderSyncJobRecord, job.id)
            assert current is not None
            return self._job_result(current)

        completed_at = self._now()
        assert source_record is not None
        assert run is not None
        job_values: dict[str, object] = {
            "processed_records": job.processed_records + len(page.items),
            "pages_processed": job.pages_processed + 1,
            "attempt_count": 0,
            "cursor": page.next_cursor,
            "error_code": None,
            "lease_expires_at": None,
        }
        if page.next_cursor is None:
            job_values.update(
                status=ProviderSyncJobStatus.SUCCEEDED.value,
                active_data_source_id=None,
                completed_at=completed_at,
            )
        else:
            job_values.update(
                status=ProviderSyncJobStatus.QUEUED.value,
                available_at=completed_at,
            )
        with self._db.no_autoflush:
            finalized = self._db.execute(
                update(ProviderSyncJobRecord)
                .where(
                    ProviderSyncJobRecord.id == job.id,
                    ProviderSyncJobRecord.status == ProviderSyncJobStatus.RUNNING.value,
                )
                .values(**job_values)
                .execution_options(synchronize_session=False)
            )
        if not finalized.rowcount:
            self._db.rollback()
            current = self._db.get(ProviderSyncJobRecord, job.id)
            assert current is not None
            return self._job_result(current)
        source_record.status = DataSourceStatus.ACTIVE.value
        source_record.last_synced_at = completed_at
        source_record.last_sync_cursor = page.next_cursor
        self._finish_success(
            run,
            completed_at=completed_at,
            processed_records=len(page.items),
            cursor_after=page.next_cursor,
        )
        self._db.commit()
        current = self._db.get(ProviderSyncJobRecord, job.id)
        assert current is not None
        return self._job_result(current)

    def get_sync_job(self, data_source_id: UUID, job_id: UUID) -> ProviderSyncJobResult:
        record = self._db.scalar(
            select(ProviderSyncJobRecord).where(
                ProviderSyncJobRecord.id == str(job_id),
                ProviderSyncJobRecord.data_source_id == str(data_source_id),
            )
        )
        if record is None:
            raise app_error("NOT_FOUND", message="Trabajo de sincronizaci\u00f3n no encontrado.")
        return self._job_result(record)

    def list_sync_jobs(self, data_source_id: UUID) -> list[ProviderSyncJobResult]:
        self._sources.get_source(data_source_id)
        records = self._db.scalars(
            select(ProviderSyncJobRecord)
            .where(ProviderSyncJobRecord.data_source_id == str(data_source_id))
            .order_by(ProviderSyncJobRecord.created_at.desc(), ProviderSyncJobRecord.id.desc())
        )
        return [self._job_result(record) for record in records]

    async def sync_parties(
        self,
        data_source_id: UUID,
        *,
        actor_user_id: int,
        page_size: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderOperationResult:
        """Compatibilidad interna para una sincronizaci\u00f3n directa de una p\u00e1gina.

        La ruta p\u00fablica usa ``enqueue_party_sync``. Este m\u00e9todo se conserva para
        consumidores internos ya existentes y para diagn\u00f3sticos controlados.
        """

        source, record, context = self._source_context(data_source_id, correlation_id=correlation_id)
        if source.status is not DataSourceStatus.ACTIVE:
            raise app_error(
                "CONFLICT",
                message="La fuente debe tener una conexi\u00f3n activa antes de sincronizar.",
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
                self._sources.upsert_provider_party(source.id, party, actor_user_id=actor_user_id)
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

    def _claim_next_sync_job(self) -> ProviderSyncJobRecord | None:
        now = self._now()
        claimable = self._claimable_job_filter(now)
        for _ in range(5):
            candidate = self._db.scalar(
                select(ProviderSyncJobRecord)
                .where(claimable)
                .order_by(ProviderSyncJobRecord.available_at, ProviderSyncJobRecord.created_at)
                .limit(1)
            )
            if candidate is None:
                return None
            claimed = self._db.execute(
                update(ProviderSyncJobRecord)
                .where(ProviderSyncJobRecord.id == candidate.id, self._claimable_job_filter(now))
                .values(
                    status=ProviderSyncJobStatus.RUNNING.value,
                    attempt_count=ProviderSyncJobRecord.attempt_count + 1,
                    started_at=case(
                        (ProviderSyncJobRecord.started_at.is_(None), now),
                        else_=ProviderSyncJobRecord.started_at,
                    ),
                    lease_expires_at=now
                    + timedelta(seconds=settings.PROVIDER_SYNC_LEASE_SECONDS),
                )
            )
            if claimed.rowcount:
                self._db.commit()
                return self._db.get(ProviderSyncJobRecord, candidate.id)
            self._db.rollback()
        return None

    @staticmethod
    def _claimable_job_filter(now: datetime):
        return or_(
            and_(
                ProviderSyncJobRecord.status.in_(
                    (ProviderSyncJobStatus.QUEUED.value, ProviderSyncJobStatus.RETRYING.value)
                ),
                ProviderSyncJobRecord.available_at <= now,
            ),
            and_(
                ProviderSyncJobRecord.status == ProviderSyncJobStatus.RUNNING.value,
                ProviderSyncJobRecord.lease_expires_at.is_not(None),
                ProviderSyncJobRecord.lease_expires_at <= now,
            ),
        )

    def _failure_job_values(
        self,
        job: ProviderSyncJobRecord,
        exc: Exception,
        completed_at: datetime,
    ) -> tuple[dict[str, object], bool]:
        error_code = self._error_code(exc)
        if error_code in _RETRYABLE_PROVIDER_ERRORS and job.attempt_count < job.max_attempts:
            return (
                {
                    "status": ProviderSyncJobStatus.RETRYING.value,
                    "available_at": completed_at
                    + timedelta(seconds=self._retry_delay_seconds(job.attempt_count)),
                    "error_code": error_code,
                    "lease_expires_at": None,
                },
                False,
            )
        return (
            {
                "status": ProviderSyncJobStatus.FAILED.value,
                "active_data_source_id": None,
                "completed_at": completed_at,
                "error_code": error_code,
                "lease_expires_at": None,
            },
            True,
        )

    @staticmethod
    def _error_code(exc: Exception) -> str:
        return exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"

    @staticmethod
    def _retry_delay_seconds(attempt_count: int) -> int:
        exponential_delay = settings.PROVIDER_SYNC_RETRY_BASE_SECONDS * 2 ** max(
            attempt_count - 1, 0
        )
        return min(exponential_delay, settings.PROVIDER_SYNC_RETRY_MAX_SECONDS)

    def _cancel_active_sync_jobs(self, data_source_id: UUID) -> None:
        now = self._now()
        records = list(
            self._db.scalars(
                select(ProviderSyncJobRecord).where(
                    ProviderSyncJobRecord.active_data_source_id == str(data_source_id)
                )
            )
        )
        for record in records:
            record.status = ProviderSyncJobStatus.CANCELLED.value
            record.active_data_source_id = None
            record.lease_expires_at = None
            record.completed_at = now

    def _source_context(
        self, data_source_id: UUID, *, correlation_id: str | None = None
    ) -> tuple[CompanyDataSource, CompanyDataSourceRecord, ProviderContext]:
        source = self._sources.get_source(data_source_id)
        if source.provider_id is None:
            raise app_error(
                "CONFLICT",
                message="La fuente no est\u00e1 configurada para un proveedor externo.",
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
        actor_user_id: int | None,
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
        run.error_code = ProviderConnectionService._error_code(exc)
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

    @staticmethod
    def _job_result(record: ProviderSyncJobRecord) -> ProviderSyncJobResult:
        return ProviderSyncJobResult(
            id=UUID(record.id),
            data_source_id=UUID(record.data_source_id),
            provider_id=record.provider_id,
            status=record.status,
            page_size=record.page_size,
            processed_records=record.processed_records,
            pages_processed=record.pages_processed,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            cursor=record.cursor,
            error_code=record.error_code,
            correlation_id=record.correlation_id,
            available_at=record.available_at,
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )
