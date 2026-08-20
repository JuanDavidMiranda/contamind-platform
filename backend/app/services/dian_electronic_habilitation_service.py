"""Flujo durable de habilitación DIAN para software propio por empresa.

El servicio gestiona únicamente la preparación y el envío de pruebas al
servicio oficial de habilitación. No habilita producción ni reintenta a ciegas
una transmisión cuyo resultado sea ambiguo.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Callable
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from lxml import etree
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.config.features import FEATURE_DIAN_ELECTRONIC_HABILITATION, is_enabled
from app.data_sources.models import ConnectionMode, DataSourceKind, DataSourceStatus
from app.integrations.dian.artifacts import DianArtifactCipher
from app.integrations.dian.credentials import DianTechnicalCredentials
from app.integrations.dian.gateway import (
    DianGatewayError,
    DianGatewayResponse,
    DianHabilitationGateway,
)
from app.models.data_source import CompanyDataSourceRecord
from app.models.dian_electronic import (
    DianElectronicDocumentRecord,
    DianElectronicDocumentStatusEventRecord,
    DianElectronicOutboxJobRecord,
    DianElectronicSubmissionRecord,
    DianFiscalProfileRecord,
    DianNumberingRangeRecord,
)
from app.models.organization import CompanyRecord
from app.providers.canonical import ProviderContext, ProviderKind
from app.providers.credential_store import EncryptedDatabaseSecretStore
from app.providers.secrets import ProviderSecret
from app.shared.errors import app_error


_HABILITATION_CONNECTOR_ID = "dian_electronic_habilitation"
_HABILITATION_SOURCE_NAME = "DIAN · Facturación electrónica (habilitación)"
_MAX_UPLOAD_BYTES = 10_000_000
_MAX_XML_BYTES = 8_000_000
_MAX_ATTEMPTS = 3
_LEASE_SECONDS = 600
_READY_JOB_STATUSES = frozenset({"queued", "retrying"})
_STATUS_IN_PROGRESS = frozenset({"processing", "queued", "sending"})
_DOCUMENT_ROOTS = {
    "invoice": (
        "Invoice",
        "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    ),
    "credit_note": (
        "CreditNote",
        "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    ),
    "debit_note": (
        "DebitNote",
        "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
    ),
}
_CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
_CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"
_TECHNICAL_CREDENTIAL_FIELDS = frozenset(
    {"software_id", "software_password", "certificate_pfx_base64", "certificate_password"}
)
_MAX_TECHNICAL_CREDENTIAL_LENGTH = 4_096
_MAX_CERTIFICATE_PFX_BASE64_LENGTH = 1_000_000
_PRESERVED_PROFILE_TECHNICAL_FIELDS = frozenset(
    {
        "software_test_set_id",
        "signature_policy_identifier",
        "signature_policy_digest_base64",
        "signature_policy_qualifier_url",
    }
)


@dataclass(frozen=True)
class DianHabilitationProfile:
    id: UUID
    company_id: UUID
    data_source_id: UUID | None
    status: str
    integration_enabled: bool
    software_test_set_id: str | None
    legal_name: str
    nit: str
    check_digit: str
    email: str
    address: str
    city_code: str
    city_name: str
    department_code: str
    department_name: str
    country_code: str
    tax_responsibilities: tuple[str, ...]
    phone: str | None
    tax_regime: str | None
    credential_configured: bool
    active_numbering_ranges: int
    missing_requirements: tuple[str, ...]


@dataclass(frozen=True)
class DianNumberingRange:
    id: UUID
    profile_id: UUID
    prefix: str
    resolution_number: str
    resolution_date: date
    valid_from: date
    valid_to: date
    range_from: int
    range_to: int
    next_number: int
    active: bool


@dataclass(frozen=True)
class DianElectronicDocument:
    id: UUID
    company_id: UUID
    corrects_document_id: UUID | None
    document_number: str
    document_type: str
    prefix: str
    consecutive: int
    issue_date: date
    currency_code: str
    payable_amount: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DianSubmissionEvent:
    id: UUID
    status: str
    code: str | None
    message: str | None
    created_at: datetime


@dataclass(frozen=True)
class _DianNumberReservation:
    """Reserva normal o corrección segura de un consecutivo DIAN."""

    numbering_range: DianNumberingRangeRecord
    corrects_document: DianElectronicDocumentRecord | None


GatewayFactory = Callable[[], DianHabilitationGateway]


class DianElectronicHabilitationService:
    """Casos de uso de facturación electrónica restringidos a habilitación."""

    def __init__(
        self,
        db: Session,
        *,
        secret_store: EncryptedDatabaseSecretStore | None = None,
        artifact_cipher: DianArtifactCipher | None = None,
        gateway_factory: GatewayFactory = DianHabilitationGateway,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._secret_store = secret_store or EncryptedDatabaseSecretStore(db)
        self._artifact_cipher = artifact_cipher
        self._gateway_factory = gateway_factory
        self._now = now or (lambda: datetime.now(UTC).replace(tzinfo=None))

    def upsert_profile(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
        legal_name: str,
        nit: str,
        check_digit: str,
        email: str,
        address: str,
        city_code: str,
        city_name: str,
        department_code: str,
        department_name: str,
        tax_responsibilities: list[str],
        phone: str | None = None,
        tax_regime: str | None = None,
        software_test_set_id: str | None = None,
        signature_policy_identifier: str | None = None,
        signature_policy_digest_base64: str | None = None,
        signature_policy_qualifier_url: str | None = None,
    ) -> DianHabilitationProfile:
        company = self._company(company_id)
        values = self._normalized_profile_values(
            legal_name=legal_name,
            nit=nit,
            check_digit=check_digit,
            email=email,
            address=address,
            city_code=city_code,
            city_name=city_name,
            department_code=department_code,
            department_name=department_name,
            tax_responsibilities=tax_responsibilities,
            phone=phone,
            tax_regime=tax_regime,
            software_test_set_id=software_test_set_id,
            signature_policy_identifier=signature_policy_identifier,
            signature_policy_digest_base64=signature_policy_digest_base64,
            signature_policy_qualifier_url=signature_policy_qualifier_url,
        )
        profile = self._db.scalar(
            select(DianFiscalProfileRecord).where(DianFiscalProfileRecord.company_id == str(company_id))
        )
        if profile is None:
            source = self._get_or_create_habilitation_source(company, actor_user_id)
            profile = DianFiscalProfileRecord(
                id=str(uuid4()),
                tenant_id=company.tenant_id,
                company_id=str(company_id),
                data_source_id=source.id,
                environment="habilitation",
                status="draft",
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
                **values,
            )
            self._db.add(profile)
        else:
            for name, value in values.items():
                # La interfaz puede actualizar datos fiscales sin conocer ni
                # volver a enviar los parámetros de habilitación ya aprobados.
                # Un valor opcional omitido no debe borrar el TestSetId ni la
                # política de firma de una empresa lista para pruebas.
                if name in _PRESERVED_PROFILE_TECHNICAL_FIELDS and value is None:
                    continue
                setattr(profile, name, value)
            if profile.data_source_id is None:
                profile.data_source_id = self._get_or_create_habilitation_source(company, actor_user_id).id
            profile.updated_by_user_id = actor_user_id
        self._db.flush()
        profile.status = self._profile_status(profile)
        self._db.commit()
        self._db.refresh(profile)
        return self._profile_view(profile)

    def get_profile(self, company_id: UUID) -> DianHabilitationProfile | None:
        profile = self._db.scalar(
            select(DianFiscalProfileRecord).where(DianFiscalProfileRecord.company_id == str(company_id))
        )
        if profile is not None and profile.status == "draft":
            next_status = self._profile_status(profile)
            if next_status != profile.status:
                profile.status = next_status
                self._db.commit()
                self._db.refresh(profile)
        return self._profile_view(profile) if profile else None

    def save_technical_credentials(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
        values: dict[str, str],
    ) -> DianHabilitationProfile:
        """Guarda únicamente el material técnico de habilitación, cifrado.

        La validación se hace antes de persistir para que un PFX vencido o
        inválido no deje una fuente aparentemente configurada. Los valores no
        salen de esta capa ni se incluyen en eventos, respuestas o bitácoras.
        """

        profile = self._required_profile(company_id)
        if profile.data_source_id is None:
            raise app_error("CONFLICT", message="La fuente DIAN de habilitación no está disponible.")
        try:
            if set(values) != _TECHNICAL_CREDENTIAL_FIELDS or any(
                not isinstance(value, str)
                or not value
                or len(value)
                > (
                    _MAX_CERTIFICATE_PFX_BASE64_LENGTH
                    if name == "certificate_pfx_base64"
                    else _MAX_TECHNICAL_CREDENTIAL_LENGTH
                )
                for name, value in values.items()
            ):
                raise ValueError("El material técnico DIAN no tiene el formato esperado.")
            DianTechnicalCredentials.from_secret_values(values)
            secret = ProviderSecret(values)
        except ValueError as exc:
            raise app_error(
                "VALIDATION_ERROR",
                message="Las credenciales DIAN deben incluir un certificado PFX RSA vigente.",
            ) from exc
        source = self._db.get(CompanyDataSourceRecord, profile.data_source_id)
        if source is None or source.company_id != str(company_id):
            raise app_error("CONFLICT", message="La fuente DIAN de habilitación no está disponible.")
        context = ProviderContext(
            tenant_id=UUID(profile.tenant_id),
            company_id=company_id,
            data_source_id=UUID(source.id),
            provider=ProviderKind.DIAN,
        )
        self._secret_store.save(context, secret, actor_user_id=actor_user_id)
        source.credential_reference = f"provider-credential:{source.id}"
        source.status = DataSourceStatus.PENDING.value
        source.last_connection_checked_at = None
        profile.updated_by_user_id = actor_user_id
        self._db.flush()
        profile.status = self._profile_status(profile)
        self._db.commit()
        self._db.refresh(profile)
        return self._profile_view(profile)

    def save_habilitation_parameters(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
        software_test_set_id: str,
        signature_policy_identifier: str,
        signature_policy_digest_base64: str,
        signature_policy_qualifier_url: str | None = None,
    ) -> DianHabilitationProfile:
        """Guarda los parámetros públicos asignados por DIAN sin tocar el perfil.

        Se separan del formulario fiscal para que una actualización posterior no
        borre ni obligue a reingresar datos de la empresa. No devuelve los
        parámetros, porque basta con informar que quedaron configurados.
        """

        profile = self._required_profile(company_id)
        values = self._normalized_habilitation_parameters(
            software_test_set_id=software_test_set_id,
            signature_policy_identifier=signature_policy_identifier,
            signature_policy_digest_base64=signature_policy_digest_base64,
            signature_policy_qualifier_url=signature_policy_qualifier_url,
        )
        if not values["software_test_set_id"] or not values["signature_policy_identifier"]:
            raise app_error(
                "VALIDATION_ERROR",
                message="Completa el TestSetId y la política de firma de habilitación.",
            )
        for name, value in values.items():
            setattr(profile, name, value)
        profile.updated_by_user_id = actor_user_id
        self._db.flush()
        profile.status = self._profile_status(profile)
        self._db.commit()
        self._db.refresh(profile)
        return self._profile_view(profile)

    def revoke_technical_credentials(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
    ) -> DianHabilitationProfile:
        """Revoca las credenciales técnicas y deja la habilitación cerrada."""

        profile = self._required_profile(company_id)
        if profile.data_source_id is None:
            raise app_error("CONFLICT", message="La fuente DIAN de habilitación no está disponible.")
        source = self._db.get(CompanyDataSourceRecord, profile.data_source_id)
        if source is None or source.company_id != str(company_id):
            raise app_error("CONFLICT", message="La fuente DIAN de habilitación no está disponible.")
        context = ProviderContext(
            tenant_id=UUID(profile.tenant_id),
            company_id=company_id,
            data_source_id=UUID(source.id),
            provider=ProviderKind.DIAN,
        )
        self._secret_store.revoke(context)
        source.credential_reference = None
        source.status = DataSourceStatus.DISABLED.value
        source.last_connection_checked_at = None
        profile.updated_by_user_id = actor_user_id
        self._db.flush()
        profile.status = self._profile_status(profile)
        self._db.commit()
        self._db.refresh(profile)
        return self._profile_view(profile)

    def create_numbering_range(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
        prefix: str,
        resolution_number: str,
        resolution_date: date,
        valid_from: date,
        valid_to: date,
        range_from: int,
        range_to: int,
    ) -> DianNumberingRange:
        profile = self._required_profile(company_id)
        normalized_prefix = self._required_text(prefix, "prefix", maximum=20).upper()
        normalized_resolution = self._required_text(
            resolution_number, "resolution_number", maximum=100
        )
        if not isinstance(resolution_date, date) or not isinstance(valid_from, date) or not isinstance(valid_to, date):
            raise app_error("VALIDATION_ERROR", message="Las fechas de numeración no son válidas.")
        if valid_to < valid_from or range_from < 1 or range_to < range_from:
            raise app_error("VALIDATION_ERROR", message="El rango de numeración no es válido.")
        for existing in self._db.scalars(
            select(DianNumberingRangeRecord).where(
                DianNumberingRangeRecord.profile_id == profile.id,
                DianNumberingRangeRecord.prefix == normalized_prefix,
                DianNumberingRangeRecord.active.is_(True),
            )
        ):
            existing.active = False
        record = DianNumberingRangeRecord(
            id=str(uuid4()),
            profile_id=profile.id,
            company_id=str(company_id),
            prefix=normalized_prefix,
            resolution_number=normalized_resolution,
            resolution_date=resolution_date,
            valid_from=valid_from,
            valid_to=valid_to,
            range_from=range_from,
            range_to=range_to,
            next_number=range_from,
            active=True,
            created_by_user_id=actor_user_id,
        )
        self._db.add(record)
        self._db.flush()
        profile.status = self._profile_status(profile)
        self._db.commit()
        self._db.refresh(record)
        return self._range_view(record)

    def list_numbering_ranges(self, company_id: UUID) -> list[DianNumberingRange]:
        self._company(company_id)
        records = self._db.scalars(
            select(DianNumberingRangeRecord)
            .where(DianNumberingRangeRecord.company_id == str(company_id))
            .order_by(DianNumberingRangeRecord.active.desc(), DianNumberingRangeRecord.created_at.desc())
        )
        return [self._range_view(record) for record in records]

    def create_signed_test_document(
        self,
        company_id: UUID,
        *,
        actor_user_id: int,
        file_name: str,
        content: bytes,
        prefix: str,
        consecutive: int,
        issue_date: date,
        currency_code: str,
        payable_amount: str,
        confirmed: bool,
        document_type: str = "invoice",
        correlation_id: str | None = None,
    ) -> DianElectronicDocument:
        """Registra y encola un ZIP ya firmado para el set de habilitación.

        La generación propia de UBL aún se conserva como paso de preparación;
        este caso permite probar la conexión con archivos de prueba validados
        por la empresa, sin que el sistema transmita XML sin firma.
        """

        if not confirmed:
            raise app_error("VALIDATION_ERROR", message="Confirma el envío de prueba antes de encolarlo.")
        if not is_enabled(FEATURE_DIAN_ELECTRONIC_HABILITATION):
            raise app_error(
                "DEPENDENCY_DISABLED",
                message="La integración DIAN está deshabilitada en este ambiente.",
            )
        profile = self._required_profile(company_id)
        missing = self._profile_missing_requirements(profile)
        if missing:
            raise app_error(
                "CONFLICT",
                message="Completa la habilitación DIAN antes de cargar una prueba.",
                details={"missing_requirements": sorted(missing)},
            )
        normalized_prefix = self._required_text(prefix, "prefix", maximum=20).upper()
        if not isinstance(consecutive, int) or consecutive < 1:
            raise app_error("VALIDATION_ERROR", message="El consecutivo de prueba no es válido.")
        if not isinstance(issue_date, date):
            raise app_error("VALIDATION_ERROR", message="La fecha de emisión no es válida.")
        normalized_currency = self._required_text(currency_code, "currency_code", maximum=3).upper()
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise app_error("VALIDATION_ERROR", message="La moneda debe usar tres letras ISO.")
        normalized_amount = self._normalized_amount(payable_amount)
        normalized_document_type = self._normalized_document_type(document_type)
        document_number = f"{normalized_prefix}{consecutive}"
        xml_content = self._signed_xml_from_zip(
            file_name,
            content,
            expected_document_number=document_number,
            expected_document_type=normalized_document_type,
            expected_issue_date=issue_date,
            expected_currency_code=normalized_currency,
            expected_payable_amount=normalized_amount,
            expected_issuer_nit=profile.nit,
            expected_signature_policy_identifier=profile.signature_policy_identifier or "",
            expected_signature_policy_digest_base64=profile.signature_policy_digest_base64 or "",
        )
        reservation = self._reserve_number(
            profile=profile,
            company_id=company_id,
            prefix=normalized_prefix,
            consecutive=consecutive,
            issue_date=issue_date,
        )
        numbering = reservation.numbering_range
        corrected_document = reservation.corrects_document
        content_hash = hashlib.sha256(content).hexdigest()
        xml_hash = hashlib.sha256(xml_content).hexdigest()
        snapshot_hash = hashlib.sha256(
            json.dumps(
                {
                    "document_number": document_number,
                    "issue_date": issue_date.isoformat(),
                    "currency_code": normalized_currency,
                    "payable_amount": normalized_amount,
                    "zip_sha256": content_hash,
                    "range_id": numbering.id,
                    "corrects_document_id": corrected_document.id if corrected_document else None,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        artifact_cipher = self._cipher()
        document = DianElectronicDocumentRecord(
            id=str(uuid4()),
            profile_id=profile.id,
            company_id=str(company_id),
            source_invoice_id=None,
            corrects_document_id=corrected_document.id if corrected_document else None,
            document_type=normalized_document_type,
            prefix=normalized_prefix,
            consecutive=consecutive,
            document_number=document_number,
            issue_date=issue_date,
            currency_code=normalized_currency,
            payable_amount=normalized_amount,
            status="queued",
            source_snapshot_sha256=snapshot_hash,
            unsigned_xml_sha256=None,
            signed_xml_sha256=xml_hash,
            signed_xml_ciphertext=artifact_cipher.encrypt(xml_content),
            signed_zip_ciphertext=artifact_cipher.encrypt(content),
            artifact_key_version=artifact_cipher.key_version,
            created_by_user_id=actor_user_id,
        )
        self._db.add(document)
        self._db.flush()
        if corrected_document is None:
            self._add_status_event(
                document,
                previous_status=None,
                status="queued",
                code="DIAN_HABILITATION_TEST_QUEUED",
                message="Prueba firmada encolada para habilitación DIAN.",
                actor_user_id=actor_user_id,
            )
        else:
            self._add_status_event(
                document,
                previous_status=None,
                status="queued",
                code="DIAN_HABILITATION_CORRECTION_QUEUED",
                message="Corrección firmada encolada tras un rechazo definitivo de DIAN.",
                actor_user_id=actor_user_id,
            )
            self._add_status_event(
                corrected_document,
                previous_status=corrected_document.status,
                status=corrected_document.status,
                code="DIAN_HABILITATION_CORRECTION_LINKED",
                message=f"Se encoló la corrección trazable {document.id} con el mismo consecutivo.",
                actor_user_id=actor_user_id,
            )
        self._enqueue_job(
            document,
            operation="send_test_set",
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        profile.status = "in_habilitation"
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise app_error(
                "CONFLICT",
                message="El consecutivo DIAN ya fue reservado por otro documento.",
            ) from exc
        self._db.refresh(document)
        return self._document_view(document)

    def list_documents(self, company_id: UUID, *, limit: int = 50) -> list[DianElectronicDocument]:
        self._company(company_id)
        records = self._db.scalars(
            select(DianElectronicDocumentRecord)
            .where(DianElectronicDocumentRecord.company_id == str(company_id))
            .order_by(DianElectronicDocumentRecord.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
        return [self._document_view(record) for record in records]

    def list_document_events(
        self, company_id: UUID, document_id: UUID
    ) -> list[DianSubmissionEvent]:
        document = self._document_for_company(company_id, document_id)
        records = self._db.scalars(
            select(DianElectronicDocumentStatusEventRecord)
            .where(DianElectronicDocumentStatusEventRecord.document_id == document.id)
            .order_by(DianElectronicDocumentStatusEventRecord.created_at)
        )
        return [
            DianSubmissionEvent(
                id=UUID(record.id),
                status=record.status,
                code=record.code,
                message=record.message,
                created_at=record.created_at,
            )
            for record in records
        ]

    async def process_next_job(self) -> DianElectronicDocument | None:
        """Procesa una transmisión/consulta disponible desde un worker dedicado."""

        # La bandera también protege trabajos que hubieran quedado en cola antes
        # de desactivar DIAN; no basta validarla únicamente al momento de crear
        # el documento, porque eso permitiría una salida de red posterior.
        if not is_enabled(FEATURE_DIAN_ELECTRONIC_HABILITATION):
            return None
        job = self._claim_next_job()
        if job is None:
            return None
        document = self._db.get(DianElectronicDocumentRecord, job.document_id)
        if document is None:
            self._complete_job(job, status="failed", error_code="NOT_FOUND")
            self._db.commit()
            return None
        try:
            credentials = self._credentials_for_document(document)
            gateway = self._gateway_factory()
            if job.operation == "send_test_set":
                response = await gateway.send_test_set_async(
                    file_name=f"{document.document_number}.zip",
                    zipped_document=self._cipher().decrypt(document.signed_zip_ciphertext),
                    test_set_id=self._required_test_set_id(document.profile_id),
                    credentials=credentials,
                )
                self._record_gateway_response(document, job, response)
            elif job.operation == "check_status":
                track_id = self._latest_track_id(document.id)
                if track_id is None:
                    self._manual_review(
                        document,
                        job,
                        code="DIAN_TRACK_ID_MISSING",
                        message="DIAN no entregó un identificador de seguimiento; revisa el portal de habilitación.",
                    )
                else:
                    response = await gateway.get_status_zip(track_id=track_id, credentials=credentials)
                    self._record_gateway_response(document, job, response)
            else:
                self._manual_review(
                    document,
                    job,
                    code="DIAN_UNKNOWN_JOB",
                    message="El trabajo DIAN no tiene una operación reconocida.",
                )
        except DianGatewayError as exc:
            self._record_gateway_failure(document, job, exc)
        except (ValueError, BadZipFile):
            self._manual_review(
                document,
                job,
                code="DIAN_ARTIFACT_INVALID",
                message="No fue posible recuperar el artefacto de prueba para DIAN.",
            )
        except Exception:
            self._manual_review(
                document,
                job,
                code="INTERNAL_ERROR",
                message="La prueba DIAN requiere revisión manual antes de reintentarla.",
            )
        self._db.commit()
        self._db.refresh(document)
        return self._document_view(document)

    def _record_gateway_response(
        self,
        document: DianElectronicDocumentRecord,
        job: DianElectronicOutboxJobRecord,
        response: DianGatewayResponse,
    ) -> None:
        now = self._now()
        response_status = "processing"
        # SendTestSetAsync entrega un ZipKey para consultar el resultado. Aunque
        # incluya IsValid, no se libera un consecutivo como rechazado hasta que
        # GetStatusZip confirme el estado final de esa transmisión.
        if job.operation == "send_test_set" and response.track_id:
            response_status = "processing"
        elif response.is_valid is True:
            response_status = "accepted"
        elif response.is_valid is False:
            response_status = "rejected"
        elif not response.track_id:
            response_status = "manual_review"
        self._db.add(
            DianElectronicSubmissionRecord(
                id=str(uuid4()),
                document_id=document.id,
                job_id=job.id,
                company_id=document.company_id,
                operation=job.operation,
                attempt_number=job.attempt_count,
                status=response_status,
                request_sha256=document.signed_xml_sha256,
                track_id=response.track_id,
                status_code=response.status_code,
                status_description=self._safe_message(response.status_description, 1_000),
                status_message=self._safe_message(response.status_message, 1_000),
                error_message=self._safe_message(response.error_message, 1_000),
                is_valid=response.is_valid,
                completed_at=now,
            )
        )
        if response_status == "processing":
            self._transition_document(
                document,
                status="processing",
                code="DIAN_PROCESSING",
                message="DIAN recibió la prueba; se consultará su estado antes de cualquier nueva acción.",
            )
            self._complete_job(job, status="succeeded")
            self._enqueue_job(
                document,
                operation="check_status",
                actor_user_id=job.created_by_user_id,
                correlation_id=job.correlation_id,
                available_at=now + timedelta(seconds=15),
            )
            return
        if response_status == "accepted":
            self._transition_document(
                document,
                status="accepted",
                code=response.status_code or "DIAN_ACCEPTED",
                message="DIAN aceptó el documento de prueba.",
            )
            self._complete_job(job, status="succeeded")
            return
        if response_status == "rejected":
            self._transition_document(
                document,
                status="rejected",
                code=response.status_code or "DIAN_REJECTED",
                message=(
                    "DIAN rechazó definitivamente el documento de prueba; corrige el XML y "
                    "carga una nueva versión con el mismo consecutivo."
                ),
            )
            self._complete_job(job, status="failed", error_code=response.status_code or "DIAN_REJECTED")
            return
        self._manual_review(
            document,
            job,
            code=response.status_code or "DIAN_RESPONSE_INCOMPLETE",
            message="DIAN respondió sin estado ni identificador de seguimiento; revisa el portal antes de reintentar.",
        )

    def _record_gateway_failure(
        self,
        document: DianElectronicDocumentRecord,
        job: DianElectronicOutboxJobRecord,
        failure: DianGatewayError,
    ) -> None:
        now = self._now()
        if failure.may_have_been_submitted:
            self._db.add(
                DianElectronicSubmissionRecord(
                    id=str(uuid4()),
                    document_id=document.id,
                    job_id=job.id,
                    company_id=document.company_id,
                    operation=job.operation,
                    attempt_number=job.attempt_count,
                    status="unknown",
                    request_sha256=document.signed_xml_sha256,
                    error_message=self._safe_message(failure.message, 1_000),
                    completed_at=now,
                )
            )
            self._manual_review(
                document,
                job,
                code="DIAN_SUBMISSION_UNKNOWN",
                message="No se confirmó la respuesta de DIAN. No se reenviará el documento automáticamente.",
            )
            return
        retryable = failure.code in {"PROVIDER_UNREACHABLE", "SERVICE_UNAVAILABLE"}
        if retryable and job.attempt_count < job.max_attempts:
            self._db.add(
                DianElectronicSubmissionRecord(
                    id=str(uuid4()),
                    document_id=document.id,
                    job_id=job.id,
                    company_id=document.company_id,
                    operation=job.operation,
                    attempt_number=job.attempt_count,
                    status="retrying",
                    request_sha256=document.signed_xml_sha256,
                    error_message=self._safe_message(failure.message, 1_000),
                    completed_at=now,
                )
            )
            self._transition_document(
                document,
                status="queued",
                code=failure.code,
                message="DIAN no está disponible; se reintentará la operación segura.",
            )
            job.status = "retrying"
            job.available_at = now + timedelta(seconds=30 * job.attempt_count)
            job.lease_expires_at = None
            job.error_code = failure.code
            return
        self._manual_review(
            document,
            job,
            code=failure.code,
            message="DIAN no procesó la prueba; revisa la configuración antes de crear un nuevo envío.",
        )

    def _manual_review(
        self,
        document: DianElectronicDocumentRecord,
        job: DianElectronicOutboxJobRecord,
        *,
        code: str,
        message: str,
    ) -> None:
        self._transition_document(document, status="manual_review", code=code, message=message)
        self._complete_job(job, status="failed", error_code=code)

    def _claim_next_job(self) -> DianElectronicOutboxJobRecord | None:
        now = self._now()
        if self._recover_expired_submission(now):
            # Una transmisión vencida pudo llegar a DIAN antes de que el worker
            # cayera. Se conserva para revisión manual y nunca se vuelve a
            # transmitir de forma implícita.
            return None
        candidate_id = self._db.scalar(
            select(DianElectronicOutboxJobRecord.id)
            .where(
                or_(
                    and_(
                        DianElectronicOutboxJobRecord.status.in_(_READY_JOB_STATUSES),
                        DianElectronicOutboxJobRecord.available_at <= now,
                    ),
                    and_(
                        DianElectronicOutboxJobRecord.status == "running",
                        DianElectronicOutboxJobRecord.operation == "check_status",
                        DianElectronicOutboxJobRecord.lease_expires_at.is_not(None),
                        DianElectronicOutboxJobRecord.lease_expires_at < now,
                    ),
                )
            )
            .order_by(DianElectronicOutboxJobRecord.available_at, DianElectronicOutboxJobRecord.created_at)
            .limit(1)
        )
        if candidate_id is None:
            return None
        claimed = self._db.execute(
            update(DianElectronicOutboxJobRecord)
            .where(
                DianElectronicOutboxJobRecord.id == candidate_id,
                or_(
                    and_(
                        DianElectronicOutboxJobRecord.status.in_(_READY_JOB_STATUSES),
                        DianElectronicOutboxJobRecord.available_at <= now,
                    ),
                    and_(
                        DianElectronicOutboxJobRecord.status == "running",
                        DianElectronicOutboxJobRecord.operation == "check_status",
                        DianElectronicOutboxJobRecord.lease_expires_at.is_not(None),
                        DianElectronicOutboxJobRecord.lease_expires_at < now,
                    ),
                ),
            )
            .values(
                status="running",
                attempt_count=DianElectronicOutboxJobRecord.attempt_count + 1,
                started_at=now,
                lease_expires_at=now + timedelta(seconds=_LEASE_SECONDS),
                error_code=None,
            )
            .execution_options(synchronize_session=False)
        )
        if not claimed.rowcount:
            self._db.rollback()
            return None
        self._db.commit()
        job = self._db.get(DianElectronicOutboxJobRecord, candidate_id)
        assert job is not None
        return job

    def _recover_expired_submission(self, now: datetime) -> bool:
        """Aísla un envío cuyo lease venció antes de confirmar su resultado.

        ``SendTestSetAsync`` no es idempotente desde la perspectiva de la cola:
        un worker puede perderse después de que DIAN recibió el ZIP. Por eso un
        lease vencido se convierte en estado desconocido y revisión manual; solo
        ``check_status`` se puede reclamar nuevamente de forma segura.
        """

        candidate_id = self._db.scalar(
            select(DianElectronicOutboxJobRecord.id)
            .where(
                DianElectronicOutboxJobRecord.status == "running",
                DianElectronicOutboxJobRecord.operation == "send_test_set",
                DianElectronicOutboxJobRecord.lease_expires_at.is_not(None),
                DianElectronicOutboxJobRecord.lease_expires_at < now,
            )
            .order_by(DianElectronicOutboxJobRecord.lease_expires_at)
            .limit(1)
        )
        if candidate_id is None:
            return False

        recovered = self._db.execute(
            update(DianElectronicOutboxJobRecord)
            .where(
                DianElectronicOutboxJobRecord.id == candidate_id,
                DianElectronicOutboxJobRecord.status == "running",
                DianElectronicOutboxJobRecord.operation == "send_test_set",
                DianElectronicOutboxJobRecord.lease_expires_at.is_not(None),
                DianElectronicOutboxJobRecord.lease_expires_at < now,
            )
            .values(
                status="failed",
                active_document_id=None,
                lease_expires_at=None,
                error_code="DIAN_SUBMISSION_UNKNOWN",
                completed_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if not recovered.rowcount:
            self._db.rollback()
            return False

        job = self._db.get(DianElectronicOutboxJobRecord, candidate_id)
        assert job is not None
        document = self._db.get(DianElectronicDocumentRecord, job.document_id)
        if document is not None:
            self._db.add(
                DianElectronicSubmissionRecord(
                    id=str(uuid4()),
                    document_id=document.id,
                    job_id=job.id,
                    company_id=document.company_id,
                    operation=job.operation,
                    attempt_number=job.attempt_count,
                    status="unknown",
                    request_sha256=document.signed_xml_sha256,
                    error_message="El worker perdió el lease antes de confirmar la respuesta de DIAN.",
                    completed_at=now,
                )
            )
            self._transition_document(
                document,
                status="manual_review",
                code="DIAN_SUBMISSION_UNKNOWN",
                message="No se confirmó la respuesta de DIAN; revisa el portal antes de cualquier reenvío.",
            )
        self._db.commit()
        return True

    def _enqueue_job(
        self,
        document: DianElectronicDocumentRecord,
        *,
        operation: str,
        actor_user_id: int,
        correlation_id: str | None,
        available_at: datetime | None = None,
    ) -> DianElectronicOutboxJobRecord:
        # La sesión de este servicio no usa autoflush. Antes de verificar la
        # restricción de un trabajo activo debemos materializar, por ejemplo,
        # que el trabajo de envío recién terminado liberó el documento.
        self._db.flush()
        existing = self._db.scalar(
            select(DianElectronicOutboxJobRecord).where(
                DianElectronicOutboxJobRecord.active_document_id == document.id
            )
        )
        if existing is not None:
            raise app_error("CONFLICT", message="Ya existe una operación DIAN activa para este documento.")
        job = DianElectronicOutboxJobRecord(
            id=str(uuid4()),
            document_id=document.id,
            active_document_id=document.id,
            company_id=document.company_id,
            operation=operation,
            status="queued",
            attempt_count=0,
            max_attempts=_MAX_ATTEMPTS,
            available_at=available_at or self._now(),
            correlation_id=correlation_id,
            created_by_user_id=actor_user_id,
        )
        self._db.add(job)
        return job

    def _complete_job(
        self,
        job: DianElectronicOutboxJobRecord,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        job.status = status
        job.active_document_id = None
        job.lease_expires_at = None
        job.error_code = error_code
        job.completed_at = self._now()

    def _transition_document(
        self,
        document: DianElectronicDocumentRecord,
        *,
        status: str,
        code: str | None,
        message: str | None,
    ) -> None:
        previous_status = document.status
        document.status = status
        self._add_status_event(
            document,
            previous_status=previous_status,
            status=status,
            code=code,
            message=message,
            actor_user_id=None,
        )

    def _add_status_event(
        self,
        document: DianElectronicDocumentRecord,
        *,
        previous_status: str | None,
        status: str,
        code: str | None,
        message: str | None,
        actor_user_id: int | None,
    ) -> None:
        self._db.add(
            DianElectronicDocumentStatusEventRecord(
                id=str(uuid4()),
                document_id=document.id,
                company_id=document.company_id,
                previous_status=previous_status,
                status=status,
                code=code,
                message=self._safe_message(message, 500),
                actor_user_id=actor_user_id,
            )
        )

    def _credentials_for_document(
        self, document: DianElectronicDocumentRecord
    ) -> DianTechnicalCredentials:
        profile = self._db.get(DianFiscalProfileRecord, document.profile_id)
        if profile is None or profile.data_source_id is None:
            raise app_error("CONFLICT", message="La configuración DIAN ya no está disponible.")
        context = ProviderContext(
            tenant_id=UUID(profile.tenant_id),
            company_id=UUID(document.company_id),
            data_source_id=UUID(profile.data_source_id),
            provider=ProviderKind.DIAN,
        )
        secret = self._secret_store.get(context)
        if secret is None:
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                message="Configura las credenciales DIAN antes de enviar la prueba.",
            )
        try:
            return DianTechnicalCredentials.from_secret_values(secret.values)
        except ValueError as exc:
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                message="Las credenciales DIAN no están listas para firmar la solicitud SOAP.",
            ) from exc

    def _required_test_set_id(self, profile_id: str) -> str:
        profile = self._db.get(DianFiscalProfileRecord, profile_id)
        if profile is None or not profile.software_test_set_id:
            raise app_error("CONFLICT", message="Falta el TestSetId de habilitación DIAN.")
        return profile.software_test_set_id

    def _latest_track_id(self, document_id: str) -> str | None:
        return self._db.scalar(
            select(DianElectronicSubmissionRecord.track_id)
            .where(
                DianElectronicSubmissionRecord.document_id == document_id,
                DianElectronicSubmissionRecord.track_id.is_not(None),
            )
            .order_by(DianElectronicSubmissionRecord.created_at.desc())
            .limit(1)
        )

    def _reserve_number(
        self,
        *,
        profile: DianFiscalProfileRecord,
        company_id: UUID,
        prefix: str,
        consecutive: int,
        issue_date: date,
    ) -> _DianNumberReservation:
        record = self._db.scalar(
            select(DianNumberingRangeRecord)
            .where(
                DianNumberingRangeRecord.profile_id == profile.id,
                DianNumberingRangeRecord.company_id == str(company_id),
                DianNumberingRangeRecord.prefix == prefix,
                DianNumberingRangeRecord.active.is_(True),
                DianNumberingRangeRecord.valid_from <= issue_date,
                DianNumberingRangeRecord.valid_to >= issue_date,
            )
            .order_by(DianNumberingRangeRecord.created_at.desc())
            .with_for_update()
        )
        if record is None:
            raise app_error(
                "CONFLICT",
                message="No existe un rango DIAN de habilitación vigente para el prefijo indicado.",
            )
        if consecutive < record.range_from or consecutive > record.range_to:
            raise app_error("CONFLICT", message="El consecutivo está fuera del rango DIAN de habilitación.")
        if consecutive == record.next_number:
            record.next_number = consecutive + 1
            return _DianNumberReservation(numbering_range=record, corrects_document=None)
        if consecutive > record.next_number:
            raise app_error(
                "CONFLICT",
                message="El consecutivo debe ser el siguiente valor reservado del rango DIAN.",
                details={"next_number": record.next_number},
            )
        existing_unrejected = self._db.scalar(
            select(DianElectronicDocumentRecord.id)
            .where(
                DianElectronicDocumentRecord.company_id == str(company_id),
                DianElectronicDocumentRecord.profile_id == profile.id,
                DianElectronicDocumentRecord.prefix == prefix,
                DianElectronicDocumentRecord.consecutive == consecutive,
                DianElectronicDocumentRecord.status != "rejected",
            )
            .limit(1)
        )
        if existing_unrejected is not None:
            raise app_error(
                "CONFLICT",
                message=(
                    "El consecutivo DIAN ya tiene una prueba pendiente, aceptada o en revisión; "
                    "no puede reenviarse."
                ),
            )
        correction = aliased(DianElectronicDocumentRecord)
        corrected_document = self._db.scalar(
            select(DianElectronicDocumentRecord)
            .where(
                DianElectronicDocumentRecord.company_id == str(company_id),
                DianElectronicDocumentRecord.profile_id == profile.id,
                DianElectronicDocumentRecord.prefix == prefix,
                DianElectronicDocumentRecord.consecutive == consecutive,
                DianElectronicDocumentRecord.status == "rejected",
                ~select(correction.id)
                .where(correction.corrects_document_id == DianElectronicDocumentRecord.id)
                .exists(),
            )
            .order_by(
                DianElectronicDocumentRecord.updated_at.desc(),
                DianElectronicDocumentRecord.created_at.desc(),
            )
            .with_for_update()
            .limit(1)
        )
        if corrected_document is None:
            raise app_error(
                "CONFLICT",
                message=(
                    "El consecutivo solo puede reutilizarse para corregir una prueba "
                    "con rechazo definitivo de DIAN."
                ),
            )
        return _DianNumberReservation(
            numbering_range=record,
            corrects_document=corrected_document,
        )

    def _profile_missing_requirements(self, profile: DianFiscalProfileRecord) -> set[str]:
        missing: set[str] = set()
        if not profile.data_source_id:
            missing.add("dian_data_source")
        else:
            source = self._db.get(CompanyDataSourceRecord, profile.data_source_id)
            if source is None or not source.credential_reference:
                missing.add("technical_credentials")
        if not profile.software_test_set_id:
            missing.add("software_test_set_id")
        if not profile.signature_policy_identifier or not profile.signature_policy_digest_base64:
            missing.add("signature_policy")
        active_range = self._db.scalar(
            select(DianNumberingRangeRecord.id).where(
                DianNumberingRangeRecord.profile_id == profile.id,
                DianNumberingRangeRecord.active.is_(True),
            )
        )
        if active_range is None:
            missing.add("numbering_range")
        return missing

    def _profile_status(self, profile: DianFiscalProfileRecord) -> str:
        return "ready_for_habilitation" if not self._profile_missing_requirements(profile) else "draft"

    def _profile_view(self, profile: DianFiscalProfileRecord) -> DianHabilitationProfile:
        missing = self._profile_missing_requirements(profile)
        active_ranges = self._db.scalar(
            select(DianNumberingRangeRecord.id).where(
                DianNumberingRangeRecord.profile_id == profile.id,
                DianNumberingRangeRecord.active.is_(True),
            )
        )
        source = self._db.get(CompanyDataSourceRecord, profile.data_source_id) if profile.data_source_id else None
        return DianHabilitationProfile(
            id=UUID(profile.id),
            company_id=UUID(profile.company_id),
            data_source_id=UUID(profile.data_source_id) if profile.data_source_id else None,
            status=profile.status,
            integration_enabled=is_enabled(FEATURE_DIAN_ELECTRONIC_HABILITATION),
            software_test_set_id=profile.software_test_set_id,
            legal_name=profile.legal_name,
            nit=profile.nit,
            check_digit=profile.check_digit,
            email=profile.email,
            address=profile.address,
            city_code=profile.city_code,
            city_name=profile.city_name,
            department_code=profile.department_code,
            department_name=profile.department_name,
            country_code=profile.country_code,
            tax_responsibilities=tuple(profile.tax_responsibilities),
            phone=profile.phone,
            tax_regime=profile.tax_regime,
            credential_configured=bool(source and source.credential_reference),
            active_numbering_ranges=1 if active_ranges else 0,
            missing_requirements=tuple(sorted(missing)),
        )

    @staticmethod
    def _range_view(record: DianNumberingRangeRecord) -> DianNumberingRange:
        return DianNumberingRange(
            id=UUID(record.id),
            profile_id=UUID(record.profile_id),
            prefix=record.prefix,
            resolution_number=record.resolution_number,
            resolution_date=record.resolution_date,
            valid_from=record.valid_from,
            valid_to=record.valid_to,
            range_from=record.range_from,
            range_to=record.range_to,
            next_number=record.next_number,
            active=record.active,
        )

    @staticmethod
    def _document_view(record: DianElectronicDocumentRecord) -> DianElectronicDocument:
        return DianElectronicDocument(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            corrects_document_id=(UUID(record.corrects_document_id) if record.corrects_document_id else None),
            document_number=record.document_number,
            document_type=record.document_type,
            prefix=record.prefix,
            consecutive=record.consecutive,
            issue_date=record.issue_date,
            currency_code=record.currency_code,
            payable_amount=record.payable_amount,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _required_profile(self, company_id: UUID) -> DianFiscalProfileRecord:
        profile = self._db.scalar(
            select(DianFiscalProfileRecord).where(DianFiscalProfileRecord.company_id == str(company_id))
        )
        if profile is None:
            raise app_error(
                "CONFLICT",
                message="Configura primero el perfil fiscal DIAN de la empresa.",
            )
        return profile

    def _company(self, company_id: UUID) -> CompanyRecord:
        company = self._db.get(CompanyRecord, str(company_id))
        if company is None:
            raise app_error("NOT_FOUND", message="Empresa no encontrada.")
        return company

    def _cipher(self) -> DianArtifactCipher:
        if self._artifact_cipher is None:
            self._artifact_cipher = DianArtifactCipher.from_settings()
        return self._artifact_cipher

    def _document_for_company(
        self, company_id: UUID, document_id: UUID
    ) -> DianElectronicDocumentRecord:
        document = self._db.get(DianElectronicDocumentRecord, str(document_id))
        if document is None or document.company_id != str(company_id):
            raise app_error("NOT_FOUND", message="Documento electrónico DIAN no encontrado.")
        return document

    def _get_or_create_habilitation_source(
        self, company: CompanyRecord, actor_user_id: int
    ) -> CompanyDataSourceRecord:
        source = self._db.scalar(
            select(CompanyDataSourceRecord).where(
                CompanyDataSourceRecord.company_id == company.id,
                CompanyDataSourceRecord.connector_id == _HABILITATION_CONNECTOR_ID,
            )
        )
        if source is not None:
            return source
        source = CompanyDataSourceRecord(
            id=str(uuid4()),
            tenant_id=company.tenant_id,
            company_id=company.id,
            connector_id=_HABILITATION_CONNECTOR_ID,
            display_name=_HABILITATION_SOURCE_NAME,
            kind=DataSourceKind.FISCAL_AUTHORITY.value,
            mode=ConnectionMode.FISCAL_SERVICE.value,
            capabilities=[],
            provider_id=ProviderKind.DIAN.value,
            credential_reference=None,
            status=DataSourceStatus.PENDING.value,
            created_by_user_id=actor_user_id,
        )
        self._db.add(source)
        self._db.flush()
        return source

    @staticmethod
    def _normalized_profile_values(**values: object) -> dict[str, object]:
        required_fields = {
            "legal_name": 255,
            "nit": 30,
            "check_digit": 1,
            "email": 255,
            "address": 255,
            "city_code": 10,
            "city_name": 100,
            "department_code": 10,
            "department_name": 100,
        }
        normalized: dict[str, object] = {
            name: DianElectronicHabilitationService._required_text(values[name], name, maximum=maximum)
            for name, maximum in required_fields.items()
        }
        nit = str(normalized["nit"])
        check_digit = str(normalized["check_digit"])
        if not nit.isdigit() or not check_digit.isdigit():
            raise app_error("VALIDATION_ERROR", message="El NIT y el dígito de verificación deben ser numéricos.")
        if "@" not in str(normalized["email"]):
            raise app_error("VALIDATION_ERROR", message="El correo fiscal no tiene un formato válido.")
        responsibilities = values.get("tax_responsibilities")
        if not isinstance(responsibilities, list) or not responsibilities:
            raise app_error(
                "VALIDATION_ERROR",
                message="Indica al menos una responsabilidad tributaria de la empresa.",
            )
        normalized["tax_responsibilities"] = [
            DianElectronicHabilitationService._required_text(
                item, "tax_responsibilities", maximum=100
            )
            for item in responsibilities
        ]
        for name, maximum in {"phone": 50, "tax_regime": 100}.items():
            value = values.get(name)
            normalized[name] = (
                DianElectronicHabilitationService._required_text(value, name, maximum=maximum)
                if value is not None
                else None
            )
        normalized.update(
            DianElectronicHabilitationService._normalized_habilitation_parameters(
                software_test_set_id=values.get("software_test_set_id"),
                signature_policy_identifier=values.get("signature_policy_identifier"),
                signature_policy_digest_base64=values.get("signature_policy_digest_base64"),
                signature_policy_qualifier_url=values.get("signature_policy_qualifier_url"),
            )
        )
        return normalized

    @staticmethod
    def _normalized_habilitation_parameters(
        *,
        software_test_set_id: object,
        signature_policy_identifier: object,
        signature_policy_digest_base64: object,
        signature_policy_qualifier_url: object,
    ) -> dict[str, str | None]:
        values = {
            "software_test_set_id": (software_test_set_id, 128),
            "signature_policy_identifier": (signature_policy_identifier, 2048),
            "signature_policy_digest_base64": (signature_policy_digest_base64, 128),
            "signature_policy_qualifier_url": (signature_policy_qualifier_url, 2048),
        }
        normalized = {
            name: (
                DianElectronicHabilitationService._required_text(value, name, maximum=maximum)
                if value is not None
                else None
            )
            for name, (value, maximum) in values.items()
        }
        policy_identifier = normalized["signature_policy_identifier"]
        policy_digest = normalized["signature_policy_digest_base64"]
        if bool(policy_identifier) != bool(policy_digest):
            raise app_error(
                "VALIDATION_ERROR",
                message="La política de firma requiere identificador y hash SHA-256 en base64.",
            )
        if policy_digest:
            try:
                decoded_policy_digest = base64.b64decode(str(policy_digest), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise app_error(
                    "VALIDATION_ERROR",
                    message="El hash de política de firma no tiene formato SHA-256 base64.",
                ) from exc
            if len(decoded_policy_digest) != 32:
                raise app_error(
                    "VALIDATION_ERROR",
                    message="El hash de política de firma debe usar SHA-256.",
                )
        return normalized

    @staticmethod
    def _required_text(value: object, field: str, *, maximum: int) -> str:
        if not isinstance(value, str):
            raise app_error("VALIDATION_ERROR", message=f"{field} debe ser texto.")
        normalized = value.strip()
        if not normalized or len(normalized) > maximum:
            raise app_error("VALIDATION_ERROR", message=f"{field} es obligatorio y excede el tamaño permitido.")
        return normalized

    @staticmethod
    def _normalized_document_type(value: object) -> str:
        if not isinstance(value, str) or value not in _DOCUMENT_ROOTS:
            raise app_error(
                "VALIDATION_ERROR",
                message="El tipo de documento DIAN de habilitación no está permitido.",
            )
        return value

    @staticmethod
    def _normalized_amount(value: object) -> str:
        if not isinstance(value, str) or len(value.strip()) > 32:
            raise app_error("VALIDATION_ERROR", message="El valor total DIAN no es válido.")
        try:
            amount = Decimal(value.strip())
        except (InvalidOperation, ValueError) as exc:
            raise app_error("VALIDATION_ERROR", message="El valor total DIAN no es válido.") from exc
        if not amount.is_finite() or amount < 0:
            raise app_error("VALIDATION_ERROR", message="El valor total DIAN no es válido.")
        return format(amount.quantize(Decimal("0.01")), "f")

    @staticmethod
    def _safe_message(value: str | None, maximum: int) -> str | None:
        if not value:
            return None
        return value.replace("\x00", " ").strip()[:maximum] or None

    @staticmethod
    def _signed_xml_from_zip(
        file_name: str,
        content: bytes,
        *,
        expected_document_number: str,
        expected_document_type: str,
        expected_issue_date: date,
        expected_currency_code: str,
        expected_payable_amount: str,
        expected_issuer_nit: str,
        expected_signature_policy_identifier: str,
        expected_signature_policy_digest_base64: str,
    ) -> bytes:
        if not file_name.lower().endswith(".zip"):
            raise app_error("VALIDATION_ERROR", message="El documento de prueba debe cargarse en un archivo ZIP.")
        if not content or len(content) > _MAX_UPLOAD_BYTES:
            raise app_error("VALIDATION_ERROR", message="El archivo de prueba está vacío o supera el límite permitido.")
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(entries) != 1 or not entries[0].filename.lower().endswith(".xml"):
                    raise app_error(
                        "VALIDATION_ERROR",
                        message="El ZIP DIAN debe contener únicamente un documento XML firmado.",
                    )
                entry = entries[0]
                if entry.file_size <= 0 or entry.file_size > _MAX_XML_BYTES:
                    raise app_error("VALIDATION_ERROR", message="El XML de prueba tiene un tamaño no permitido.")
                xml = archive.read(entry)
        except BadZipFile as exc:
            raise app_error("VALIDATION_ERROR", message="El archivo de prueba no es un ZIP válido.") from exc
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
        try:
            root = etree.fromstring(xml, parser=parser)
        except etree.XMLSyntaxError as exc:
            raise app_error("VALIDATION_ERROR", message="El ZIP no contiene un XML UBL válido.") from exc
        expected_root_name, expected_root_namespace = _DOCUMENT_ROOTS[expected_document_type]
        root_name = etree.QName(root)
        if root_name.localname != expected_root_name or root_name.namespace != expected_root_namespace:
            raise app_error(
                "VALIDATION_ERROR",
                message="El tipo de XML no coincide con el documento DIAN que se va a enviar.",
            )
        ubl_document_number = (root.findtext(f"{{{_CBC_NS}}}ID") or "").strip()
        if ubl_document_number != expected_document_number:
            raise app_error(
                "VALIDATION_ERROR",
                message="El consecutivo del XML no coincide con el consecutivo DIAN reservado.",
            )
        if (root.findtext(f"{{{_CBC_NS}}}ProfileExecutionID") or "").strip() != "2":
            raise app_error(
                "VALIDATION_ERROR",
                message="El XML debe indicar ProfileExecutionID 2 para habilitación DIAN.",
            )
        if (root.findtext(f"{{{_CBC_NS}}}IssueDate") or "").strip() != expected_issue_date.isoformat():
            raise app_error(
                "VALIDATION_ERROR",
                message="La fecha del XML no coincide con la prueba DIAN reservada.",
            )
        if (
            root.findtext(f"{{{_CBC_NS}}}DocumentCurrencyCode") or ""
        ).strip().upper() != expected_currency_code:
            raise app_error(
                "VALIDATION_ERROR",
                message="La moneda del XML no coincide con la prueba DIAN reservada.",
            )
        payable_amount = root.findtext(
            f"{{{_CAC_NS}}}LegalMonetaryTotal/{{{_CBC_NS}}}PayableAmount"
        )
        try:
            matches_payable_amount = (
                payable_amount is not None
                and Decimal(payable_amount.strip()) == Decimal(expected_payable_amount)
            )
        except (InvalidOperation, ValueError):
            matches_payable_amount = False
        if not matches_payable_amount:
            raise app_error(
                "VALIDATION_ERROR",
                message="El total del XML no coincide con la prueba DIAN reservada.",
            )
        issuer_ids = root.xpath(
            "./cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID/text()",
            namespaces={"cac": _CAC_NS, "cbc": _CBC_NS},
        )
        if expected_issuer_nit not in {str(value).strip() for value in issuer_ids}:
            raise app_error(
                "VALIDATION_ERROR",
                message="El NIT emisor del XML no coincide con el perfil DIAN de la empresa.",
            )
        signature_values = root.xpath(
            ".//*[local-name()='SignatureValue' and namespace-uri()=$signature_namespace]/text()",
            signature_namespace=_DS_NS,
        )
        if not any(str(value).strip() for value in signature_values):
            raise app_error("VALIDATION_ERROR", message="El XML de prueba debe contener una firma digital XAdES.")
        signing_certificates = root.xpath(
            ".//*[local-name()='X509Certificate' and namespace-uri()=$signature_namespace]/text()",
            signature_namespace=_DS_NS,
        )
        if not any(str(value).strip() for value in signing_certificates):
            raise app_error(
                "VALIDATION_ERROR",
                message="El XML de prueba no incluye el certificado de firma XAdES.",
            )
        policy_identifier = root.findtext(
            ".//"
            f"{{{_XADES_NS}}}SignaturePolicyIdentifier/"
            f"{{{_XADES_NS}}}SignaturePolicyId/"
            f"{{{_XADES_NS}}}SigPolicyId/"
            f"{{{_XADES_NS}}}Identifier"
        )
        policy_digest = root.findtext(
            ".//"
            f"{{{_XADES_NS}}}SignaturePolicyIdentifier/"
            f"{{{_XADES_NS}}}SignaturePolicyId/"
            f"{{{_XADES_NS}}}SigPolicyHash/"
            f"{{{_DS_NS}}}DigestValue"
        )
        if (
            (policy_identifier or "").strip() != expected_signature_policy_identifier
            or (policy_digest or "").strip() != expected_signature_policy_digest_base64
        ):
            raise app_error(
                "VALIDATION_ERROR",
                message="La política XAdES del XML no coincide con la configuración de habilitación.",
            )
        return xml
