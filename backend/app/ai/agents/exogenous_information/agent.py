"""Agente agregado para revisar preparación de información exógena."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.exogenous_information.schemas import (
    ExogenousInformationConversation,
    ExogenousInformationReport,
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
from app.services.exogenous_information_service import ExogenousInformationService


class ExogenousInformationAgent(BaseAgent):
    """Prioriza calidad de datos sin decidir obligaciones ni preparar archivos oficiales."""

    id = "exogenous_information"
    name = "Agente de información exógena"
    description = (
        "Revisa la preparación de terceros, facturas y pagos para un año gravable, "
        "sin determinar obligaciones, generar archivos ni consultar la DIAN."
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
                errors=["MISSING_EXOGENOUS_INFORMATION_SCOPE"],
            )

        db: Session = self._session_factory()
        try:
            tax_year = self._tax_year_from_question(context.user_message)
            report = ExogenousInformationService(db).analyze(company_id, tax_year=tax_year)
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
                message="No fue posible generar el diagnóstico de información exógena.",
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
                name="Información exógena",
                description=self.description,
                keywords=[
                    "información exógena",
                    "informacion exogena",
                    "medios magnéticos",
                    "año gravable",
                    "preparación exógena",
                ],
            )
        ]

    def _conversation(
        self,
        question: str,
        report: ExogenousInformationReport,
    ) -> ExogenousInformationConversation:
        suggested = self._suggested_questions(report.metrics.tax_year)
        if contains_sensitive_text(question):
            return ExogenousInformationConversation(
                outcome="clarification_needed",
                response=(
                    "Por seguridad, reformula la pregunta sin NIT, documentos, correos, "
                    "credenciales ni otros identificadores individuales."
                ),
                suggested_questions=suggested,
            )
        normalized = self._normalize(question)
        if self._requests_individual_record(normalized):
            return ExogenousInformationConversation(
                outcome="out_of_scope",
                response=(
                    "Este chat solo resume la preparación de datos. Para revisar casos individuales "
                    "usa la vista Preparación operativa con un usuario autorizado."
                ),
                suggested_questions=suggested,
            )
        if self._requests_official_action(normalized):
            return ExogenousInformationConversation(
                outcome="out_of_scope",
                response=(
                    "Este agente no genera, firma, transmite ni presenta archivos de información "
                    "exógena, y tampoco consulta la DIAN."
                ),
                suggested_questions=suggested,
            )
        if self._asks_for_official_rules(normalized):
            return ExogenousInformationConversation(
                outcome="answered",
                response=(
                    "Aún no determinamos qué formatos, conceptos ni obligación de presentación aplican "
                    f"para {report.metrics.tax_year}. Esa validación requiere parametrización normativa "
                    "vigente y revisión del responsable tributario. Por ahora puedo evaluar la calidad "
                    "de datos disponible."
                ),
                suggested_questions=suggested,
            )

        metrics = report.metrics
        if any(term in normalized for term in ("tercero", "identificacion", "documento", "direccion", "ciudad")):
            response = (
                f"Para {metrics.tax_year} hay {metrics.registered_parties} terceros registrados. "
                f"La cobertura de identificación completa es {metrics.party_identification_coverage}%: "
                f"{metrics.parties_missing_document_type} sin tipo de documento y "
                f"{metrics.parties_missing_document_number} sin número de documento. "
                f"Además, {metrics.parties_missing_city} no tienen ciudad y "
                f"{metrics.parties_missing_address} no tienen dirección."
            )
        elif any(term in normalized for term in ("factura", "pago", "movimiento", "soporte", "trazabilidad")):
            response = (
                f"En {metrics.tax_year} se revisaron {metrics.invoices_in_tax_year} facturas y "
                f"{metrics.payments_in_tax_year} pagos. Hay {metrics.invoices_missing_number} facturas "
                f"sin consecutivo, {metrics.invoices_missing_counterparty} sin contraparte, "
                f"{metrics.invoices_with_total_mismatch} con total inconsistente y "
                f"{metrics.payments_without_invoice} pagos sin factura vinculada."
            )
        elif any(term in normalized for term in ("primero", "prior", "alert", "revis")):
            response = (
                f"Para {metrics.tax_year} hay {report.summary.critical_count} alerta"
                f"{'s' if report.summary.critical_count != 1 else ''} crítica"
                f"{'s' if report.summary.critical_count != 1 else ''} y "
                f"{report.summary.warning_count} advertencia"
                f"{'s' if report.summary.warning_count != 1 else ''}. "
                f"{priority_actions(report.findings, severity_values=frozenset({'critical', 'warning'}))}"
            )
        else:
            response = (
                f"Se revisó la preparación de datos para {metrics.tax_year}: "
                f"{metrics.registered_parties} terceros, {metrics.invoices_in_tax_year} facturas y "
                f"{metrics.payments_in_tax_year} pagos. La cobertura de identificación de terceros es "
                f"{metrics.party_identification_coverage}%. Este resultado no define obligación ni formatos DIAN."
            )
        return ExogenousInformationConversation(
            outcome="answered",
            response=response,
            suggested_questions=suggested,
        )

    @staticmethod
    def _suggested_questions(tax_year: int) -> tuple[str, ...]:
        return (
            "¿Qué debo revisar primero para información exógena?",
            "¿Qué datos faltan en los terceros?",
            "¿Qué facturas o pagos requieren trazabilidad?",
            f"¿Qué preparación de datos hay para el año gravable {tax_year}?",
            "¿El aplicativo ya genera archivos para la DIAN?",
        )

    @staticmethod
    def _tax_year_from_question(question: str) -> int | None:
        match = re.search(r"\b(20\d{2})\b", question)
        return int(match.group(1)) if match else None

    @staticmethod
    def _requests_individual_record(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:muestrame|dame|lista|cual|numero|documento|nit|nombre)\b"
                r".{0,60}\b(?:tercero|cliente|proveedor|factura|pago)\b",
                question,
            )
        )

    @staticmethod
    def _requests_official_action(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:genera|generar|descarga|descargar|firma|firmar|envia|enviar|"
                r"presenta|presentar|radica|radicar|transmite|transmitir|carga|cargar)\b"
                r".{0,80}\b(?:archivo|formato|exogena|dian|muisca|medio)\b",
                question,
            )
        )

    @staticmethod
    def _asks_for_official_rules(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:formatos?|conceptos?|obligacion(?:es)?|obligad[oa]s?|fechas?|vencimientos?|"
                r"plazos?|requisitos?|normas?|resoluciones?)\b.{0,80}\b(?:exogena|dian|muisca|medio)\b"
                r"|\b(?:exogena|dian|muisca|medio)\b.{0,80}\b(?:formatos?|conceptos?|obligacion(?:es)?|"
                r"obligad[oa]s?|fechas?|vencimientos?|plazos?|requisitos?|normas?|resoluciones?)\b",
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
        report: ExogenousInformationReport,
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
