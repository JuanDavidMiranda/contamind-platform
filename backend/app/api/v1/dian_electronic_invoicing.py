"""Configuración y pruebas de facturación electrónica DIAN en habilitación."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.user import CompanyRole, User
from app.services.company_service import CompanyService
from app.services.dian_electronic_habilitation_service import (
    DianElectronicDocument,
    DianElectronicHabilitationService,
    DianHabilitationProfile,
    DianNumberingRange,
    DianSubmissionEvent,
)
from app.shared.company_access import MANAGE_SOURCES_ROLES, VIEW_COMPANY_ROLES, require_company_role
from app.shared.security import get_current_user


router = APIRouter(
    prefix="/companies/{company_id}/dian/electronic-invoicing",
    tags=["DIAN electronic invoicing"],
)


class DianHabilitationProfileWrite(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    nit: str = Field(min_length=1, max_length=30, pattern=r"^\d+$")
    check_digit: str = Field(min_length=1, max_length=1, pattern=r"^\d$")
    email: str = Field(min_length=3, max_length=255)
    address: str = Field(min_length=1, max_length=255)
    city_code: str = Field(min_length=1, max_length=10)
    city_name: str = Field(min_length=1, max_length=100)
    department_code: str = Field(min_length=1, max_length=10)
    department_name: str = Field(min_length=1, max_length=100)
    tax_responsibilities: list[str] = Field(min_length=1, max_length=30)
    phone: str | None = Field(default=None, max_length=50)
    tax_regime: str | None = Field(default=None, max_length=100)
    software_test_set_id: str | None = Field(default=None, max_length=128)
    signature_policy_identifier: str | None = Field(default=None, max_length=2048)
    signature_policy_digest_base64: str | None = Field(default=None, max_length=128)
    signature_policy_qualifier_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_signature_policy(self) -> "DianHabilitationProfileWrite":
        has_identifier = bool(self.signature_policy_identifier)
        has_hash = bool(self.signature_policy_digest_base64)
        if has_identifier != has_hash:
            raise ValueError("La política de firma requiere identificador y hash SHA-256 en base64.")
        return self


class DianHabilitationProfileResponse(BaseModel):
    id: UUID
    company_id: UUID
    data_source_id: UUID | None
    environment: str = "habilitation"
    production_locked: bool = True
    status: str
    integration_enabled: bool
    can_manage_habilitation: bool
    software_test_set_id_configured: bool
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
    tax_responsibilities: list[str]
    phone: str | None
    tax_regime: str | None
    credential_configured: bool
    active_numbering_ranges: int
    missing_requirements: list[str]

    @classmethod
    def from_profile(
        cls,
        profile: DianHabilitationProfile,
        *,
        can_manage_habilitation: bool,
    ) -> "DianHabilitationProfileResponse":
        return cls(
            id=profile.id,
            company_id=profile.company_id,
            data_source_id=profile.data_source_id,
            status=profile.status,
            integration_enabled=profile.integration_enabled,
            can_manage_habilitation=can_manage_habilitation,
            software_test_set_id_configured=bool(profile.software_test_set_id),
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
            tax_responsibilities=list(profile.tax_responsibilities),
            phone=profile.phone,
            tax_regime=profile.tax_regime,
            credential_configured=profile.credential_configured,
            active_numbering_ranges=profile.active_numbering_ranges,
            missing_requirements=list(profile.missing_requirements),
        )


class DianTechnicalCredentialsWrite(BaseModel):
    """Secretos de DIAN restringidos al ambiente de habilitación.

    No se usa el modelo genérico de conexiones: aceptar únicamente los cuatro
    valores necesarios evita mezclar una configuración de emisión con el
    piloto de consulta de adquirientes.
    """

    software_id: SecretStr
    software_password: SecretStr
    certificate_pfx_base64: SecretStr
    certificate_password: SecretStr

    def plain_values(self) -> dict[str, str]:
        return {
            "software_id": self.software_id.get_secret_value(),
            "software_password": self.software_password.get_secret_value(),
            "certificate_pfx_base64": self.certificate_pfx_base64.get_secret_value(),
            "certificate_password": self.certificate_password.get_secret_value(),
        }


class DianHabilitationParametersWrite(BaseModel):
    """Parámetros públicos entregados por DIAN para el set de habilitación."""

    software_test_set_id: str = Field(min_length=1, max_length=128)
    signature_policy_identifier: str = Field(min_length=1, max_length=2048)
    signature_policy_digest_base64: str = Field(min_length=1, max_length=128)
    signature_policy_qualifier_url: str | None = Field(default=None, max_length=2048)


class DianHabilitationAccessResponse(BaseModel):
    """Permiso no sensible que permite no mostrar formularios a lectores."""

    can_manage_habilitation: bool


class DianNumberingRangeWrite(BaseModel):
    prefix: str = Field(min_length=1, max_length=20)
    resolution_number: str = Field(min_length=1, max_length=100)
    resolution_date: date
    valid_from: date
    valid_to: date
    range_from: int = Field(ge=1)
    range_to: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> "DianNumberingRangeWrite":
        if self.valid_to < self.valid_from or self.range_to < self.range_from:
            raise ValueError("La vigencia y el rango de numeración deben tener límites válidos.")
        return self


class DianNumberingRangeResponse(BaseModel):
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

    @classmethod
    def from_range(cls, value: DianNumberingRange) -> "DianNumberingRangeResponse":
        return cls(**value.__dict__)


class DianElectronicDocumentResponse(BaseModel):
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

    @classmethod
    def from_document(cls, document: DianElectronicDocument) -> "DianElectronicDocumentResponse":
        return cls(**document.__dict__)


class DianDocumentEventResponse(BaseModel):
    id: UUID
    status: str
    code: str | None
    message: str | None
    created_at: datetime

    @classmethod
    def from_event(cls, event: DianSubmissionEvent) -> "DianDocumentEventResponse":
        return cls(**event.__dict__)


class DianDocumentEventsResponse(BaseModel):
    items: list[DianDocumentEventResponse]


def _current_user(authorization: str | None, db: Session) -> User:
    return get_current_user(authorization, db)


def _company_for_role(company_id: UUID, user: User, db: Session, roles) -> CompanyRole | None:
    CompanyService(db).require_active_company(company_id)
    return require_company_role(user, db, company_id, roles)


def _can_manage_habilitation(user: User, role: CompanyRole | None) -> bool:
    return user.is_platform_admin or role in MANAGE_SOURCES_ROLES


@router.get("/habilitation", response_model=DianHabilitationProfileResponse | None)
def get_habilitation_profile(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    role = _company_for_role(company_id, user, db, VIEW_COMPANY_ROLES)
    profile = DianElectronicHabilitationService(db).get_profile(company_id)
    return (
        DianHabilitationProfileResponse.from_profile(
            profile,
            can_manage_habilitation=_can_manage_habilitation(user, role),
        )
        if profile
        else None
    )


@router.get("/habilitation/access", response_model=DianHabilitationAccessResponse)
def get_habilitation_access(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Expone solo el permiso de la pantalla, incluso antes de crear perfil."""

    user = _current_user(authorization, db)
    role = _company_for_role(company_id, user, db, VIEW_COMPANY_ROLES)
    return DianHabilitationAccessResponse(
        can_manage_habilitation=_can_manage_habilitation(user, role)
    )


