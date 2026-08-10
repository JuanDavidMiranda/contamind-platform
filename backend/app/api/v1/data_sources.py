"""Fuentes de datos operadas dentro del ámbito de cada empresa."""

from pathlib import Path
from uuid import UUID

import re

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.data_sources.models import (
    CompanyDataSource,
    ConnectionMode,
    DataCapability,
    DataSourceKind,
    DataSourceStatus,
    FileFormat,
    ImportEntity,
    ImportProfile,
    ImportRejection,
    ProviderOperationResult,
)
from app.database.database import get_db
from app.models.user import User
from app.providers.canonical import Party, PartyType
from app.services.company_service import CompanyService
from app.services.data_source_service import DataSourceService
from app.services.provider_connection_service import ProviderConnectionService
from app.shared.company_access import (
    MANAGE_SOURCES_ROLES,
    OPERATE_SOURCES_ROLES,
    VIEW_COMPANY_ROLES,
    require_company_role,
)
from app.shared.errors import app_error
from app.shared.security import get_current_user

router = APIRouter(prefix="/data-sources", tags=["Data sources"])


class DataSourceCreate(BaseModel):
    tenant_id: UUID
    company_id: UUID
    connector_id: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    kind: DataSourceKind
    mode: ConnectionMode
    capabilities: set[DataCapability] = Field(default_factory=set)
    provider_id: str | None = Field(default=None, max_length=64)
    credential_reference: str | None = Field(default=None, max_length=255)
    status: DataSourceStatus = DataSourceStatus.ACTIVE


class ImportProfileCreate(BaseModel):
    entity: ImportEntity
    file_format: FileFormat
    column_mapping: dict[str, str] = Field(min_length=1)
    default_party_type: PartyType = PartyType.CUSTOMER


class PartyImportResponse(BaseModel):
    batch_id: UUID
    parties: tuple[Party, ...]
    rejections: tuple[ImportRejection, ...]


class AccountingImportResponse(BaseModel):
    batch_id: UUID
    entity: ImportEntity
    accepted_rows: int
    rejections: tuple[ImportRejection, ...]


class ManualPartyCreate(BaseModel):
    party_type: PartyType
    name: str = Field(min_length=1, max_length=255)
    document_type: str | None = Field(default=None, max_length=10)
    document_number: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    fiscal_responsibility: str | None = Field(default=None, max_length=100)


_CREDENTIAL_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProviderCredentialsWrite(BaseModel):
    credentials: dict[str, SecretStr] = Field(min_length=1)

    @field_validator("credentials")
    @classmethod
    def validate_credentials(cls, value: dict[str, SecretStr]) -> dict[str, SecretStr]:
        if any(
            not _CREDENTIAL_KEY_PATTERN.fullmatch(key)
            or not secret.get_secret_value()
            or len(secret.get_secret_value()) > 4096
            for key, secret in value.items()
        ):
            raise ValueError("Las credenciales contienen un campo no válido.")
        return value

    def plain_values(self) -> dict[str, str]:
        return {key: secret.get_secret_value() for key, secret in self.credentials.items()}


class ProviderCredentialsResponse(BaseModel):
    data_source_id: UUID
    provider_id: str
    status: DataSourceStatus
    credential_configured: bool = True


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


def _source_for_role(
    data_source_id: UUID,
    user: User,
    db: Session,
    allowed_roles,
) -> CompanyDataSource:
    source = DataSourceService(db).get_source(data_source_id)
    CompanyService(db).require_company_in_tenant(source.company_id, source.tenant_id)
    CompanyService(db).require_active_company(source.company_id)
    require_company_role(user, db, source.company_id, allowed_roles)
    return source


