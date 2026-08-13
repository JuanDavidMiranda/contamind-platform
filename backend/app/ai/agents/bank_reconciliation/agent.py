"""Agente agregado y de solo lectura para conciliación bancaria."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.bank_reconciliation.schemas import (
    BankReconciliationConversation,
    BankReconciliationReport,
)
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.bank_reconciliation_analysis_service import (
    BankReconciliationAnalysisService,
)


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


class BankReconciliationAgent(BaseAgent):
    id = "bank_reconciliation"
    name = "Agente de conciliación bancaria"
    description = (
        "Explica cobertura, sugerencias y diferencias de conciliación con agregados verificables."
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
                errors=["MISSING_BANK_RECONCILIATION_SCOPE"],
            )
        db: Session = self._session_factory()
        try:
            report = BankReconciliationAnalysisService(db).analyze(company_id)
            conversation = self._conversation(context.user_message, report)
            self._record_execution(db, company_id, actor_user_id, task, report)
            db.commit()
        except Exception:
            db.rollback()
            return BaseResult(
                success=False,
                message="No fue posible generar el diagnóstico de conciliación bancaria.",
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
                name="Conciliación bancaria",
                description=self.description,
                keywords=[
                    "conciliación bancaria",
                    "extracto bancario",
                    "movimientos sin conciliar",
                    "coincidencias bancarias",
                ],
            )
        ]

    def _conversation(
        self,
        question: str,
        report: BankReconciliationReport,
    ) -> BankReconciliationConversation:
        suggested = (
            "¿Qué debo revisar primero en la conciliación?",
            "¿Cuántos movimientos siguen sin conciliar?",
            "¿Cuál es la cobertura de conciliación?",
            "¿Qué entradas y salidas fueron importadas por moneda?",
        )
        if any(pattern.search(question) for pattern in _SENSITIVE_PATTERNS):
            return BankReconciliationConversation(
                outcome="clarification_needed",
                response=(
                    "Reformula la pregunta sin números de cuenta, documentos, correos, "
                    "credenciales ni referencias bancarias."
                ),
                suggested_questions=suggested,
            )
        normalized = self._normalize(question)
        action_request = normalized.replace("sin conciliar", "")
        if re.search(
            r"\b(?:movimiento|pago|extracto|referencia|cuenta)\s+(?:numero|nro|de|del|con)\b",
            normalized,
        ) or re.search(
            r"\b(?:confirma|confirmar|concilia|conciliar|descarta|descartar|excluye|excluir|importa|importar)\b",
            action_request,
        ):
            return BankReconciliationConversation(
                outcome="out_of_scope",
                response=(
                    "El chat no muestra movimientos, pagos, cuentas o referencias individuales "
                    "ni confirma conciliaciones. Usa Conciliación operativa para esas acciones autorizadas."
                ),
                suggested_questions=suggested,
            )
        metrics = report.metrics
        if re.search(r"\b(?:saldo|dinero disponible|liquidez)\b", normalized):
            response = (
                "Los extractos importados no demuestran el saldo bancario actual porque pueden "
                "cubrir períodos parciales y no incluyen un saldo inicial verificado. Puedo explicar "
                "entradas, salidas y cobertura de conciliación."
            )
            outcome = "out_of_scope"
        elif any(term in normalized for term in ("cobertura", "porcentaje", "tasa")):
            response = (
                f"La cobertura actual es {metrics.reconciliation_rate}%: "
                f"{metrics.reconciled_transactions} de "
                f"{metrics.imported_transactions - metrics.excluded_transactions} movimientos elegibles "
                "están conciliados. Una sugerencia no cuenta como conciliada hasta confirmación humana."
            )
            outcome = "answered"
        elif any(term in normalized for term in ("entrada", "salida", "moneda")):
            response = (
                f"Las entradas importadas son {self._amounts(metrics.statement_inflows)} y "
                f"las salidas importadas son {self._amounts(metrics.statement_outflows)}. "
                "Las monedas permanecen separadas y estos importes no equivalen a saldo actual."
            )
            outcome = "answered"
        elif any(term in normalized for term in ("sin conciliar", "pendiente", "cuantos")):
            response = (
                f"Hay {metrics.pending_transactions} movimientos pendientes, "
                f"{metrics.suggested_matches} sugerencias por confirmar, "
                f"{metrics.unmatched_transactions} sin coincidencia única y "
                f"{metrics.ambiguous_transactions} ambiguos."
            )
            outcome = "answered"
        else:
            codes = ", ".join(
                finding.code
                for finding in report.findings
                if finding.severity.value == "warning"
            ) or "ninguna advertencia prioritaria"
            response = (
                f"La conciliación registra {metrics.imported_transactions} movimientos y "
                f"{metrics.reconciled_transactions} confirmados. Prioriza: {codes}. "
                "Revisa siempre las sugerencias en la vista operativa."
            )
            outcome = "answered"
        return BankReconciliationConversation(
            outcome=outcome,
            response=response,
            suggested_questions=suggested,
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
        return ", ".join(values) if values else "sin movimientos"

    def _record_execution(
        self,
        db: Session,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: BankReconciliationReport,
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