@router.put("/habilitation", response_model=DianHabilitationProfileResponse)
def save_habilitation_profile(
    company_id: UUID,
    payload: DianHabilitationProfileWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    profile = DianElectronicHabilitationService(db).upsert_profile(
        company_id,
        actor_user_id=user.id,
        **payload.model_dump(),
    )
    return DianHabilitationProfileResponse.from_profile(profile, can_manage_habilitation=True)


@router.put("/technical-credentials", response_model=DianHabilitationProfileResponse)
def save_habilitation_technical_credentials(
    company_id: UUID,
    payload: DianTechnicalCredentialsWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Rota credenciales de habilitación sin devolver ni registrar secretos."""

    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    profile = DianElectronicHabilitationService(db).save_technical_credentials(
        company_id,
        actor_user_id=user.id,
        values=payload.plain_values(),
    )
    return DianHabilitationProfileResponse.from_profile(profile, can_manage_habilitation=True)


@router.put("/habilitation-parameters", response_model=DianHabilitationProfileResponse)
def save_habilitation_parameters(
    company_id: UUID,
    payload: DianHabilitationParametersWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Actualiza TestSetId y política XAdES sin reescribir el perfil fiscal."""

    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    profile = DianElectronicHabilitationService(db).save_habilitation_parameters(
        company_id,
        actor_user_id=user.id,
        **payload.model_dump(),
    )
    return DianHabilitationProfileResponse.from_profile(profile, can_manage_habilitation=True)


@router.delete("/technical-credentials", status_code=status.HTTP_204_NO_CONTENT)
def revoke_habilitation_technical_credentials(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Revoca la configuración técnica y cierra el envío de pruebas."""

    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    DianElectronicHabilitationService(db).revoke_technical_credentials(
        company_id,
        actor_user_id=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/numbering-ranges", response_model=list[DianNumberingRangeResponse])
def list_numbering_ranges(
    company_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, VIEW_COMPANY_ROLES)
    return [
        DianNumberingRangeResponse.from_range(item)
        for item in DianElectronicHabilitationService(db).list_numbering_ranges(company_id)
    ]


@router.post("/numbering-ranges", response_model=DianNumberingRangeResponse, status_code=201)
def create_numbering_range(
    company_id: UUID,
    payload: DianNumberingRangeWrite,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    item = DianElectronicHabilitationService(db).create_numbering_range(
        company_id,
        actor_user_id=user.id,
        **payload.model_dump(),
    )
    return DianNumberingRangeResponse.from_range(item)


@router.get("/test-documents", response_model=list[DianElectronicDocumentResponse])
def list_test_documents(
    company_id: UUID,
    limit: int = 50,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, VIEW_COMPANY_ROLES)
    return [
        DianElectronicDocumentResponse.from_document(item)
        for item in DianElectronicHabilitationService(db).list_documents(company_id, limit=limit)
    ]


@router.post("/test-documents", response_model=DianElectronicDocumentResponse, status_code=202)
async def upload_signed_test_document(
    company_id: UUID,
    file: UploadFile = File(...),
    prefix: str = Form(...),
    consecutive: int = Form(..., ge=1),
    issue_date: date = Form(...),
    document_type: Literal["invoice", "credit_note", "debit_note"] = Form(default="invoice"),
    currency_code: str = Form(default="COP"),
    payable_amount: str = Form(...),
    confirmed: bool = Form(...),
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, MANAGE_SOURCES_ROLES)
    content = await file.read(10_000_001)
    document = DianElectronicHabilitationService(db).create_signed_test_document(
        company_id,
        actor_user_id=user.id,
        file_name=file.filename or "",
        content=content,
        prefix=prefix,
        consecutive=consecutive,
        issue_date=issue_date,
        currency_code=currency_code,
        payable_amount=payable_amount,
        confirmed=confirmed,
        document_type=document_type,
        correlation_id=(x_request_id or "")[:64] or None,
    )
    return DianElectronicDocumentResponse.from_document(document)


@router.get("/test-documents/{document_id}/events", response_model=DianDocumentEventsResponse)
def list_test_document_events(
    company_id: UUID,
    document_id: UUID,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _current_user(authorization, db)
    _company_for_role(company_id, user, db, VIEW_COMPANY_ROLES)
    events = DianElectronicHabilitationService(db).list_document_events(company_id, document_id)
    return DianDocumentEventsResponse(
        items=[DianDocumentEventResponse.from_event(event) for event in events]
    )
