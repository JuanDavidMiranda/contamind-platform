"""Análisis determinista y de solo lectura de la salud contable por empresa."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.ai.agents.accounting_health.schemas import (
    AccountingHealthFinding,
    AccountingHealthMetrics,
    AccountingHealthReport,
    AccountingHealthSeverity,
    AccountingHealthStatus,
    AccountingHealthSummary,
)
from app.models.accounting import (
    InvoiceRecord,
    ItemRecord,
    JournalEntryLineRecord,
    JournalEntryRecord,
    PaymentRecord,
    TaxRecord,
)
from app.models.data_source import CompanyDataSourceRecord, ImportBatchRecord, PartyRecord


class AccountingHealthService:
    """Lee agregados por empresa y nunca devuelve filas con datos personales."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(self, company_id: UUID) -> AccountingHealthReport:
        company_key = str(company_id)
        metrics = self._metrics(company_key)
        findings = self._findings(company_key, metrics)
        summary = self._summary(findings)
        return AccountingHealthReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _metrics(self, company_id: str) -> AccountingHealthMetrics:
        accepted_rows, rejected_rows = self._db.execute(
            select(
                func.coalesce(func.sum(ImportBatchRecord.accepted_rows), 0),
                func.coalesce(func.sum(ImportBatchRecord.rejected_rows), 0),
            ).where(ImportBatchRecord.company_id == company_id)
        ).one()
        return AccountingHealthMetrics(
            data_sources=self._count(CompanyDataSourceRecord, company_id),
            active_data_sources=self._count(
                CompanyDataSourceRecord,
                company_id,
                CompanyDataSourceRecord.status == "active",
            ),
            import_batches=self._count(ImportBatchRecord, company_id),
            accepted_import_rows=int(accepted_rows or 0),
            rejected_import_rows=int(rejected_rows or 0),
            parties=self._count(PartyRecord, company_id),
            taxes=self._count(TaxRecord, company_id),
            items=self._count(ItemRecord, company_id),
            invoices=self._count(InvoiceRecord, company_id),
            payments=self._count(PaymentRecord, company_id),
            journal_entries=self._count(JournalEntryRecord, company_id),
        )

    def _findings(
        self, company_id: str, metrics: AccountingHealthMetrics
    ) -> list[AccountingHealthFinding]:
        findings: list[AccountingHealthFinding] = []
        if metrics.active_data_sources == 0:
            findings.append(
                self._finding(
                    "NO_ACTIVE_DATA_SOURCE",
                    AccountingHealthSeverity.INFO,
                    "No hay fuentes de datos activas para la empresa.",
                    {"data_sources": metrics.data_sources},
                    "Configura o reactiva una fuente antes de confiar en la cobertura contable.",
                )
            )
        if metrics.parties + metrics.invoices + metrics.payments + metrics.journal_entries == 0:
            findings.append(
                self._finding(
                    "NO_ACCOUNTING_DATA",
                    AccountingHealthSeverity.INFO,
                    "Aún no hay movimientos ni terceros contables para analizar.",
                    {"accounting_records": 0},
                    "Importa o captura información contable para obtener un diagnóstico útil.",
                )
            )

        failed_sources = self._count(
            CompanyDataSourceRecord,
            company_id,
            CompanyDataSourceRecord.status.in_(("failed", "disabled")),
        )
        if failed_sources:
            findings.append(
                self._finding(
                    "SOURCE_NOT_READY",
                    AccountingHealthSeverity.WARNING,
                    "Hay fuentes que no están disponibles para aportar datos.",
                    {"sources": failed_sources},
                    "Revisa sus credenciales, configuración o estado antes de la siguiente operación.",
                )
            )

        rejected_batches, rejected_rows = self._db.execute(
            select(
                func.count(ImportBatchRecord.id),
                func.coalesce(func.sum(ImportBatchRecord.rejected_rows), 0),
            ).where(
                ImportBatchRecord.company_id == company_id,
                ImportBatchRecord.rejected_rows > 0,
            )
        ).one()
        if rejected_batches:
            findings.append(
                self._finding(
                    "IMPORT_REJECTIONS",
                    AccountingHealthSeverity.WARNING,
                    "Algunas filas de importación fueron rechazadas.",
                    {"batches": int(rejected_batches), "rows": int(rejected_rows or 0)},
                    "Corrige las filas rechazadas y vuelve a importarlas con el perfil correspondiente.",
                )
            )

        parties_without_document = self._count(
            PartyRecord,
            company_id,
            or_(
                self._missing_text(PartyRecord.document_type),
                self._missing_text(PartyRecord.document_number),
            ),
        )
        if parties_without_document:
            findings.append(
                self._finding(
                    "PARTIES_MISSING_TAX_ID",
                    AccountingHealthSeverity.WARNING,
                    "Hay terceros sin tipo o número de documento.",
                    {"parties": parties_without_document},
                    "Completa la identificación tributaria de esos terceros antes de procesos fiscales.",
                )
            )

        duplicate_groups, duplicate_records = self._duplicate_party_documents(company_id)
        if duplicate_groups:
            findings.append(
                self._finding(
                    "DUPLICATE_PARTY_DOCUMENT",
                    AccountingHealthSeverity.WARNING,
                    "Hay documentos de terceros repetidos dentro de la empresa.",
                    {"groups": duplicate_groups, "extra_records": duplicate_records},
                    "Revisa y consolida los terceros duplicados antes de sincronizar o generar reportes.",
                )
            )

        items_without_account = self._count(
            ItemRecord,
            company_id,
            self._missing_text(ItemRecord.ledger_account),
        )
        if items_without_account:
            findings.append(
                self._finding(
                    "ITEMS_WITHOUT_LEDGER_ACCOUNT",
                    AccountingHealthSeverity.WARNING,
                    "Hay ítems sin cuenta contable configurada.",
                    {"items": items_without_account},
                    "Asigna una cuenta contable a esos ítems antes de automatizar su contabilización.",
                )
            )

        invoices_without_party = self._count(
            InvoiceRecord,
            company_id,
            or_(
                and_(
                    InvoiceRecord.invoice_type == "sale",
                    InvoiceRecord.recipient_party_id.is_(None),
                ),
                and_(
                    InvoiceRecord.invoice_type == "purchase",
                    InvoiceRecord.issuer_party_id.is_(None),
                ),
            ),
        )
        if invoices_without_party:
            findings.append(
                self._finding(
                    "INVOICE_PARTY_MISSING",
                    AccountingHealthSeverity.WARNING,
                    "Hay facturas sin la contraparte esperada para su tipo.",
                    {"invoices": invoices_without_party},
                    "Relaciona cada factura con su cliente o proveedor antes de usarla en reportes.",
                )
            )

        unlinked_payments = self._count(
            PaymentRecord,
            company_id,
            PaymentRecord.invoice_id.is_(None),
        )
        if unlinked_payments:
            findings.append(
                self._finding(
                    "UNLINKED_PAYMENTS",
                    AccountingHealthSeverity.INFO,
                    "Hay pagos sin una factura asociada.",
                    {"payments": unlinked_payments},
                    "Confirma si son anticipos válidos o relaciónalos con la factura correspondiente.",
                )
            )

        unbalanced_journals = self._unbalanced_journal_count(company_id)
        if unbalanced_journals:
            findings.append(
                self._finding(
                    "UNBALANCED_JOURNAL",
                    AccountingHealthSeverity.CRITICAL,
                    "Hay comprobantes cuyo débito y crédito no cuadran.",
                    {"journal_entries": unbalanced_journals},
                    "Corrige esos comprobantes antes de cualquier cierre o reporte financiero.",
                )
            )
        return findings

    def _count(self, model, company_id: str, *conditions) -> int:
        return int(
            self._db.scalar(
                select(func.count(model.id)).where(model.company_id == company_id, *conditions)
            )
            or 0
        )

    def _duplicate_party_documents(self, company_id: str) -> tuple[int, int]:
        groups = list(
            self._db.execute(
                select(func.count(PartyRecord.id))
                .where(
                    PartyRecord.company_id == company_id,
                    PartyRecord.document_type.is_not(None),
                    PartyRecord.document_number.is_not(None),
                    func.trim(PartyRecord.document_type) != "",
                    func.trim(PartyRecord.document_number) != "",
                )
                .group_by(PartyRecord.document_type, PartyRecord.document_number)
                .having(func.count(PartyRecord.id) > 1)
            ).scalars()
        )
        return len(groups), sum(int(count) - 1 for count in groups)

    def _unbalanced_journal_count(self, company_id: str) -> int:
        return len(
            list(
                self._db.scalars(
                    select(JournalEntryRecord.id)
                    .outerjoin(
                        JournalEntryLineRecord,
                        JournalEntryLineRecord.journal_entry_id == JournalEntryRecord.id,
                    )
                    .where(JournalEntryRecord.company_id == company_id)
                    .group_by(JournalEntryRecord.id)
                    .having(
                        func.coalesce(func.sum(JournalEntryLineRecord.debit), 0)
                        != func.coalesce(func.sum(JournalEntryLineRecord.credit), 0)
                    )
                )
            )
        )

    @staticmethod
    def _missing_text(column):
        return or_(column.is_(None), func.trim(column) == "")

    @staticmethod
    def _finding(
        code: str,
        severity: AccountingHealthSeverity,
        message: str,
        evidence: dict[str, int],
        recommendation: str,
    ) -> AccountingHealthFinding:
        return AccountingHealthFinding(
            code=code,
            severity=severity,
            message=message,
            evidence=evidence,
            recommendation=recommendation,
        )

    @staticmethod
    def _summary(findings: list[AccountingHealthFinding]) -> AccountingHealthSummary:
        critical_count = sum(
            finding.severity is AccountingHealthSeverity.CRITICAL for finding in findings
        )
        warning_count = sum(
            finding.severity is AccountingHealthSeverity.WARNING for finding in findings
        )
        info_count = sum(finding.severity is AccountingHealthSeverity.INFO for finding in findings)
        status = (
            AccountingHealthStatus.CRITICAL
            if critical_count
            else AccountingHealthStatus.NEEDS_ATTENTION
            if warning_count
            else AccountingHealthStatus.HEALTHY
        )
        return AccountingHealthSummary(
            status=status,
            finding_count=len(findings),
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
        )
