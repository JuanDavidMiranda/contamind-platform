"""Agente determinista y de sólo lectura para obligaciones de compra."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.payables.schemas import PayablesConversation, PayablesReport
from app.ai.agents.presentation import priority_actions
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.payables_service import PayablesService
from app.services.accounting_health_conversation_service import contains_sensitive_text


class PayablesAgent(BaseAgent):
    """Responde con agregados verificables; nunca expone proveedores o facturas."""

    id = "payables"
    name = "Agente de cuentas por pagar"
    description = "Diagnóstico de obligaciones de compra, pagos y vencimientos por moneda."
    version = "1.0.0"

    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    async def execute(self, task: BaseTask, context: Context) -> BaseResult:
        try:
            company_id, actor_user_id = UUID(context.company_id or ""), int(context.user_id or "")
        except (TypeError, ValueError):
            return BaseResult(success=False, message="El agente requiere una empresa y un usuario autenticado.", errors=["MISSING_PAYABLES_SCOPE"])
        db: Session = self._session_factory()
        try:
            report = PayablesService(db).analyze(company_id)
            conversation = self._conversation(context.user_message, report)
            self._record_execution(db, company_id, actor_user_id, task, report)
            db.commit()
        except Exception:
            db.rollback()
            return BaseResult(success=False, message="No fue posible generar el diagnóstico de cuentas por pagar.", errors=["INTERNAL_ERROR"])
        finally:
            db.close()
        return BaseResult(success=True, message=conversation.response, data={"agent_id": self.id, "report": report.model_dump(mode="json"), "conversation": conversation.model_dump(mode="json")})

    async def health(self) -> bool: return True

    @property
    def capabilities(self) -> list[Capability]:
        return [Capability(name="Cuentas por pagar", description=self.description, keywords=["cuentas por pagar", "proveedores", "compras", "obligaciones", "vencimientos de compra"])]

    def _conversation(self, question: str, report: PayablesReport) -> PayablesConversation:
        normalized = question.casefold()
        suggested = ("¿Qué obligaciones debo revisar primero?", "¿Qué saldos pendientes hay por moneda?", "¿Cuántas facturas de compra están vencidas?")
        if contains_sensitive_text(question):
            return PayablesConversation(outcome="clarification_needed", response="Por seguridad, reformula la pregunta sin documentos, correos, credenciales ni otros identificadores personales.", suggested_questions=suggested)
        if self._requests_individual_or_write(normalized):
            return PayablesConversation(outcome="out_of_scope", response="El chat no consulta facturas, proveedores ni pagos individuales, ni programa o registra pagos. Usa Cuentas por pagar operativas si tienes autorización; aquí puedo explicar saldos y alertas agregadas.", suggested_questions=suggested)
        metrics = report.metrics
        balances = ", ".join(f"{balance.currency_code} {balance.amount}" for balance in metrics.outstanding_balances) or "sin saldos abiertos"
        if "moneda" in normalized or "saldo" in normalized:
            response = f"Los saldos pendientes se mantienen separados por moneda: {balances}. No convierto ni sumo monedas distintas."
        elif "venc" in normalized or "antig" in normalized:
            response = f"Hay {metrics.overdue_purchase_invoices} facturas de compra vencidas y {metrics.due_today_purchase_invoices} que vencen hoy; {metrics.purchase_invoices_missing_due_date} no tienen vencimiento verificable."
        elif "alert" in normalized or "primero" in normalized or "prior" in normalized:
            response = (
                f"El diagnóstico tiene {report.summary.critical_count} alertas críticas y "
                f"{report.summary.warning_count} advertencias. "
                f"{priority_actions(report.findings)}"
            )
        else:
            response = f"Hay {metrics.open_purchase_invoices} facturas de compra con saldo pendiente. Los importes siguen separados por moneda: {balances}. Puedo ayudarte a interpretar vencimientos, antigüedad y alertas agregadas."
        return PayablesConversation(outcome="answered", response=response, suggested_questions=suggested)

    @staticmethod
    def _requests_individual_or_write(question: str) -> bool:
        terms = ("factura ", "proveedor ", "nit", "numero", "número", "pago para", "registr", "program", "enviar", "transfer")
        return any(term in question for term in terms)

    def _record_execution(self, db: Session, company_id: UUID, actor_user_id: int, task: BaseTask, report: PayablesReport) -> None:
        company = db.get(CompanyRecord, str(company_id))
        if company is None: return
        db.add(AgentExecutionRecord(
            id=str(uuid4()), tenant_id=company.tenant_id, company_id=str(company_id), actor_user_id=actor_user_id,
            conversation_id=self._optional_text(task.payload.get("conversation_id"), 36), agent_id=self.id, agent_version=self.version,
            operation=task.objective[:64], status="succeeded", finding_count=len(report.findings),
            finding_codes=sorted(finding.code for finding in report.findings),
            correlation_id=self._optional_text(task.payload.get("correlation_id"), 64), completed_at=datetime.now(UTC).replace(tzinfo=None),
        ))

    @staticmethod
    def _optional_text(value: object, maximum: int) -> str | None:
        return value.strip()[:maximum] or None if isinstance(value, str) else None
