"""Diagnóstico agregado de evidencia de facturación electrónica."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.electronic_invoicing.schemas import (
    ElectronicInvoicingFinding,
    ElectronicInvoicingMetrics,
    ElectronicInvoicingReport,
    ElectronicInvoicingSeverity,
    ElectronicInvoicingStatus,
    ElectronicInvoicingSummary,
)
from app.models.accounting import InvoiceRecord


_CENT = Decimal("0.01")
_ACCEPTED_STATUSES = frozenset({"accepted", "validated", "approved", "dian_accepted"})
_PENDING_STATUSES = frozenset({"draft", "issued", "sent", "submitted", "pending", "processing"})
_REJECTED_STATUSES = frozenset({"rejected", "error", "failed", "invalid"})


class ElectronicInvoicingService:
    """Lee evidencia importada; no consulta, transmite ni modifica datos de DIAN."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(
        self,
        company_id: UUID,
        *,
        as_of: date | None = None,
    ) -> ElectronicInvoicingReport:
        analysis_date = as_of or datetime.now(UTC).date()
        metrics = self._metrics(str(company_id), analysis_date)
        findings = self._findings(metrics)
        summary = self._summary(findings)
        return ElectronicInvoicingReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _metrics(self, company_id: str, as_of: date) -> ElectronicInvoicingMetrics:
        rows = self._db.execute(
            select(
                InvoiceRecord.issue_date,
                InvoiceRecord.number,
                InvoiceRecord.recipient_party_id,
                InvoiceRecord.subtotal,
                InvoiceRecord.tax_total,
                InvoiceRecord.withholding_total,
                InvoiceRecord.total,
                InvoiceRecord.electronic_status,
                InvoiceRecord.electronic_reference,
            ).where(
                InvoiceRecord.company_id == company_id,
                InvoiceRecord.invoice_type == "sale",
            )
        ).all()
        accepted = pending = rejected = without_status = 0
        without_reference = missing_number = without_recipient = total_mismatch = future_dated = 0

        for row in rows:
            status = self._normalize_status(row.electronic_status)
            if status in _ACCEPTED_STATUSES:
                accepted += 1
            elif status in _PENDING_STATUSES:
                pending += 1
            elif status in _REJECTED_STATUSES:
                rejected += 1
            else:
                without_status += 1
            if not self._has_text(row.electronic_reference):
                without_reference += 1
            if not self._has_text(row.number):
                missing_number += 1
            if row.recipient_party_id is None:
                without_recipient += 1
            expected_total = (
                Decimal(row.subtotal) + Decimal(row.tax_total) - Decimal(row.withholding_total)
            ).quantize(_CENT)
            if Decimal(row.total).quantize(_CENT) != expected_total:
                total_mismatch += 1
            if row.issue_date > as_of:
                future_dated += 1

        recorded = accepted + pending + rejected
        coverage = (
            (Decimal(recorded) / Decimal(len(rows)) * Decimal("100")).quantize(_CENT)
            if rows
            else Decimal("0")
        )
        return ElectronicInvoicingMetrics(
            as_of_date=as_of,
            sales_invoices=len(rows),
            electronic_status_recorded=recorded,
            accepted_electronic_invoices=accepted,
            pending_electronic_invoices=pending,
            rejected_electronic_invoices=rejected,
            invoices_without_electronic_status=without_status,
            invoices_without_electronic_reference=without_reference,
            invoices_missing_number=missing_number,
            invoices_without_recipient=without_recipient,
            invoices_with_total_mismatch=total_mismatch,
            future_dated_sales_invoices=future_dated,
            electronic_status_coverage=coverage,
        )

    @staticmethod
    def _findings(metrics: ElectronicInvoicingMetrics) -> list[ElectronicInvoicingFinding]:
        findings: list[ElectronicInvoicingFinding] = [
            ElectronicInvoicingFinding(
                code="DIAN_CONNECTION_NOT_CONFIGURED",
                severity=ElectronicInvoicingSeverity.INFO,
                message="Este diagnóstico no se conecta en tiempo real con la DIAN ni envía documentos electrónicos.",
                evidence={"invoices": metrics.sales_invoices},
                recommendation="Usa los estados importados como evidencia operativa y confirma los casos críticos en tu proveedor electrónico hasta habilitar la integración DIAN.",
            )
        ]
        if not metrics.sales_invoices:
            findings.append(
                ElectronicInvoicingFinding(
                    code="NO_SALES_INVOICES_FOR_ELECTRONIC_REVIEW",
                    severity=ElectronicInvoicingSeverity.INFO,
                    message="No hay facturas de venta para revisar evidencia de facturación electrónica.",
                    evidence={"invoices": 0},
                    recommendation="Importa o registra las facturas de venta antes de medir su estado electrónico.",
                )
            )
            return findings
        if metrics.rejected_electronic_invoices:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICES_REJECTED",
                    severity=ElectronicInvoicingSeverity.CRITICAL,
                    message="Hay facturas de venta con estado electrónico rechazado o con error.",
                    evidence={"invoices": metrics.rejected_electronic_invoices},
                    recommendation="Revisa las validaciones del proveedor y corrige los datos antes de reenviar desde el proceso autorizado.",
                )
            )
        if metrics.pending_electronic_invoices:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICES_PENDING",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas con estado electrónico pendiente de confirmación.",
                    evidence={"invoices": metrics.pending_electronic_invoices},
                    recommendation="Confirma el resultado en la fuente que reportó el documento antes de considerarlo validado.",
                )
            )
        if metrics.invoices_without_electronic_status:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_STATUS_MISSING",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas de venta sin estado electrónico importado.",
                    evidence={"invoices": metrics.invoices_without_electronic_status},
                    recommendation="Completa o sincroniza el estado electrónico desde la fuente autorizada antes de medir cumplimiento.",
                )
            )
        if metrics.invoices_without_electronic_reference:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_REFERENCE_MISSING",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas sin referencia electrónica registrada, como CUFE, CUDE o identificador equivalente.",
                    evidence={"invoices": metrics.invoices_without_electronic_reference},
                    recommendation="Importa la referencia emitida por tu proveedor para conservar trazabilidad, sin compartirla en este chat.",
                )
            )
        if metrics.invoices_missing_number:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICES_MISSING_NUMBER",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas de venta sin consecutivo o número registrado.",
                    evidence={"invoices": metrics.invoices_missing_number},
                    recommendation="Completa el consecutivo desde la fuente contable antes de revisar su trazabilidad electrónica.",
                )
            )
        if metrics.invoices_without_recipient:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICES_WITHOUT_RECIPIENT",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas de venta sin un adquiriente asociado.",
                    evidence={"invoices": metrics.invoices_without_recipient},
                    recommendation="Completa el tercero en la fuente autorizada antes de reenviar o usar el documento como soporte.",
                )
            )
        if metrics.invoices_with_total_mismatch:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICE_TOTAL_MISMATCH",
                    severity=ElectronicInvoicingSeverity.CRITICAL,
                    message="Hay facturas cuyo total no coincide con subtotal, impuestos y retenciones registrados.",
                    evidence={"invoices": metrics.invoices_with_total_mismatch},
                    recommendation="Revisa los importes y los impuestos en la fuente contable antes de emitir o corregir documentos.",
                )
            )
        if metrics.future_dated_sales_invoices:
            findings.append(
                ElectronicInvoicingFinding(
                    code="ELECTRONIC_INVOICES_FUTURE_DATED",
                    severity=ElectronicInvoicingSeverity.WARNING,
                    message="Hay facturas de venta con fecha de emisión posterior al corte del diagnóstico.",
                    evidence={"invoices": metrics.future_dated_sales_invoices},
                    recommendation="Confirma la fecha contable y la fecha electrónica antes de transmitir o contabilizar ajustes.",
                )
            )
        return findings

    @staticmethod
    def _summary(findings: list[ElectronicInvoicingFinding]) -> ElectronicInvoicingSummary:
        critical = sum(item.severity is ElectronicInvoicingSeverity.CRITICAL for item in findings)
        warning = sum(item.severity is ElectronicInvoicingSeverity.WARNING for item in findings)
        info = sum(item.severity is ElectronicInvoicingSeverity.INFO for item in findings)
        status = (
            ElectronicInvoicingStatus.CRITICAL
            if critical
            else ElectronicInvoicingStatus.NEEDS_ATTENTION
            if warning
            else ElectronicInvoicingStatus.HEALTHY
        )
        return ElectronicInvoicingSummary(
            status=status,
            finding_count=len(findings),
            critical_count=critical,
            warning_count=warning,
            info_count=info,
        )

    @staticmethod
    def _normalize_status(value: str | None) -> str:
        return value.strip().casefold().replace("-", "_").replace(" ", "_") if value else ""

    @staticmethod
    def _has_text(value: str | None) -> bool:
        return bool(value and value.strip())
