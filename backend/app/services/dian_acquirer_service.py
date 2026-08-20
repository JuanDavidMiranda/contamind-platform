"""Caso de uso controlado para completar datos de adquiriente con DIAN."""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.data_sources.models import ConnectionMode, DataSourceKind, DataSourceStatus
from app.models.data_source import CompanyDataSourceRecord
from app.models.dian import DianAcquirerLookupRecord
from app.providers.canonical import ProviderContext, ProviderKind
from app.providers.credential_store import EncryptedDatabaseSecretStore
from app.providers.factory import ProviderFactory
from app.providers.runtime import default_provider_factory
from app.shared.errors import AppError, app_error


_DIAN_ACQUIRER_CONNECTOR_ID = "dian_get_acquirer"


class DianAcquirerLookup:
    """Resultado efímero; solo se expone a quien realizó la consulta autorizada."""

    def __init__(self, *, id: UUID, name: str, email: str | None) -> None:
        self.id = id
        self.name = name
        self.email = email


class DianAcquirerService:
    """Consulta de a uno para emisión de factura, sin persistir datos personales."""

    def __init__(
        self,
        db: Session,
        *,
        provider_factory: ProviderFactory | None = None,
        secret_store: EncryptedDatabaseSecretStore | None = None,
    ) -> None:
        self._db = db
        self._provider_factory = provider_factory or default_provider_factory()
        self._secret_store = secret_store or EncryptedDatabaseSecretStore(db)

    async def lookup(
        self,
        *,
        company_id: UUID,
        data_source_id: UUID,
        actor_user_id: int,
        document_type: str,
        document_number: str,
        correlation_id: str | None = None,
    ) -> DianAcquirerLookup:
        source = self._dian_source(company_id, data_source_id)
        context = ProviderContext(
            tenant_id=UUID(source.tenant_id),
            company_id=company_id,
            data_source_id=data_source_id,
            provider=ProviderKind.DIAN,
            correlation_id=correlation_id,
        )
        lookup_id = uuid4()
        audit = DianAcquirerLookupRecord(
            id=str(lookup_id),
            data_source_id=str(data_source_id),
            company_id=str(company_id),
            actor_user_id=actor_user_id,
            document_type=document_type,
            document_number_hmac=self._document_hmac(document_number),
            status="failed",
            correlation_id=correlation_id,
        )
        self._db.add(audit)
        try:
            secret = self._secret_store.get(context)
            if secret is None:
                raise app_error(
                    "PROVIDER_AUTH_FAILED",
                    message="Configura las credenciales DIAN antes de consultar un adquiriente.",
                    details={"provider": ProviderKind.DIAN},
                )
            adapter = self._provider_factory.resolve_fiscal(context)
            party = await adapter.get_acquirer_information(
                context, secret, document_type, document_number
            )
        except AppError as exc:
            audit.error_code = exc.code
            self._db.commit()
            raise
        except Exception:
            audit.error_code = "INTERNAL_ERROR"
            self._db.commit()
            raise

        audit.status = "succeeded"
        source.status = DataSourceStatus.ACTIVE.value
        source.last_connection_checked_at = datetime.now(UTC)
        self._db.commit()
        return DianAcquirerLookup(id=lookup_id, name=party.name, email=party.email)

    def _dian_source(
        self, company_id: UUID, data_source_id: UUID
    ) -> CompanyDataSourceRecord:
        source = self._db.get(CompanyDataSourceRecord, str(data_source_id))
        if source is None or source.company_id != str(company_id):
            raise app_error("NOT_FOUND", message="Fuente DIAN no encontrada para esta empresa.")
        if (
            source.connector_id != _DIAN_ACQUIRER_CONNECTOR_ID
            or source.provider_id != ProviderKind.DIAN.value
            or source.kind != DataSourceKind.FISCAL_AUTHORITY.value
            or source.mode != ConnectionMode.FISCAL_SERVICE.value
        ):
            raise app_error(
                "CONFLICT",
                message="La fuente no está configurada como servicio fiscal DIAN.",
            )
        if source.status == DataSourceStatus.DISABLED.value:
            raise app_error("CONFLICT", message="La fuente DIAN está deshabilitada.")
        return source

    @staticmethod
    def _document_hmac(document_number: str) -> str:
        from app.config.settings import settings

        assert settings.AUTH_SECRET_KEY is not None
        return hmac.new(
            settings.AUTH_SECRET_KEY.encode("utf-8"),
            document_number.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
