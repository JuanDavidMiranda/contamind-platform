"""API administrativa inicial para fuentes de datos e importaciones de terceros."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.admin import require_admin
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
)
from app.database.database import get_db
from app.providers.canonical import Party, PartyType
from app.services.data_source_service import DataSourceService
from app.shared.errors import app_error

router = APIRouter(prefix="/admin/data-sources", tags=["Data sources"])


class DataSourceCreate(BaseModel):
    tenant_id: UUID
    company_id: UUID
    connector_id: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    kind: DataSourceKind
    mode: ConnectionMode
    capabilities: set[DataCapability] = set()
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


def _require_admin(authorization: str | None, db: Session) -> None:
    require_admin(authorization, db)


@router.post("", response_model=CompanyDataSource, status_code=201)
def create_data_source(
    payload: DataSourceCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_admin(authorization, db)
    return DataSourceService(db).create_source(CompanyDataSource(**payload.model_dump()))


@router.get("", response_model=list[CompanyDataSource])
def list_data_sources(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_admin(authorization, db)
    return DataSourceService(db).list_sources(company_id)


@router.post("/{data_source_id}/profiles", response_model=ImportProfile, status_code=201)
def create_import_profile(
    data_source_id: UUID,
    payload: ImportProfileCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_admin(authorization, db)
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
    _require_admin(authorization, db)
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
        data_source_id, profile_id, content, uploaded_format=formats_by_extension[extension]
    )
    return PartyImportResponse(
        batch_id=batch_id,
        parties=result.parties,
        rejections=result.rejections,
    )
