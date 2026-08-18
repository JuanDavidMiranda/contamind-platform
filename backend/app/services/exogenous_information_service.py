"""Diagnóstico determinista de preparación de datos para información exógena."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.exogenous_information.schemas import (
    ExogenousInformationFinding,
    ExogenousInformationMetrics,
    ExogenousInformationReport,
    ExogenousInformationSeverity,
    ExogenousInformationStatus,
    ExogenousInformationSummary,
)
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.data_source import PartyRecord


_CENT = Decimal("0.01")


@dataclass(frozen=True)
class ExogenousInformationExceptionItem:
    record_id: UUID
    record_type: str
    record_label: str
    record_date: date | None
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class ExogenousInformationExceptionsPage:
    tax_year: int
    total: int
    items: tuple[ExogenousInformationExceptionItem, ...]


class ExogenousInformationService:
    """Evalúa calidad de datos; no determina obligaciones ni interactúa con DIAN."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(
        self,
        company_id: UUID,
        *,
        tax_year: int | None = None,
    ) -> ExogenousInformationReport:
        year = self._tax_year(tax_year)
        metrics = self._metrics(str(company_id), year)
        findings = self._findings(metrics)
        summary = self._summary(findings)
        return ExogenousInformationReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def exceptions(
        self,
        company_id: UUID,
        *,
        tax_year: int | None = None,
        limit: int,
        offset: int,
    ) -> ExogenousInformationExceptionsPage:
        year = self._tax_year(tax_year)
        company_key = str(company_id)
        records: list[ExogenousInformationExceptionItem] = []
        for party in self._db.scalars(
            select(PartyRecord)
            .where(PartyRecord.company_id == company_key)
            .order_by(PartyRecord.id.asc())
        ):
            codes = self._party_codes(party)
            if codes:
                records.append(
                    ExogenousInformationExceptionItem(
                        record_id=UUID(party.id),
                        record_type="party",
                        record_label="Tercero con datos pendientes",
                        record_date=None,
                        issue_codes=tuple(codes),
                    )
                )
        for invoice in self._invoices(company_key, year):
            codes = self._invoice_codes(invoice)
            if codes:
                records.append(
                    ExogenousInformationExceptionItem(
                        record_id=UUID(invoice.id),
                        record_type="invoice",
                        record_label=(
                            f"Factura {invoice.number.strip()}"
                            if self._has_text(invoice.number)
                            else "Factura sin consecutivo"
                        ),
                        record_date=invoice.issue_date,
                        issue_codes=tuple(codes),
                    )
                )
        for payment in self._payments(company_key, year):
            if payment.invoice_id is None:
                records.append(
                    ExogenousInformationExceptionItem(
                        record_id=UUID(payment.id),
                        record_type="payment",
                        record_label="Pago sin factura vinculada",
                        record_date=payment.payment_date,
                        issue_codes=("PAYMENT_INVOICE_MISSING",),
                    )
                )
        ordered = tuple(
            sorted(
                records,
                key=lambda item: (
                    item.record_date is None,
                    item.record_date or date.min,
                    item.record_type,
                    str(item.record_id),
                ),
                reverse=True,
            )
        )
        return ExogenousInformationExceptionsPage(
            tax_year=year,
            total=len(ordered),
            items=ordered[offset:offset + limit],
        )

    def _metrics(self, company_id: str, tax_year: int) -> ExogenousInformationMetrics:
        parties = tuple(
            self._db.scalars(select(PartyRecord).where(PartyRecord.company_id == company_id))
        )
        invoices = self._invoices(company_id, tax_year)
        payments = self._payments(company_id, tax_year)
        complete_parties = sum(
            self._has_text(party.document_type) and self._has_text(party.document_number)
            for party in parties
        )
        missing_document_type = sum(not self._has_text(party.document_type) for party in parties)
        missing_document_number = sum(not self._has_text(party.document_number) for party in parties)
        missing_city = sum(not self._has_text(party.city) for party in parties)
        missing_address = sum(not self._has_text(party.address) for party in parties)
        coverage = (
            (Decimal(complete_parties) / Decimal(len(parties)) * Decimal("100")).quantize(_CENT)
            if parties
            else Decimal("0")
        )
        invoice_codes = [self._invoice_codes(invoice) for invoice in invoices]
        return ExogenousInformationMetrics(
            tax_year=tax_year,
            registered_parties=len(parties),
            parties_with_complete_identification=complete_parties,
            parties_missing_document_type=missing_document_type,
            parties_missing_document_number=missing_document_number,
            parties_missing_city=missing_city,
            parties_missing_address=missing_address,
            party_identification_coverage=coverage,
            invoices_in_tax_year=len(invoices),
            invoices_missing_number=sum("INVOICE_NUMBER_MISSING" in codes for codes in invoice_codes),
            invoices_missing_counterparty=sum("INVOICE_COUNTERPARTY_MISSING" in codes for codes in invoice_codes),
            invoices_with_total_mismatch=sum("INVOICE_TOTAL_MISMATCH" in codes for codes in invoice_codes),
            payments_in_tax_year=len(payments),
            payments_without_invoice=sum(payment.invoice_id is None for payment in payments),
        )

    @staticmethod
    def _findings(metrics: ExogenousInformationMetrics) -> list[ExogenousInformationFinding]:
        findings = [
            ExogenousInformationFinding(
                code="EXOGENA_OFFICIAL_RULES_NOT_CONFIGURED",
                severity=ExogenousInformationSeverity.INFO,
                message=(
                    "Esta revisión no determina formatos, conceptos ni obligación de presentación "
                    "ante la DIAN para el año gravable seleccionado."
                ),
                evidence={"tax_year": metrics.tax_year},
                recommendation=(
                    "Confirma la obligación y los formatos vigentes con el responsable tributario "
                    "antes de preparar archivos oficiales."
                ),
            ),
            ExogenousInformationFinding(
                code="EXOGENA_OFFICIAL_FILES_NOT_GENERATED",
                severity=ExogenousInformationSeverity.INFO,
                message="La aplicación no genera, firma, transmite ni presenta archivos de información exógena.",
                evidence={"tax_year": metrics.tax_year},
                recommendation="Usa este diagnóstico para depurar datos antes de una preparación autorizada de archivos.",
            ),
        ]
        if not metrics.registered_parties:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_NO_PARTIES_REGISTERED",
                    severity=ExogenousInformationSeverity.WARNING,
                    message="No hay terceros registrados para revisar su preparación de datos.",
                    evidence={"parties": 0},
                    recommendation="Importa o registra los terceros desde una fuente autorizada antes de preparar información exógena.",
                )
            )
        if metrics.parties_missing_document_type or metrics.parties_missing_document_number:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_PARTIES_MISSING_IDENTIFICATION",
                    severity=ExogenousInformationSeverity.CRITICAL,
                    message="Hay terceros sin tipo o número de documento registrado.",
                    evidence={
                        "missing_document_type": metrics.parties_missing_document_type,
                        "missing_document_number": metrics.parties_missing_document_number,
                    },
                    recommendation="Completa la identificación de los terceros en la fuente autorizada antes de clasificarlos en cualquier formato oficial.",
                )
            )
        if metrics.parties_missing_city or metrics.parties_missing_address:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_PARTIES_MISSING_LOCATION",
                    severity=ExogenousInformationSeverity.WARNING,
                    message="Hay terceros sin ciudad o dirección registrada.",
                    evidence={
                        "missing_city": metrics.parties_missing_city,
                        "missing_address": metrics.parties_missing_address,
                    },
                    recommendation="Completa la ubicación que requiera la fuente contable o la parametrización tributaria aplicable.",
                )
            )
        if metrics.invoices_missing_number or metrics.invoices_missing_counterparty:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_INVOICES_MISSING_TRACEABILITY",
                    severity=ExogenousInformationSeverity.WARNING,
                    message="Hay facturas del año gravable sin consecutivo o sin contraparte asociada.",
                    evidence={
                        "missing_number": metrics.invoices_missing_number,
                        "missing_counterparty": metrics.invoices_missing_counterparty,
                    },
                    recommendation="Relaciona consecutivo y tercero en la fuente contable antes de usar estos movimientos para una preparación fiscal.",
                )
            )
        if metrics.invoices_with_total_mismatch:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_INVOICES_WITH_TOTAL_MISMATCH",
                    severity=ExogenousInformationSeverity.CRITICAL,
                    message="Hay facturas cuyo total no coincide con subtotal, impuestos y retenciones registrados.",
                    evidence={"invoices": metrics.invoices_with_total_mismatch},
                    recommendation="Revisa los importes contables antes de clasificar o consolidar movimientos para información exógena.",
                )
            )
        if metrics.payments_without_invoice:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_PAYMENTS_WITHOUT_INVOICE",
                    severity=ExogenousInformationSeverity.WARNING,
                    message="Hay pagos del año gravable sin una factura vinculada.",
                    evidence={"payments": metrics.payments_without_invoice},
                    recommendation="Relaciona cada pago con su soporte contable cuando corresponda, antes de consolidar datos tributarios.",
                )
            )
        if not metrics.invoices_in_tax_year and not metrics.payments_in_tax_year:
            findings.append(
                ExogenousInformationFinding(
                    code="EXOGENA_NO_FISCAL_YEAR_MOVEMENTS",
                    severity=ExogenousInformationSeverity.INFO,
                    message="No hay facturas ni pagos registrados para el año gravable seleccionado.",
                    evidence={"tax_year": metrics.tax_year},
                    recommendation="Confirma que las fuentes contables incluyan el período antes de evaluar preparación de datos.",
                )
            )
        return findings

    @staticmethod
    def _summary(findings: list[ExogenousInformationFinding]) -> ExogenousInformationSummary:
        critical = sum(item.severity is ExogenousInformationSeverity.CRITICAL for item in findings)
        warning = sum(item.severity is ExogenousInformationSeverity.WARNING for item in findings)
        info = sum(item.severity is ExogenousInformationSeverity.INFO for item in findings)
        status = (
            ExogenousInformationStatus.CRITICAL
            if critical
            else ExogenousInformationStatus.NEEDS_ATTENTION
            if warning
            else ExogenousInformationStatus.HEALTHY
        )
        return ExogenousInformationSummary(
            status=status,
            finding_count=len(findings),
            critical_count=critical,
            warning_count=warning,
            info_count=info,
        )

    def _invoices(self, company_id: str, tax_year: int) -> tuple[InvoiceRecord, ...]:
        return tuple(
            self._db.scalars(
                select(InvoiceRecord)
                .where(
                    InvoiceRecord.company_id == company_id,
                    InvoiceRecord.issue_date >= date(tax_year, 1, 1),
                    InvoiceRecord.issue_date <= date(tax_year, 12, 31),
                )
                .order_by(InvoiceRecord.issue_date.desc(), InvoiceRecord.id.asc())
            )
        )

    def _payments(self, company_id: str, tax_year: int) -> tuple[PaymentRecord, ...]:
        return tuple(
            self._db.scalars(
                select(PaymentRecord)
                .where(
                    PaymentRecord.company_id == company_id,
                    PaymentRecord.payment_date >= date(tax_year, 1, 1),
                    PaymentRecord.payment_date <= date(tax_year, 12, 31),
                )
                .order_by(PaymentRecord.payment_date.desc(), PaymentRecord.id.asc())
            )
        )

    @staticmethod
    def _party_codes(party: PartyRecord) -> list[str]:
        codes = []
        if not ExogenousInformationService._has_text(party.document_type):
            codes.append("PARTY_DOCUMENT_TYPE_MISSING")
        if not ExogenousInformationService._has_text(party.document_number):
            codes.append("PARTY_DOCUMENT_NUMBER_MISSING")
        if not ExogenousInformationService._has_text(party.city):
            codes.append("PARTY_CITY_MISSING")
        if not ExogenousInformationService._has_text(party.address):
            codes.append("PARTY_ADDRESS_MISSING")
        return codes

    @staticmethod
    def _invoice_codes(invoice: InvoiceRecord) -> list[str]:
        codes = []
        if not ExogenousInformationService._has_text(invoice.number):
            codes.append("INVOICE_NUMBER_MISSING")
        counterparty_id = (
            invoice.recipient_party_id if invoice.invoice_type == "sale" else invoice.issuer_party_id
        )
        if counterparty_id is None:
            codes.append("INVOICE_COUNTERPARTY_MISSING")
        expected_total = (
            Decimal(invoice.subtotal) + Decimal(invoice.tax_total) - Decimal(invoice.withholding_total)
        ).quantize(_CENT)
        if Decimal(invoice.total).quantize(_CENT) != expected_total:
            codes.append("INVOICE_TOTAL_MISMATCH")
        return codes

    @staticmethod
    def _has_text(value: str | None) -> bool:
        return bool(value and value.strip())

    @staticmethod
    def _tax_year(value: int | None) -> int:
        year = value if value is not None else datetime.now(UTC).year
        if not 2000 <= year <= 2100:
            raise ValueError("El año gravable debe estar entre 2000 y 2100.")
        return year