@router.post("", response_model=CompanyDataSource, status_code=201)
def create_data_source(
    payload: DataSourceCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    CompanyService(db).require_company_in_tenant(payload.company_id, payload.tenant_id)
    CompanyService(db).require_active_company(payload.company_id)
    require_company_role(user, db, payload.company_id, MANAGE_SOURCES_ROLES)
    return DataSourceService(db).create_source(
        CompanyDataSource(**payload.model_dump()), actor_user_id=user.id
    )


@router.get("", response_model=list[CompanyDataSource])
def list_data_sources(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    CompanyService(db).get_company(company_id)
    require_company_role(user, db, company_id, VIEW_COMPANY_ROLES)
    return DataSourceService(db).list_sources(company_id)


@router.post("/{data_source_id}/profiles", response_model=ImportProfile, status_code=201)
def create_import_profile(
    data_source_id: UUID,
    payload: ImportProfileCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, MANAGE_SOURCES_ROLES)
    profile = ImportProfile(data_source_id=data_source_id, **payload.model_dump())
    return DataSourceService(db).create_profile(profile)


@router.post("/{data_source_id}/imports/parties", response_model=PartyImportResponse)
async def import_parties(
    data_source_id: UUID,
    profile_id: UUID = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, OPERATE_SOURCES_ROLES)
    content = await file.read(settings.MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > settings.MAX_IMPORT_FILE_BYTES:
        raise app_error("VALIDATION_ERROR", message="El archivo supera el tamaño máximo permitido.")
    if not content:
        raise app_error("VALIDATION_ERROR", message="El archivo está vacío.")

    extension = Path(file.filename or "").suffix.lower()
    formats_by_extension = {".csv": FileFormat.CSV, ".xlsx": FileFormat.XLSX}
    if extension not in formats_by_extension:
        raise app_error("VALIDATION_ERROR", message="Solo se admiten archivos CSV o XLSX.")

    batch_id, result = await DataSourceService(db).import_parties(
        data_source_id,
        profile_id,
        content,
        uploaded_format=formats_by_extension[extension],
        actor_user_id=user.id,
    )
    return PartyImportResponse(
        batch_id=batch_id,
        parties=result.parties,
        rejections=result.rejections,
    )


@router.post("/{data_source_id}/imports/accounting", response_model=AccountingImportResponse)
async def import_accounting(
    data_source_id: UUID,
    profile_id: UUID = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, OPERATE_SOURCES_ROLES)
    content = await file.read(settings.MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > settings.MAX_IMPORT_FILE_BYTES:
        raise app_error("VALIDATION_ERROR", message="El archivo supera el tamaño máximo permitido.")
    if not content:
        raise app_error("VALIDATION_ERROR", message="El archivo está vacío.")
    extension = Path(file.filename or "").suffix.lower()
    formats_by_extension = {".csv": FileFormat.CSV, ".xlsx": FileFormat.XLSX}
    if extension not in formats_by_extension:
        raise app_error("VALIDATION_ERROR", message="Solo se admiten archivos CSV o XLSX.")
    batch_id, result = DataSourceService(db).import_accounting(
        data_source_id,
        profile_id,
        content,
        uploaded_format=formats_by_extension[extension],
        actor_user_id=user.id,
    )
    return AccountingImportResponse(
        batch_id=batch_id,
        entity=result.entity,
        accepted_rows=result.accepted_rows,
        rejections=result.rejections,
    )


@router.post("/{data_source_id}/parties", response_model=Party, status_code=201)
def capture_manual_party(
    data_source_id: UUID,
    payload: ManualPartyCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Captura terceros sin permitir que el cliente elija la empresa de destino."""

    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, OPERATE_SOURCES_ROLES)
    return DataSourceService(db).capture_manual_party(
        data_source_id, actor_user_id=user.id, **payload.model_dump()
    )


@router.put("/{data_source_id}/credentials", response_model=ProviderCredentialsResponse)
def save_provider_credentials(
    data_source_id: UUID,
    payload: ProviderCredentialsWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Guarda o rota secretos sin devolverlos ni escribirlos en la auditoría."""

    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, MANAGE_SOURCES_ROLES)
    source = ProviderConnectionService(db).save_credentials(
        data_source_id, payload.plain_values(), actor_user_id=user.id
    )
    assert source.provider_id is not None
    return ProviderCredentialsResponse(
        data_source_id=source.id,
        provider_id=source.provider_id,
        status=source.status,
    )


@router.delete("/{data_source_id}/credentials", status_code=status.HTTP_204_NO_CONTENT)
def revoke_provider_credentials(
    data_source_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, MANAGE_SOURCES_ROLES)
    ProviderConnectionService(db).revoke_credentials(data_source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{data_source_id}/connection-test", response_model=ProviderOperationResult)
async def test_provider_connection(
    data_source_id: UUID,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, MANAGE_SOURCES_ROLES)
    return await ProviderConnectionService(db).test_connection(
        data_source_id,
        actor_user_id=user.id,
        correlation_id=(x_request_id or "")[:64] or None,
    )


@router.post("/{data_source_id}/sync/parties", response_model=ProviderOperationResult)
async def sync_provider_parties(
    data_source_id: UUID,
    page_size: int = Query(default=50, ge=1, le=100),
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, OPERATE_SOURCES_ROLES)
    return await ProviderConnectionService(db).sync_parties(
        data_source_id,
        actor_user_id=user.id,
        page_size=page_size,
        correlation_id=(x_request_id or "")[:64] or None,
    )


@router.get("/{data_source_id}/connection-runs", response_model=list[ProviderOperationResult])
def list_provider_connection_runs(
    data_source_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _source_for_role(data_source_id, user, db, VIEW_COMPANY_ROLES)
    return ProviderConnectionService(db).list_runs(data_source_id)
