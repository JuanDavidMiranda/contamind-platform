"""Agente determinista de movimientos proyectados de caja."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.cash_flow.schemas import (
    CashFlowAmount,
    CashFlowConversation,
    CashFlowPeriod,
    CashFlowReport,
)
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.cash_flow_service import CashFlowService


_SENSITIVE_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\d[\s.-]?){7,}\d(?!\d)"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:password|contraseña|secret|token|api[ _-]?key|clave)"
        r"\s*(?:es|:|=)\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
)


class CashFlowAgent(BaseAgent):
    """Explica movimientos abiertos, nunca saldos bancarios ni pagos ejecutables."""

    id = "cash_flow"
    name = "Agente de flujo de caja"
    description = (
        "Proyecta entradas y salidas abiertas por vencimiento y moneda, "
        "sin afirmar disponibilidad bancaria."
    )
    version = "1.0.0"

    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    async def execute(self, task: BaseTask, context: Context) -> BaseResult:
        try:
            company_id = UUID(context.company_id or "")
            actor_user_id = int(context.user_id or "")
        except (TypeError, ValueError):
            return BaseResult(
                success=False,
                message="El agente requiere una empresa y un usuario autenticado.",
                errors=["MISSING_CASH_FLOW_SCOPE"],
            )

        db: Session = self._session_factory()
        try:
            report = CashFlowService(db).analyze(company_id)
            conversation = self._conversation(context.user_message, report)
            self._record_execution(
                db,
                company_id=company_id,
                actor_user_id=actor_user_id,
                task=task,
                report=report,
            )
            db.commit()
        except Exception:
            db.rollback()
            return BaseResult(
                success=False,
                message="No fue posible generar la proyección de flujo de caja.",
                errors=["INTERNAL_ERROR"],
            )
        finally:
            db.close()

        return BaseResult(
            success=True,
            message=conversation.response,
            data={
                "agent_id": self.id,
                "report": report.model_dump(mode="json"),
                "conversation": conversation.model_dump(mode="json"),
            },
        )

    async def health(self) -> bool:
        return True

    @property
    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                name="Flujo de caja",
                description=self.description,
                keywords=[
                    "flujo de caja",
                    "entradas y salidas",
                    "movimientos proyectados",
                    "vencimientos de caja",
                ],
            )
        ]

    def _conversation(
        self,
        question: str,
        report: CashFlowReport,
    ) -> CashFlowConversation:
        suggested = (
            "¿Qué movimientos debo revisar primero?",
            "¿Qué entradas y salidas hay en los próximos 30 días?",
            "¿Cuál es el movimiento neto proyectado por moneda?",
            "¿Qué datos faltan para completar la proyección?",
        )
        if self._contains_sensitive_text(question):
            return CashFlowConversation(
                outcome="clarification_needed",
                response=(
                    "Por seguridad, reformula la pregunta sin documentos, correos, "
                    "credenciales ni otros identificadores personales."
                ),
                suggested_questions=suggested,
            )

        normalized = self._normalize(question)
        if self._requests_bank_balance(normalized):
            return CashFlowConversation(
                outcome="out_of_scope",
                response=(
                    "No puedo determinar efectivo disponible, liquidez real ni saldo "
                    "bancario porque esta versión no recibe cuentas bancarias ni "
                    "extractos. Sí puedo explicar los movimientos abiertos proyectados "
                    "por vencimiento y moneda."
                ),
                suggested_questions=suggested,
            )
        if self._requests_individual_or_write(normalized):
            return CashFlowConversation(
                outcome="out_of_scope",
                response=(
                    "El chat no consulta facturas, clientes, proveedores o pagos "
                    "individuales, ni registra cobros, pagos o transferencias. Usa "
                    "Cartera o Cuentas por pagar operativas para el detalle autorizado."
                ),
                suggested_questions=suggested,
            )

        metrics = report.metrics
        if any(
            term in normalized
            for term in ("faltan", "faltante", "sin fecha", "cobertura")
        ):
            response = (
                f"Hay {metrics.receivables_missing_due_date} cuentas por cobrar y "
                f"{metrics.payables_missing_due_date} cuentas por pagar sin fecha de "
                "vencimiento. Esos movimientos no entran en la proyección temporal."
            )
        elif any(
            term in normalized
            for term in ("periodo", "semana", "distribu", "cuando")
        ):
            response = self._periods_response(metrics.cash_flow_periods)
        elif any(
            term in normalized
            for term in ("entrada", "salida", "30 dias")
        ):
            inflows, outflows = self._within_30_days(metrics.cash_flow_periods)
            response = (
                "Dentro de los próximos treinta días, incluyendo movimientos vencidos, "
                f"las entradas abiertas son {self._amounts_text(inflows)} y las salidas "
                f"abiertas son {self._amounts_text(outflows)}. Son vencimientos, no "
                "cobros ni pagos confirmados."
            )
        elif any(term in normalized for term in ("neto", "moneda", "balance")):
            response = (
                "El movimiento neto proyectado hasta noventa días es "
                f"{self._amounts_text(metrics.net_movements_90d)}. Cada moneda se "
                "mantiene separada y este neto no representa saldo bancario."
            )
        elif any(
            term in normalized for term in ("primero", "prior", "alert")
        ):
            warning_codes = ", ".join(
                finding.code
                for finding in report.findings
                if finding.severity.value == "warning"
            ) or "ninguna advertencia prioritaria"
            response = (
                f"La proyección tiene {report.summary.warning_count} advertencias. "
                f"Prioriza: {warning_codes}. Revisa siempre la certeza de recaudo y la "
                "disponibilidad bancaria fuera de este reporte."
            )
        else:
            response = (
                f"Hay {metrics.scheduled_receivables} entradas y "
                f"{metrics.scheduled_payables} salidas abiertas con vencimiento. El "
                "movimiento neto hasta noventa días es "
                f"{self._amounts_text(metrics.net_movements_90d)}. No equivale a caja "
                "disponible."
            )
        return CashFlowConversation(
            outcome="answered",
            response=response,
            suggested_questions=suggested,
        )

    @staticmethod
    def _requests_individual_or_write(question: str) -> bool:
        individual = re.search(
            r"\b(?:cliente|proveedor|tercero|consecutivo|referencia)\b|"
            r"\bfactura\s+(?:numero|nro|de|del|con)\b|"
            r"\bpago\s+(?:de|del|para)\b",
            question,
        )
        write = re.search(
            r"\b(?:registra|registrar|programa|programar|crea|crear|modifica|"
            r"modificar|paga|pagar|cobra|cobrar|transfiere|transferir|envia|enviar)\b",
            question,
        )
        return bool(individual or write)

    @staticmethod
    def _requests_bank_balance(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:saldo\s+bancario|saldo\s+en\s+banco|efectivo\s+disponible|"
                r"dinero\s+disponible|cuanto\s+dinero\s+(?:tengo|hay)|"
                r"liquidez\s+(?:real|disponible)|puedo\s+pagar)\b",
                question,
            )
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(character)
        )

    @staticmethod
    def _contains_sensitive_text(value: str) -> bool:
        return any(pattern.search(value) for pattern in _SENSITIVE_PATTERNS)

    @staticmethod
    def _amounts_text(amounts) -> str:
        values = [f"{amount.currency_code} {amount.amount}" for amount in amounts]
        return ", ".join(values) if values else "sin movimientos programados"

    @classmethod
    def _periods_response(cls, periods: tuple[CashFlowPeriod, ...]) -> str:
        labels = {
            "overdue": "vencidos",
            "due_today": "hoy",
            "next_7_days": "próximos 7 días",
            "days_8_30": "días 8 a 30",
            "days_31_60": "días 31 a 60",
            "days_61_90": "días 61 a 90",
            "beyond_90": "después de 90 días",
        }
        if not periods:
            return "No hay movimientos abiertos con vencimiento para distribuir por período."
        parts = [
            f"{labels[period.key]}: neto {cls._amounts_text(period.net_movements)}"
            for period in periods
        ]
        return (
            "La distribución de movimientos netos es "
            + "; ".join(parts)
            + ". Los importes no representan saldos bancarios."
        )

    @staticmethod
    def _within_30_days(periods: tuple[CashFlowPeriod, ...]):
        included = {"overdue", "due_today", "next_7_days", "days_8_30"}
        inflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        outflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for period in periods:
            if period.key not in included:
                continue
            for amount in period.projected_inflows:
                inflows[amount.currency_code] += amount.amount
            for amount in period.projected_outflows:
                outflows[amount.currency_code] += amount.amount
        return (
            tuple(
                CashFlowAmount(currency_code=currency, amount=amount)
                for currency, amount in sorted(inflows.items())
            ),
            tuple(
                CashFlowAmount(currency_code=currency, amount=amount)
                for currency, amount in sorted(outflows.items())
            ),
        )

    def _record_execution(
        self,
        db: Session,
        *,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: CashFlowReport,
    ) -> None:
        company = db.get(CompanyRecord, str(company_id))
        if company is None:
            return
        db.add(
            AgentExecutionRecord(
                id=str(uuid4()),
                tenant_id=company.tenant_id,
                company_id=str(company_id),
                actor_user_id=actor_user_id,
                conversation_id=self._optional_text(
                    task.payload.get("conversation_id"), maximum=36
                ),
                agent_id=self.id,
                agent_version=self.version,
                operation=task.objective[:64],
                status="succeeded",
                finding_count=len(report.findings),
                finding_codes=sorted(finding.code for finding in report.findings),
                correlation_id=self._optional_text(
                    task.payload.get("correlation_id"), maximum=64
                ),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    @staticmethod
    def _optional_text(value: object, *, maximum: int) -> str | None:
        if not isinstance(value, str):
            return None
        return value.strip()[:maximum] or None
