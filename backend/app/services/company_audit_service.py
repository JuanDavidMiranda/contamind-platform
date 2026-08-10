"""Consulta de la trazabilidad operativa de una empresa."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_source import CompanyDataSourceRecord, ImportBatchRecord, PartyRecord


class CompanyAuditService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def sources(self, company_id: str) -> list[CompanyDataSourceRecord]:
        return list(
            self._db.scalars(
                select(CompanyDataSourceRecord)
                .where(CompanyDataSourceRecord.company_id == company_id)
                .order_by(CompanyDataSourceRecord.created_at.desc())
            )
        )

    def imports(self, company_id: str) -> list[ImportBatchRecord]:
        return list(
            self._db.scalars(
                select(ImportBatchRecord)
                .where(ImportBatchRecord.company_id == company_id)
                .order_by(ImportBatchRecord.created_at.desc())
            )
        )

    def manual_parties(self, company_id: str) -> list[PartyRecord]:
        return list(
            self._db.scalars(
                select(PartyRecord)
                .join(CompanyDataSourceRecord, PartyRecord.data_source_id == CompanyDataSourceRecord.id)
                .where(
                    PartyRecord.company_id == company_id,
                    CompanyDataSourceRecord.kind == "manual_entry",
                )
                .order_by(PartyRecord.updated_at.desc())
            )
        )
