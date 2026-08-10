"""Casos de uso para el ciclo de vida de tenants y empresas."""

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.organization import CompanyRecord, TenantMembership, TenantRecord, TenantRole
from app.models.user import CompanyMembership, CompanyRole, User
from app.providers.canonical import Company, CompanyStatus, Tenant
from app.shared.errors import app_error


class CompanyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def onboard_company(
        self,
        user: User,
        *,
        tenant_name: str,
        country_code: str,
        company_name: str,
        functional_currency: str,
        provider_company_id: str | None,
    ) -> tuple[Tenant, Company]:
        """Crea tenant, empresa y su primer propietario en una transacción."""

        tenant = Tenant(name=tenant_name, country_code=country_code)
        company = Company(
            tenant_id=tenant.id,
            name=company_name,
            functional_currency=functional_currency,
            provider_company_id=provider_company_id,
        )
        self._db.add(
            TenantRecord(
                id=str(tenant.id),
                name=tenant.name,
                country_code=tenant.country_code,
            )
        )
        self._db.add(
            CompanyRecord(
                id=str(company.id),
                tenant_id=str(company.tenant_id),
                name=company.name,
                functional_currency=company.functional_currency,
                provider_company_id=company.provider_company_id,
            )
        )
        self._db.add(
            CompanyMembership(
                user_id=user.id,
                company_id=str(company.id),
                role=CompanyRole.OWNER.value,
            )
        )
        self._db.add(
            TenantMembership(
                user_id=user.id,
                tenant_id=str(tenant.id),
                role=TenantRole.OWNER.value,
            )
        )
        self._db.commit()
        return tenant, company

    def create_company_in_tenant(
        self,
        user: User,
        *,
        tenant_id: UUID,
        name: str,
        functional_currency: str,
        provider_company_id: str | None,
    ) -> Company:
        self.get_tenant(tenant_id)
        company = Company(
            tenant_id=tenant_id,
            name=name,
            functional_currency=functional_currency,
            provider_company_id=provider_company_id,
        )
        self._db.add(
            CompanyRecord(
                id=str(company.id),
                tenant_id=str(company.tenant_id),
                name=company.name,
                functional_currency=company.functional_currency,
                provider_company_id=company.provider_company_id,
                status=company.status.value,
            )
        )
        self._db.add(
            CompanyMembership(
                user_id=user.id,
                company_id=str(company.id),
                role=CompanyRole.OWNER.value,
            )
        )
        self._db.commit()
        return company

    def get_tenant(self, tenant_id: UUID) -> Tenant:
        record = self._db.get(TenantRecord, str(tenant_id))
        if record is None:
            raise app_error("NOT_FOUND", message="Tenant no encontrado.")
        return Tenant(id=UUID(record.id), name=record.name, country_code=record.country_code)

    def get_company(self, company_id: UUID) -> Company:
        record = self._db.get(CompanyRecord, str(company_id))
        if record is None:
            raise app_error("NOT_FOUND", message="Empresa no encontrada.")
        return self._company_from_record(record)

    def require_company_in_tenant(self, company_id: UUID, tenant_id: UUID) -> Company:
        company = self.get_company(company_id)
        if company.tenant_id != tenant_id:
            raise app_error(
                "CONFLICT",
                message="La empresa no pertenece al tenant indicado.",
            )
        return company

    def require_active_company(self, company_id: UUID) -> Company:
        company = self.get_company(company_id)
        if company.status is CompanyStatus.DISABLED:
            raise app_error("CONFLICT", message="La empresa está desactivada.")
        return company

    def update_company(
        self,
        company_id: UUID,
        *,
        name: str | None = None,
        functional_currency: str | None = None,
        provider_company_id: str | None = None,
        update_provider_company_id: bool = False,
    ) -> Company:
        record = self._get_company_record(company_id)
        if name is not None:
            record.name = name
        if functional_currency is not None:
            record.functional_currency = functional_currency
        if update_provider_company_id:
            record.provider_company_id = provider_company_id
        self._db.commit()
        self._db.refresh(record)
        return self._company_from_record(record)

    def set_company_status(self, company_id: UUID, status: CompanyStatus) -> Company:
        record = self._get_company_record(company_id)
        record.status = status.value
        self._db.commit()
        self._db.refresh(record)
        return self._company_from_record(record)

    def list_companies_for_user(self, user: User) -> list[Company]:
        statement = select(CompanyRecord).order_by(CompanyRecord.name)
        if not user.is_platform_admin:
            statement = (
                statement.outerjoin(
                    CompanyMembership,
                    and_(
                        CompanyMembership.company_id == CompanyRecord.id,
                        CompanyMembership.user_id == user.id,
                    ),
                )
                .outerjoin(
                    TenantMembership,
                    and_(
                        TenantMembership.tenant_id == CompanyRecord.tenant_id,
                        TenantMembership.user_id == user.id,
                        TenantMembership.role == TenantRole.OWNER.value,
                    ),
                )
                .where(or_(CompanyMembership.id.is_not(None), TenantMembership.id.is_not(None)))
                .distinct()
            )
        records = self._db.scalars(statement)
        return [self._company_from_record(record) for record in records]

    @staticmethod
    def _company_from_record(record: CompanyRecord) -> Company:
        return Company(
            id=UUID(record.id),
            tenant_id=UUID(record.tenant_id),
            name=record.name,
            functional_currency=record.functional_currency,
            provider_company_id=record.provider_company_id,
            status=CompanyStatus(record.status),
        )

    def _get_company_record(self, company_id: UUID) -> CompanyRecord:
        record = self._db.get(CompanyRecord, str(company_id))
        if record is None:
            raise app_error("NOT_FOUND", message="Empresa no encontrada.")
        return record
