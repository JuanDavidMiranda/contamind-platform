"""Agente de facturación electrónica basado en evidencia agregada."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.electronic_invoicing.schemas import (
    ElectronicInvoicingConversation,
    ElectronicInvoicingReport,
)
from app.ai.agents.presentation import priority_actions
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.accounting_health_conversation_service import contains_sensitive_text
from app.services.electronic_invoicing_service import ElectronicInvoicingService


class ElectronicInvoicingAgent(BaseAgent):
    """Diagnostica evidencia electrónica sin consultar ni modificar servicios externos."""

    id = "electronic_invoicing"
    name = "Agente de facturación electrónica"
    description = (
        "Revisa estados electrónicos importados y la calidad de las facturas de venta, "
        "sin emitir, reenviar ni validar documentos ante la DIAN."
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
                errors=["MISSING_ELECTRONIC_INVOICING_SCOPE"],
            )

        db: Session = self._session_factory()
        try:
            report = ElectronicInvoicingService(db).analyze(company_id)
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
                message="No fue posible generar el diagnóstico de facturación electrónica.",
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
                name="Facturación electrónica",
                description=self.description,
                keywords=[
                    "facturación electrónica",
                    "factura electrónica",
                    "cufe",
                    "cude",
                    "estado dian",
                    "facturas rechazadas",
                ],
            )
        ]

    def _conversation(
        self,
        question: str,
        report: ElectronicInvoicingReport,
    ) -> ElectronicInvoicingConversation:
        suggested = self._suggested_questions()
        if contains_sensitive_text(question):
            return ElectronicInvoicingConversation(
                outcome="clarification_needed",
                response=(
                    "Por seguridad, reformula la pregunta sin NIT, CUFE, CUDE, correos, "
                    "credenciales ni otros identificadores individuales."
                ),
                suggested_questions=suggested,
            )

        normalized = self._normalize(question)
        if self._requests_individual_document(normalized):
            return ElectronicInvoicingConversation(
                outcome="out_of_scope",
                response=(
                    "Este chat solo analiza evidencia agregada y no muestra facturas, "
                    "consecutivos, CUFE, CUDE ni datos de adquirientes individuales."
                ),
                suggested_questions=suggested,
            )
        if self._requests_write_or_dian_validation(normalized):
            return ElectronicInvoicingConversation(
                outcome="out_of_scope",
                response=(
                    "Este agente no emite, firma, envía, corrige, anula ni consulta documentos "
                    "en la DIAN. Solo interpreta los estados que una fuente autorizada ya haya importado."
                ),
                suggested_questions=suggested,
            )
        if self._asks_about_dian_connection(normalized):
            return ElectronicInvoicingConversation(
                outcome="answered",
                response=(
                    "La conexión en tiempo real con la DIAN todavía no está configurada. "
                    "Por ahora, este diagnóstico usa estados y referencias importados desde "
                    "las fuentes contables o electrónicas autorizadas; no confirma aceptación "
                    "ante la DIAN ni transmite documentos."
                ),
                suggested_questions=suggested,
            )

        metrics = report.metrics
        if any(term in normalized for term in ("rechaz", "error", "pendient", "estado")):
            response = (
                f"Hay {metrics.accepted_electronic_invoices} facturas con estado aceptado, "
                f"{metrics.pending_electronic_invoices} pendientes y "
                f"{metrics.rejected_electronic_invoices} rechazadas o con error. "
                "Son estados importados; confirma los casos críticos en la fuente que los reportó."
            )
        elif any(term in normalized for term in ("falt", "referencia", "cufe", "cude", "cobertura", "dato")):
            response = (
                f"La cobertura de estado electrónico es {metrics.electronic_status_coverage}%. "
                f"Hay {metrics.invoices_without_electronic_status} facturas sin estado, "
                f"{metrics.invoices_without_electronic_reference} sin referencia electrónica, "
                f"{metrics.invoices_missing_number} sin consecutivo y "
                f"{metrics.invoices_without_recipient} sin adquiriente asociado."
            )
        elif any(term in normalized for term in ("primero", "prior", "alert", "revis")):
            response = (
                f"El diagnóstico registra {report.summary.critical_count} alerta"
                f"{'s' if report.summary.critical_count != 1 else ''} crítica"
                f"{'s' if report.summary.critical_count != 1 else ''} y "
                f"{report.summary.warning_count} advertencia"
                f"{'s' if report.summary.warning_count != 1 else ''}. "
                f"{priority_actions(report.findings, severity_values=frozenset({'critical', 'warning'}))}"
            )
        else:
            response = (
                f"Se revisaron {metrics.sales_invoices} facturas de venta. "
                f"La cobertura de estado electrónico importado es {metrics.electronic_status_coverage}%: "
                f"{metrics.accepted_electronic_invoices} aceptadas, "
                f"{metrics.pending_electronic_invoices} pendientes y "
                f"{metrics.rejected_electronic_invoices} rechazadas o con error. "
                "El diagnóstico no verifica estos estados directamente con la DIAN."
            )
        return ElectronicInvoicingConversation(
            outcome="answered",
            response=response,
            suggested_questions=suggested,
        )

    @staticmethod
    def _suggested_questions() -> tuple[str, ...]:
        return (
            "¿Qué debo revisar primero en facturación electrónica?",
            "¿Cuántas facturas están pendientes o rechazadas?",
            "¿Qué datos faltan para tener trazabilidad electrónica?",
            "¿El aplicativo ya valida documentos ante la DIAN?",
        )

    @staticmethod
    def _requests_individual_document(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:muestrame|dame|lista|cual|numero|consecutivo|referencia|cufe|cude)\b"
                r".{0,60}\b(?:factura|documento|adquiriente|cliente|tercero)\b",
                question,
            )
        )

    @staticmethod
    def _requests_write_or_dian_validation(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:emite|emitir|firma|firmar|envia|enviar|reenviar|crea|crear|"
                r"corrige|corregir|anula|anular|cancela|cancelar|sincroniza|sincronizar|"
                r"valida(?:r)?\s+(?:esta|la|el|una|un)?\s*(?:factura|documento)|"
                r"consulta(?:r)?\s+(?:esta|la|el|una|un)?\s*(?:factura|documento))\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_dian_connection(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:conexion|conectado|integracion|integrado|consulta|valid(?:a|ar|acion))\b"
                r".{0,60}\b(?:dian|tiempo\s+real)\b"
                r"|\b(?:dian|tiempo\s+real)\b.{0,60}\b(?:conexion|conectado|integracion|"
                r"integrado|consulta|valid(?:a|ar|acion))\b",
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

    def _record_execution(
        self,
        db: Session,
        *,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: ElectronicInvoicingReport,
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
                conversation_id=self._optional_text(task.payload.get("conversation_id"), maximum=36),
                agent_id=self.id,
                agent_version=self.version,
                operation=task.objective[:64],
                status="succeeded",
                finding_count=len(report.findings),
                finding_codes=sorted(finding.code for finding in report.findings),
                correlation_id=self._optional_text(task.payload.get("correlation_id"), maximum=64),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    @staticmethod
    def _optional_text(value: object, *, maximum: int) -> str | None:
        if not isinstance(value, str):
            return None
        return value.strip()[:maximum] or None
