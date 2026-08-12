"""Cobertura conversacional determinista del agente de cartera.

Estas pruebas mantienen el contrato de lectura agregada del chat. El detalle de
facturas, clientes y pagos sigue perteneciendo a Cartera operativa, no a esta
capa conversacional.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.ai.agents.receivables.agent import ReceivablesAgent
from app.ai.agents.receivables.schemas import (
    ReceivablesAgingBucket,
    ReceivablesBalance,
    ReceivablesConversationOutcome,
    ReceivablesFinding,
    ReceivablesMetrics,
    ReceivablesReport,
    ReceivablesSeverity,
    ReceivablesStatus,
    ReceivablesSummary,
)


pytestmark = pytest.mark.unit


def _finding(code: str, severity: ReceivablesSeverity, message: str) -> ReceivablesFinding:
    return ReceivablesFinding(
        code=code,
        severity=severity,
        message=message,
        evidence={"items": 1},
        recommendation="Revisa el agregado antes de continuar con la gestión.",
    )


@pytest.fixture
def rich_report() -> ReceivablesReport:
    """Escenario que contiene todos los agregados que el chat puede explicar."""

    return ReceivablesReport(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        generated_at=datetime(2026, 8, 12, tzinfo=UTC),
        overall_status=ReceivablesStatus.CRITICAL,
        summary=ReceivablesSummary(
            status=ReceivablesStatus.CRITICAL,
            finding_count=10,
            critical_count=1,
            warning_count=7,
            info_count=2,
        ),
        metrics=ReceivablesMetrics(
            as_of_date=datetime(2026, 8, 12, tzinfo=UTC).date(),
            sales_invoices=12,
            open_sales_invoices=10,
            unpaid_sales_invoices=5,
            partially_paid_sales_invoices=5,
            overpaid_sales_invoices=1,
            payments_with_currency_mismatch=2,
            sales_invoices_missing_due_date=2,
            due_today_sales_invoices=1,
            overdue_sales_invoices=5,
            seriously_overdue_sales_invoices=2,
            pending_collection_followups=3,
            open_payment_promises=2,
            broken_payment_promises=1,
            settled_sales_invoices=1,
            average_days_to_collect=Decimal("17.50"),
            outstanding_balances=(
                ReceivablesBalance(currency_code="COP", amount=Decimal("1234.50")),
                ReceivablesBalance(currency_code="USD", amount=Decimal("99.50")),
            ),
            aging_buckets=(
                ReceivablesAgingBucket(
                    key="not_due",
                    invoices=2,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="COP", amount=Decimal("300.00")),
                    ),
                ),
                ReceivablesAgingBucket(
                    key="due_today",
                    invoices=1,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="COP", amount=Decimal("100.00")),
                    ),
                ),
                ReceivablesAgingBucket(
                    key="overdue_1_30",
                    invoices=2,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="COP", amount=Decimal("250.00")),
                    ),
                ),
                ReceivablesAgingBucket(
                    key="overdue_31_60",
                    invoices=1,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="COP", amount=Decimal("200.00")),
                    ),
                ),
                ReceivablesAgingBucket(
                    key="overdue_91_plus",
                    invoices=2,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="COP", amount=Decimal("384.50")),
                    ),
                ),
                ReceivablesAgingBucket(
                    key="missing_due_date",
                    invoices=2,
                    outstanding_balances=(
                        ReceivablesBalance(currency_code="USD", amount=Decimal("99.50")),
                    ),
                ),
            ),
        ),
        findings=(
            _finding(
                "UNPAID_SALES_INVOICES",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta sin pagos registrados.",
            ),
            _finding(
                "PARTIALLY_PAID_SALES_INVOICES",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta con pagos parciales.",
            ),
            _finding(
                "OVERPAID_SALES_INVOICES",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta con pagos superiores al total.",
            ),
            _finding(
                "SALES_INVOICES_MISSING_DUE_DATE",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta sin fecha de vencimiento verificable.",
            ),
            _finding(
                "OVERDUE_SALES_INVOICES",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta vencidas con saldo pendiente.",
            ),
            _finding(
                "SERIOUSLY_OVERDUE_SALES_INVOICES",
                ReceivablesSeverity.CRITICAL,
                "Hay cartera vencida por más de noventa días.",
            ),
            _finding(
                "BROKEN_PAYMENT_PROMISES",
                ReceivablesSeverity.WARNING,
                "Hay promesas de pago cuya fecha ya pasó.",
            ),
            _finding(
                "OPEN_PAYMENT_PROMISES",
                ReceivablesSeverity.INFO,
                "Hay promesas de pago activas con saldo pendiente.",
            ),
            _finding(
                "SALES_INVOICES_WITHOUT_CUSTOMER",
                ReceivablesSeverity.WARNING,
                "Hay facturas de venta sin cliente asociado.",
            ),
            _finding(
                "PAYMENTS_WITH_CURRENCY_MISMATCH",
                ReceivablesSeverity.INFO,
                "Hay pagos vinculados en una moneda distinta a la factura.",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("question", "expected_metric_keys", "expected_finding_codes", "expected_fragments"),
    (
        (
            "¿Cuántas facturas tengo por vencer o que vencen hoy?",
            {"due_today_sales_invoices", "aging_buckets"},
            set(),
            {"2", "1", "venc"},
        ),
        (
            "¿Cuántas facturas están vencidas?",
            {"overdue_sales_invoices", "seriously_overdue_sales_invoices"},
            {"OVERDUE_SALES_INVOICES", "SERIOUSLY_OVERDUE_SALES_INVOICES"},
            {"5", "venc"},
        ),
        (
            "¿Cómo está distribuida la antigüedad de la cartera?",
            {"aging_buckets"},
            set(),
            {"1", "30"},
        ),
        (
            "¿Cuál es el saldo pendiente por moneda?",
            {"outstanding_balances"},
            set(),
            {"COP", "USD"},
        ),
        (
            "¿Cuántas facturas de venta están abiertas?",
            {"open_sales_invoices"},
            set(),
            {"10", "factura"},
        ),
        (
            "¿Cuántas facturas no tienen pagos registrados?",
            {"unpaid_sales_invoices"},
            {"UNPAID_SALES_INVOICES"},
            {"5", "pago"},
        ),
        (
            "¿Cuántas facturas tienen pagos parciales?",
            {"partially_paid_sales_invoices"},
            {"PARTIALLY_PAID_SALES_INVOICES"},
            {"5", "parcial"},
        ),
        (
            "¿Existen pagos superiores al total de una factura?",
            {"overpaid_sales_invoices"},
            {"OVERPAID_SALES_INVOICES"},
            {"1", "superior"},
        ),
        (
            "¿Cuántas facturas no tienen fecha de vencimiento?",
            {"sales_invoices_missing_due_date"},
            {"SALES_INVOICES_MISSING_DUE_DATE"},
            {"2", "vencimiento"},
        ),
        (
            "¿Cuántos seguimientos de cobro están pendientes?",
            {"pending_collection_followups"},
            set(),
            {"3", "seguimiento"},
        ),
        (
            "¿Cuántas promesas de pago están activas o incumplidas?",
            {"open_payment_promises", "broken_payment_promises"},
            {"OPEN_PAYMENT_PROMISES", "BROKEN_PAYMENT_PROMISES"},
            {"2", "1", "promesa"},
        ),
        (
            "¿Cuál es el promedio de días de recaudo?",
            {"average_days_to_collect", "settled_sales_invoices"},
            set(),
            {"17", "recaudo"},
        ),
        (
            "¿Hay facturas sin cliente asociado?",
            set(),
            {"SALES_INVOICES_WITHOUT_CUSTOMER"},
            {"cliente"},
        ),
        (
            "¿Qué pasa con los pagos en una moneda distinta a la factura?",
            {"payments_with_currency_mismatch"},
            {"PAYMENTS_WITH_CURRENCY_MISMATCH"},
            {"2", "moneda"},
        ),
        (
            "¿Qué significa una factura vencida?",
            {"overdue_sales_invoices"},
            {"OVERDUE_SALES_INVOICES"},
            {"después", "5", "vencida"},
        ),
        (
            "¿Qué es un pago parcial?",
            {"partially_paid_sales_invoices"},
            {"PARTIALLY_PAID_SALES_INVOICES"},
            {"parte", "5", "saldo"},
        ),
        (
            "¿Qué puedo preguntar al agente de cartera?",
            {"open_sales_invoices", "outstanding_balances", "aging_buckets"},
            set(),
            {"puedes preguntar", "promesas", "cartera operativa"},
        ),
    ),
)
def test_deterministic_chat_answers_each_supported_aggregate_question(
    rich_report: ReceivablesReport,
    question: str,
    expected_metric_keys: set[str],
    expected_finding_codes: set[str],
    expected_fragments: set[str],
) -> None:
    conversation = ReceivablesAgent._deterministic_fallback(rich_report, question)

    assert conversation.outcome is ReceivablesConversationOutcome.ANSWERED
    assert conversation.llm_used is False
    evidence = conversation.evidence[0]
    assert expected_metric_keys <= set(evidence.metric_keys)
    assert expected_finding_codes <= set(evidence.finding_codes)
    response = conversation.response.casefold()
    assert all(fragment.casefold() in response for fragment in expected_fragments)


def test_deterministic_chat_prioritizes_active_alerts_without_detail(rich_report: ReceivablesReport) -> None:
    conversation = ReceivablesAgent._deterministic_fallback(
        rich_report,
        "¿Qué alertas de cartera debo priorizar?",
    )

    assert conversation.outcome is ReceivablesConversationOutcome.ANSWERED
    evidence = conversation.evidence[0]
    assert "SERIOUSLY_OVERDUE_SALES_INVOICES" in evidence.finding_codes
    assert "BROKEN_PAYMENT_PROMISES" in evidence.finding_codes
    assert "90" in conversation.response


def test_deterministic_chat_returns_a_safe_summary_for_a_broad_question(
    rich_report: ReceivablesReport,
) -> None:
    conversation = ReceivablesAgent._deterministic_fallback(
        rich_report,
        "Dame un resumen de la cartera actual.",
    )

    assert conversation.outcome is ReceivablesConversationOutcome.ANSWERED
    assert {"open_sales_invoices", "overdue_sales_invoices"} <= set(
        conversation.evidence[0].metric_keys
    )
    assert "10" in conversation.response
    assert "5" in conversation.response


@pytest.mark.parametrize(
    "question",
    (
        "¿Cuál es la factura que vence hoy?",
        "Dime el número de la factura vencida.",
        "¿De qué cliente es la factura con pago parcial?",
        "¿Quién me debe esta semana?",
    ),
)
def test_question_fixtures_keep_individual_requests_outside_aggregate_contract(question: str) -> None:
    assert ReceivablesAgent._requests_individual_receivables_data(question)
