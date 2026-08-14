"""Agente determinista de tesorería y liquidez."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.treasury.schemas import TreasuryConversation, TreasuryReport
from app.ai.agents.presentation import priority_actions
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.treasury_service import TreasuryService


_SENSITIVE_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\d[\s.-]?){7,}\d(?!\d)"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:password|contraseña|secret|token|api[ _-]?key|clave)"
        r"\s*(?:es|:|=)\s*\S+",
        re.IGNORECASE,
    ),
)


class TreasuryAgent(BaseAgent):
    """Explica señales de tesorería, sin afirmar saldo ni ejecutar pagos."""

    id = "treasury"
    name = "Agente de tesorería y liquidez"
    description = (
        "Contrasta movimientos proyectados y conciliación bancaria sin afirmar "
        "disponibilidad real ni ejecutar pagos."
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
                errors=["MISSING_TREASURY_SCOPE"],
            )
        db: Session = self._session_factory()
        try:
            report = TreasuryService(db).analyze(company_id)
            conversation = self._conversation(context.user_message, report)
            self._record_execution(db, company_id, actor_user_id, task, report)
            db.commit()
        except Exception:
            db.rollback()
            return BaseResult(
                success=False,
                message="No fue posible generar el diagnóstico de tesorería.",
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
                name="Tesorería y liquidez",
                description=self.description,
                keywords=[
                    "tesorería",
                    "liquidez",
                    "prioridad de pagos",
                    "disponibilidad de caja",
                ],
            )
        ]

    def _conversation(
        self,
        question: str,
        report: TreasuryReport,
    ) -> TreasuryConversation:
        suggested = (
            "¿Qué debo revisar primero para tesorería?",
            "¿Qué movimiento neto se proyecta a 30 días por moneda?",
            "¿La conciliación permite usar la señal bancaria?",
            "¿Qué impide conocer la disponibilidad real?",
        )
        if any(pattern.search(question) for pattern in _SENSITIVE_PATTERNS):
            return TreasuryConversation(
                outcome="clarification_needed",
                response=(
                    "Reformula la pregunta sin números de cuenta, documentos, correos, "
                    "credenciales ni referencias individuales."
                ),
                suggested_questions=suggested,
            )
        normalized = self._normalize(question)
        if self._requests_actual_availability(normalized):
            return TreasuryConversation(
                outcome="out_of_scope",
                response=(
                    "No puedo determinar si puedes pagar ni la disponibilidad real: hace falta "
                    "un saldo bancario verificado y pueden existir obligaciones fuera del modelo. "
                    "Sí puedo explicar la proyección abierta y la calidad de conciliación."
                ),
                suggested_questions=suggested,
            )
        if self._requests_individual_or_write(normalized):
            return TreasuryConversation(
                outcome="out_of_scope",
                response=(
                    "El chat no muestra facturas, pagos, cuentas o movimientos individuales, "
                    "ni programa, prioriza o autoriza pagos. Usa las vistas operativas para "
                    "el detalle y la revisión humana autorizada."
                ),
                suggested_questions=suggested,
            )

        metrics = report.metrics
        if any(term in normalized for term in ("concili", "banco", "extracto", "cobertura")):
            response = (
                f"La conciliación tiene {metrics.reconciled_bank_transactions} movimientos "
                f"confirmados de {metrics.imported_bank_transactions} importados y una cobertura "
                f"de {metrics.reconciliation_rate}%. Aún hay "
                f"{metrics.pending_bank_transactions} pendientes, "
                f"{metrics.suggested_bank_transactions} sugeridos, "
                f"{metrics.unmatched_bank_transactions} sin coincidencia y "
                f"{metrics.ambiguous_bank_transactions} ambiguos."
            )
        elif any(term in normalized for term in ("30 dias", "proyeccion", "entrada", "salida", "neto", "moneda")):
            response = (
                "En los próximos treinta días, incluidos vencidos, las entradas abiertas "
                f"son {self._amounts(metrics.projected_inflows_30d)}, las salidas abiertas "
                f"son {self._amounts(metrics.projected_outflows_30d)} y el movimiento neto "
                f"proyectado es {self._amounts(metrics.net_projected_movements_30d)}. "
                "Cada moneda permanece separada; no equivale a saldo disponible."
            )
        elif any(term in normalized for term in ("impide", "faltan", "disponibilidad", "liquidez")):
            response = (
                "La disponibilidad real no puede determinarse con este reporte porque no hay "
                "un saldo bancario verificado y pueden existir obligaciones fuera del modelo. "
                f"Además hay {metrics.receivables_missing_due_date} cobros y "
                f"{metrics.payables_missing_due_date} pagos sin vencimiento, y "
                f"{metrics.pending_bank_transactions + metrics.suggested_bank_transactions} "
                "movimientos bancarios pendientes o sugeridos de revisión."
            )
        else:
            response = (
                f"El diagnóstico requiere atención en {report.summary.warning_count} "
                f"aspecto{'s' if report.summary.warning_count != 1 else ''}. "
                f"{priority_actions(report.findings, severity_values=frozenset({'warning'}))} "
                "Antes de tomar una decisión de pagos, confirma el saldo bancario verificado "
                "por moneda y completa la conciliación pendiente."
            )
        return TreasuryConversation(
            outcome="answered",
            response=response,
            suggested_questions=suggested,
        )

    @staticmethod
    def _requests_individual_or_write(question: str) -> bool:
        individual = re.search(
            r"\b(?:cliente|proveedor|tercero|factura|pago|movimiento|cuenta|referencia)"
            r"\s+(?:numero|nro|de|del|con|para)\b",
            question,
        )
        write = re.search(
            r"\b(?:registra|registrar|programa|programar|crea|crear|modifica|"
            r"modificar|paga|pagar|cobra|cobrar|transfiere|transferir|autoriza|autorizar)\b",
            question,
        )
        return bool(individual or write)

    @staticmethod
    def _requests_actual_availability(question: str) -> bool:
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
    def _amounts(amounts) -> str:
        values = [f"{amount.currency_code} {amount.amount}" for amount in amounts]
        return ", ".join(values) if values else "sin movimientos proyectados"

    def _record_execution(
        self,
        db: Session,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: TreasuryReport,
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
                conversation_id=self._optional(task.payload.get("conversation_id"), 36),
                agent_id=self.id,
                agent_version=self.version,
                operation=task.objective[:64],
                status="succeeded",
                finding_count=len(report.findings),
                finding_codes=sorted(finding.code for finding in report.findings),
                correlation_id=self._optional(task.payload.get("correlation_id"), 64),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    @staticmethod
    def _optional(value: object, maximum: int) -> str | None:
        return value.strip()[:maximum] or None if isinstance(value, str) else None
