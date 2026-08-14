"""Agente de cartera con hechos deterministas y conversación restringida."""

from datetime import UTC, datetime
from decimal import Decimal
import logging
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.receivables.schemas import (
    ReceivablesConversation,
    ReceivablesEvidence,
    ReceivablesReport,
)
from app.ai.agents.presentation import priority_actions
from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.capability import Capability
from app.ai.core.context import Context
from app.config.features import FEATURE_LLM, is_enabled
from app.database import SessionLocal
from app.models.agent import AgentExecutionRecord
from app.models.organization import CompanyRecord
from app.services.accounting_health_conversation_service import (
    contains_sensitive_text,
    redact_sensitive_text,
)
from app.services.receivables_conversation_service import (
    OpenAIReceivablesNarrator,
    ReceivablesNarration,
    ReceivablesNarrator,
)
from app.services.receivables_service import ReceivablesService


logger = logging.getLogger("contamind.receivables_agent")

_INDIVIDUAL_LIST_REQUEST = re.compile(
    r"\b(?:dame|muestra(?:me)?|lista(?:me)?|enumera|detalla|identifica|"
    r"ensen(?:a|ame)|indica(?:me)?|top|ranking)\b.{0,100}\b(?:las?\s+)?"
    r"(?:facturas?|pagos?|clientes?|deudor(?:es)?|terceros?|promesas?|"
    r"seguimientos?|notas?)\b"
)
_INDIVIDUAL_SELECTOR_REQUEST = re.compile(
    r"\b(?:cual(?:es)?|quien(?:es)?)\b\s+(?:(?:es|son|seria|serian)\s+)?"
    r"(?:la|el|las|los|una|un)?\s*(?:facturas?|pagos?|clientes?|deudor(?:es)?|"
    r"terceros?|promesas?|seguimientos?|notas?)\b"
    r"|\b(?:a\s+quien|de\s+quien)\b.{0,100}\b(?:facturas?|pagos?|clientes?|"
    r"deudor(?:es)?|terceros?|promesas?|seguimientos?|notas?)\b"
)
_INDIVIDUAL_REFERENCE_REQUEST = re.compile(
    r"\b(?:factura|pago|recibo|consecutivo|referencia)\s*"
    r"(?:numero|nro|no)?\s*#?\s*[a-z]{0,8}[-/]?\d+\b"
)
_INDIVIDUAL_DESCRIPTOR_REQUEST = re.compile(
    r"\b(?:numero|nro|consecutivo|referencia|correo|telefono|direccion|"
    r"contacto|nota)\b.{0,100}\b(?:facturas?|pagos?|clientes?|deudor(?:es)?|"
    r"terceros?|promesas?|seguimientos?)\b"
)
_INDIVIDUAL_WHAT_REQUEST = re.compile(
    r"\bque\s+(?!es\b|significa\b|ocurre\b|pasa\b)(?:la\s+|el\s+|las\s+|los\s+)?"
    r"(?:facturas?|pagos?|clientes?|deudor(?:es)?|terceros?|promesas?|"
    r"seguimientos?|notas?|correos?|telefonos?|contactos?)\b"
    r"|\bque\s+(?:dice|indica|muestra)\s+(?:la\s+|el\s+)?(?:nota|"
    r"seguimiento|factura|pago|cliente|deudor)\b"
)
_INDIVIDUAL_CONDITION_REQUEST = re.compile(
    r"\b(?:cual(?:es)?|a\s+cual)\b\s+(?:(?:es|son)\s+)?"
    r"(?:la|el|las|los|una|un)?\s*(?:facturas?|pagos?|clientes?|deudor(?:es)?|"
    r"terceros?|promesas?|seguimientos?|notas?)\b.{0,80}\b(?:mayor|menor|"
    r"primer[ao]|ultim[ao]|vence\w*|vencid\w*|atrasad\w*|moros\w*|"
    r"contactad\w*|incumplid\w*)\b"
    r"|\bcual\b\s+(?:vence\w*|esta\w*|tiene\w*|fue\w*|es\s+la)\b"
    r"|\bcual(?:es)?\s+de\s+ellas?\b"
    r"|\bquien(?:es)?\b.{0,80}\b(?:mora|debe\w*|moros\w*|pago\w*)\b"
    r"|\ba\s+quien\b.{0,40}\b(?:cobrar|debo)\b"
)
_INDIVIDUAL_NAMED_PARTY_REQUEST = re.compile(
    r"\b(?:cuanto|que)\s+debe\s+(?!(?:la\s+)?(?:cartera|empresa|"
    r"total)\b)(?:el\s+|la\s+)?[a-z][a-z0-9_-]*\b"
)
_OUT_OF_SCOPE_TOPIC_REQUEST = re.compile(
    r"\b(?:nomina|exogena|medios\s+magneticos|facturacion\s+electronica|"
    r"dian|iva|retencion(?:es)?|impuesto(?:s)?|inventario|compras?|"
    r"bancos?|extracto(?:s)?|conciliacion\s+bancaria|contabilidad\s+general|"
    r"balance\s+general|flujo\s+de\s+caja|pronostico(?:s)?|"
    r"score\s+(?:de\s+)?credito|probabilidad\s+de\s+recaudo|"
    r"demand(?:a|ar)|embargo|interes(?:es)?\s+de\s+mora|"
    r"tasa\s+de\s+interes|descuento(?:s)?|cobranza\s+coercitiva|"
    r"politica\s+de\s+credito|instrucciones\s+del\s+sistema|prompt|sql|"
    r"configuracion\s+interna|api\s*key|ignora(?:r)?\s+.*instruccion(?:es)?)\b"
)
_UNAVAILABLE_METRIC_REQUEST = re.compile(
    r"\b(?:proxim[oa]s?|siguientes?)\s+(?:\d+|siete|quince|treinta)\s+dias\b"
    r"|\b(?:esta|proxima|siguiente)\s+(?:semana|quincena|mes)\b"
    r"|\b(?:mes\s+pasado|cierre\s+de|comparad[oa]|tendencia|semanal|"
    r"recaudo\s+de\s+hoy|dso)\b"
    r"|\b(?:mas\s+de|menos\s+de|superior\s+a)\s+(?:\d+|quince|"
    r"cuarenta\s+y\s+cinco|setenta\s+y\s+cinco)\s+dias\b"
)
_OPERATIONAL_GUIDANCE_REQUEST = re.compile(
    r"\b(?:como|donde|puedo|debo)\b.{0,80}\b(?:actualiz(?:ar|o)|"
    r"edit(?:ar|o)|cambi(?:ar|o)|correg(?:ir|o)|registr(?:ar|o)|"
    r"cre(?:ar|o))\b.{0,80}\b(?:vencimiento|plazo|condiciones?\s+de\s+pago|"
    r"seguimiento|promesa\s+de\s+pago|nota)\b"
)
_WRITE_REQUEST = re.compile(
    r"\b(?:crea(?:r|me)?|emite(?:r)?|registra(?:r|me)?|aplica(?:r)?|"
    r"modifica(?:r)?|actualiza(?:r)?|edita(?:r)?|anula(?:r)?|cancela(?:r)?|"
    r"elimina(?:r)?|borra(?:r)?|marca(?:r)?|concilia(?:r)?|sincroniza(?:r)?|"
    r"importa(?:r)?|exporta(?:r)?|envia(?:r)?|contacta(?:r)?|agenda(?:r)?|"
    r"programa(?:r)?|cobra(?:r)?)\b"
)


class ReceivablesAgent(BaseAgent):
    """Expone saldos y alertas de cartera, sin revelar clientes o facturas."""

    id = "receivables"
    name = "Agente de cartera"
    description = "Prioriza saldos de ventas y la calidad de los pagos registrados."
    version = "1.2.0"

    def __init__(
        self,
        session_factory=SessionLocal,
        conversation_narrator: ReceivablesNarrator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._conversation_narrator = conversation_narrator or OpenAIReceivablesNarrator()

    async def execute(self, task: BaseTask, context: Context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="El agente requiere una empresa y un usuario autenticado.",
                errors=["MISSING_RECEIVABLES_SCOPE"],
            )
        try:
            company_id = UUID(context.company_id)
            actor_user_id = int(context.user_id)
        except (TypeError, ValueError):
            return BaseResult(
                success=False,
                message="El contexto de la empresa no es válido.",
                errors=["INVALID_RECEIVABLES_SCOPE"],
            )

        db: Session = self._session_factory()
        try:
            report = ReceivablesService(db).analyze(company_id)
        except Exception:
            logger.exception("receivables analysis failed")
            db.rollback()
            self._record_failure(db, company_id, actor_user_id, task)
            return BaseResult(
                success=False,
                message="No fue posible generar el diagnóstico de cartera.",
                errors=["INTERNAL_ERROR"],
            )
        finally:
            db.close()

        conversation, narration_degraded = await self._conversation_for(
            report=report,
            task=task,
            context=context,
            actor_user_id=actor_user_id,
        )
        db = self._session_factory()
        try:
            self._record_execution(
                db,
                company_id,
                actor_user_id,
                task,
                report,
                "degraded" if narration_degraded else "succeeded",
                "LLM_UNAVAILABLE" if narration_degraded else None,
            )
            db.commit()
        except Exception:
            logger.exception("receivables audit failed")
            db.rollback()
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
                name="Cartera",
                description=(
                    "Diagnóstico y explicación conversacional de saldos de ventas y "
                    "pagos relacionados."
                ),
                keywords=["cartera", "cobros", "saldos pendientes", "pagos parciales"],
            )
        ]

    def _record_failure(
        self,
        db: Session,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
    ) -> None:
        try:
            self._record_execution(
                db,
                company_id,
                actor_user_id,
                task,
                None,
                "failed",
                "INTERNAL_ERROR",
            )
            db.commit()
        except Exception:
            db.rollback()

    def _record_execution(
        self,
        db: Session,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: ReceivablesReport | None,
        status: str,
        error_code: str | None = None,
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
                conversation_id=self._optional_text(task.payload.get("conversation_id"), 36),
                agent_id=self.id,
                agent_version=self.version,
                operation=task.objective[:64],
                status=status,
                finding_count=len(report.findings) if report else 0,
                finding_codes=sorted({finding.code for finding in report.findings}) if report else [],
                error_code=error_code,
                correlation_id=self._optional_text(task.payload.get("correlation_id"), 64),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    async def _conversation_for(
        self,
        *,
        report: ReceivablesReport,
        task: BaseTask,
        context: Context,
        actor_user_id: int,
    ) -> tuple[ReceivablesConversation, bool]:
        finding_codes = tuple(finding.code for finding in report.findings)
        evidence = self._evidence_for(finding_codes)
        if contains_sensitive_text(context.user_message):
            conversation = ReceivablesConversation(
                outcome="clarification_needed",
                response=(
                    "Por seguridad, reformula la pregunta sin documentos, correos, "
                    "credenciales ni otros identificadores personales."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._is_out_of_scope_topic(context.user_message):
            conversation = ReceivablesConversation(
                outcome="out_of_scope",
                response=(
                    "Este agente se limita al diagnóstico agregado de cartera de ventas. "
                    "No responde sobre otros módulos, asesoría concluyente, instrucciones "
                    "internas ni configuraciones del sistema."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._requests_individual_receivables_data(context.user_message):
            conversation = ReceivablesConversation(
                outcome="out_of_scope",
                response=(
                    "Por privacidad, este chat solo ofrece información agregada de cartera "
                    "y no identifica facturas, clientes ni pagos individuales. Consulta "
                    "Cartera operativa para revisar el detalle autorizado por tu rol."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._asks_operational_guidance(context.user_message):
            conversation = ReceivablesConversation(
                outcome="answered",
                response=(
                    "Puedes actualizar términos de pago o registrar un seguimiento desde "
                    "Cartera operativa, si tu rol está autorizado y la empresa está activa. "
                    "El cambio exige confirmación explícita; este chat no lo ejecuta."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._asks_about_collection_guidance(context.user_message):
            conversation = self._priority_conversation(report)
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._requests_write(context.user_message):
            conversation = ReceivablesConversation(
                outcome="out_of_scope",
                response=(
                    "Este chat solo analiza la cartera y no crea, modifica, cobra, "
                    "contacta ni sincroniza información. Para cambios autorizados de "
                    "términos o seguimientos, usa Cartera operativa."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        if self._asks_for_unavailable_metric(context.user_message):
            conversation = ReceivablesConversation(
                outcome="clarification_needed",
                response=(
                    "Puedo resumir la cartera al corte actual por los tramos disponibles. "
                    "Para ese rango, período o indicador específico no tengo una métrica "
                    "verificable en el diagnóstico actual."
                ),
                evidence=evidence,
                suggested_questions=self._suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation, False

        deterministic = self._deterministic_answer(report, context.user_message)
        if deterministic is not None:
            # Las preguntas que piden hechos o métricas conocidas se responden localmente.
            # Así se conservan cifras verificables y el diagnóstico no depende del LLM.
            self._remember_turn(context, context.user_message, deterministic.response)
            return deterministic, False

        narration: ReceivablesNarration | None = None
        try:
            narration = await self._conversation_narrator.narrate(
                question=context.user_message,
                report=report,
                history=self._history(context),
                actor_user_id=actor_user_id,
                correlation_id=self._optional_text(task.payload.get("correlation_id"), 64),
            )
        except Exception:
            logger.warning(
                "receivables narration failed",
                extra={"reason": "unexpected_narration_error"},
            )

        if narration is None:
            # El resumen determinista es la fuente de verdad. Una falla de la capa
            # narrativa no debe ocultar esos hechos ni convertir una consulta de
            # lectura en un error visible para la persona usuaria.
            conversation = self._deterministic_fallback(report, context.user_message)
            narration_degraded = is_enabled(FEATURE_LLM)
        else:
            conversation = ReceivablesConversation(
                outcome=narration.outcome,
                response=redact_sensitive_text(narration.response, max_length=4_000),
                evidence=self._evidence_for(
                    self._verified_finding_codes(report, narration.finding_codes),
                ),
                suggested_questions=self._sanitized_suggested_questions(
                    narration.suggested_questions,
                ),
                llm_used=True,
                llm_model=narration.model,
            )
            narration_degraded = False
        self._remember_turn(context, context.user_message, conversation.response)
        return conversation, narration_degraded

    @staticmethod
    def _evidence_for(
        finding_codes: tuple[str, ...],
        metric_keys: tuple[str, ...] = (),
    ) -> tuple[ReceivablesEvidence, ...]:
        if not finding_codes and not metric_keys:
            return ()
        return (
            ReceivablesEvidence(
                finding_codes=finding_codes,
                metric_keys=metric_keys,
            ),
        )

    @classmethod
    def _deterministic_fallback(
        cls,
        report: ReceivablesReport,
        question: str,
    ) -> ReceivablesConversation:
        """Responde con hechos agregados cuando no hay narración LLM."""

        return cls._deterministic_answer(report, question) or cls._summary_conversation(report)

    @classmethod
    def _deterministic_answer(
        cls,
        report: ReceivablesReport,
        question: str,
    ) -> ReceivablesConversation | None:
        """Enruta preguntas cuantificables a la misma fuente determinista del reporte.

        El orden importa: las familias más específicas se resuelven antes de los
        resúmenes generales. Nunca se usa una fila de factura, cliente o pago.
        """

        normalized = cls._normalize_question(question)
        metrics = report.metrics

        if cls._asks_about_capabilities(normalized):
            return cls._help_conversation(report)
        if cls._asks_about_concept(normalized):
            return cls._concept_conversation(report, normalized)
        if cls._asks_about_alert_explanation(normalized):
            return cls._alert_explanation_conversation(report)
        if cls._asks_about_summary(normalized):
            return cls._summary_conversation(report)
        if cls._asks_about_priority(normalized):
            return cls._priority_conversation(report)
        if cls._asks_about_cartera_status(normalized):
            return cls._summary_conversation(report)
        if cls._asks_about_currency_mismatch(normalized):
            return cls._answered(
                report,
                (
                    f"Hay {metrics.payments_with_currency_mismatch} "
                    f"{cls._payment_label(metrics.payments_with_currency_mismatch)} asociad"
                    f"{'o' if metrics.payments_with_currency_mismatch == 1 else 'os'} en una "
                    "moneda distinta a la factura de venta. Esos pagos no reducen el saldo "
                    "automáticamente hasta revisar la tasa aplicada."
                ),
                finding_codes=("PAYMENTS_WITH_CURRENCY_MISMATCH",),
                metric_keys=("payments_with_currency_mismatch",),
            )
        if cls._asks_about_missing_customer(normalized):
            finding = cls._finding_for(report, "SALES_INVOICES_WITHOUT_CUSTOMER")
            count = cls._finding_evidence_count(finding, "invoices")
            return cls._answered(
                report,
                (
                    f"Hay {count} {cls._invoice_label(count)} de venta sin cliente asociado. "
                    "El chat no identifica cuáles son; revisa el detalle autorizado en "
                    "Cartera operativa."
                ),
                finding_codes=("SALES_INVOICES_WITHOUT_CUSTOMER",),
            )
        if cls._asks_about_missing_due_date(normalized):
            count = metrics.sales_invoices_missing_due_date
            return cls._answered(
                report,
                (
                    f"Hay {count} {cls._invoice_label(count)} de venta sin fecha de vencimiento "
                    "verificable. Completar el vencimiento o las condiciones de pago permite "
                    "medir correctamente su antigüedad."
                ),
                finding_codes=("SALES_INVOICES_MISSING_DUE_DATE",),
                metric_keys=("sales_invoices_missing_due_date", "aging_buckets"),
            )
        if cls._asks_about_payment_promises(normalized):
            return cls._payment_promises_conversation(report, normalized)
        if cls._asks_about_followups(normalized):
            count = metrics.pending_collection_followups
            return cls._answered(
                report,
                f"Hay {count} {cls._followup_label(count)} pendiente"
                f"{'s' if count != 1 else ''} de gestión de cobro.",
                metric_keys=("pending_collection_followups",),
            )
        if cls._asks_about_collection_speed(normalized):
            return cls._collection_speed_conversation(report)
        if cls._asks_about_settled_invoices(normalized):
            count = metrics.settled_sales_invoices
            return cls._answered(
                report,
                f"Hay {count} {cls._invoice_label(count)} de venta liquidada"
                f"{'s' if count != 1 else ''} con pagos registrados.",
                metric_keys=("settled_sales_invoices",),
            )
        if cls._asks_about_overpaid_invoices(normalized):
            count = metrics.overpaid_sales_invoices
            return cls._answered(
                report,
                (
                    f"Hay {count} {cls._invoice_label(count)} con pagos superiores al total "
                    "en la misma moneda. Revisa pagos duplicados, anticipos o notas de ajuste "
                    "antes de aplicar nuevos cobros."
                ),
                finding_codes=("OVERPAID_SALES_INVOICES",),
                metric_keys=("overpaid_sales_invoices",),
            )
        if cls._asks_about_partial_payments(normalized):
            count = metrics.partially_paid_sales_invoices
            return cls._answered(
                report,
                f"Hay {count} {cls._invoice_label(count)} de venta con pagos parciales y saldo pendiente.",
                finding_codes=("PARTIALLY_PAID_SALES_INVOICES",),
                metric_keys=("partially_paid_sales_invoices",),
            )
        if cls._asks_about_unpaid_invoices(normalized):
            count = metrics.unpaid_sales_invoices
            return cls._answered(
                report,
                f"Hay {count} {cls._invoice_label(count)} de venta sin pagos registrados.",
                finding_codes=("UNPAID_SALES_INVOICES",),
                metric_keys=("unpaid_sales_invoices",),
            )
        if cls._asks_about_aging(normalized):
            return cls._aging_conversation(report)
        if cls._asks_about_upcoming_due_dates(normalized):
            return cls._upcoming_due_dates_conversation(report)
        if cls._asks_about_overdue_invoices(normalized):
            return cls._overdue_invoices_conversation(report)
        if cls._asks_about_open_invoices(normalized):
            return cls._open_invoices_conversation(report)
        if cls._asks_about_sales_invoices(normalized):
            return cls._answered(
                report,
                (
                    f"Hay {metrics.sales_invoices} {cls._invoice_label(metrics.sales_invoices)} de venta "
                    f"registrada{'s' if metrics.sales_invoices != 1 else ''}; "
                    f"{metrics.open_sales_invoices} tienen saldo pendiente."
                ),
                metric_keys=("sales_invoices", "open_sales_invoices"),
            )
        if cls._asks_about_outstanding_balance(normalized):
            return cls._outstanding_balance_conversation(report)
        if cls._asks_about_cartera_concept(normalized):
            return cls._answered(
                report,
                (
                    "La cartera reúne los saldos pendientes de facturas de venta y sus pagos "
                    "relacionados. Este diagnóstico los resume por moneda, vencimiento, "
                    "antigüedad y calidad del pago, sin mostrar datos individuales."
                ),
                metric_keys=("open_sales_invoices", "outstanding_balances", "aging_buckets"),
            )
        return None

    @classmethod
    def _upcoming_due_dates_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        future_due = cls._aging_bucket_invoices(report, "not_due")
        due_today = metrics.due_today_sales_invoices
        if future_due and due_today:
            response = (
                f"Tienes {future_due} {cls._invoice_label(future_due)} con vencimiento futuro "
                f"y {due_today} que {cls._due_verb(due_today)} hoy."
            )
        elif future_due:
            response = (
                f"Tienes {future_due} {cls._invoice_label(future_due)} con saldo pendiente "
                "y vencimiento futuro."
            )
        elif due_today:
            response = (
                f"Tienes {due_today} {cls._invoice_label(due_today)} con saldo pendiente "
                f"que {cls._due_verb(due_today)} hoy."
            )
        else:
            response = (
                "No hay facturas con saldo pendiente y vencimiento futuro ni facturas "
                "que venzan hoy."
            )
        return cls._answered(
            report,
            response,
            metric_keys=("due_today_sales_invoices", "aging_buckets"),
        )

    @classmethod
    def _overdue_invoices_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        overdue = metrics.overdue_sales_invoices
        seriously_overdue = metrics.seriously_overdue_sales_invoices
        response = (
            f"Tienes {overdue} {cls._invoice_label(overdue)} "
            f"{'vencida' if overdue == 1 else 'vencidas'} con saldo pendiente."
        )
        if seriously_overdue:
            response += (
                f" De ellas, {seriously_overdue} "
                f"{'supera' if seriously_overdue == 1 else 'superan'} "
                "los noventa días de vencimiento."
            )
        overdue_balances = cls._aging_balances_text(
            report,
            ("overdue_1_30", "overdue_31_60", "overdue_61_90", "overdue_91_plus"),
        )
        if overdue_balances:
            response += f" Saldo vencido por moneda: {overdue_balances}."
        return cls._answered(
            report,
            response,
            finding_codes=(
                "OVERDUE_SALES_INVOICES",
                "SERIOUSLY_OVERDUE_SALES_INVOICES",
            ),
            metric_keys=(
                "overdue_sales_invoices",
                "seriously_overdue_sales_invoices",
                "aging_buckets",
            ),
        )

    @classmethod
    def _aging_conversation(cls, report: ReceivablesReport) -> ReceivablesConversation:
        labels = {
            "not_due": "no vencida",
            "due_today": "vence hoy",
            "overdue_1_30": "de 1 a 30 días vencida",
            "overdue_31_60": "de 31 a 60 días vencida",
            "overdue_61_90": "de 61 a 90 días vencida",
            "overdue_91_plus": "más de 90 días vencida",
            "missing_due_date": "sin fecha de vencimiento",
        }
        parts: list[str] = []
        for bucket in report.metrics.aging_buckets:
            balance = cls._balances_text(bucket.outstanding_balances)
            suffix = f" ({balance})" if balance else ""
            parts.append(
                f"{labels[bucket.key]}: {bucket.invoices} {cls._invoice_label(bucket.invoices)}{suffix}"
            )
        if not parts:
            response = "No hay facturas abiertas para clasificar por antigüedad."
        else:
            response = "La antigüedad de la cartera es: " + "; ".join(parts) + "."
        return cls._answered(report, response, metric_keys=("aging_buckets",))

    @classmethod
    def _outstanding_balance_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        balances = cls._balances_text(report.metrics.outstanding_balances)
        response = (
            f"El saldo pendiente se mantiene separado por moneda: {balances}. "
            "Este diagnóstico no suma ni convierte monedas."
            if balances
            else "No hay saldo pendiente por moneda en el diagnóstico actual."
        )
        return cls._answered(
            report,
            response,
            metric_keys=("outstanding_balances", "open_sales_invoices"),
        )

    @classmethod
    def _open_invoices_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        balances = cls._balances_text(metrics.outstanding_balances)
        response = (
            f"Tienes {metrics.open_sales_invoices} {cls._invoice_label(metrics.open_sales_invoices)} "
            "de venta con saldo pendiente."
        )
        if balances:
            response += f" Saldo abierto por moneda: {balances}."
        return cls._answered(
            report,
            response,
            metric_keys=("open_sales_invoices", "outstanding_balances"),
        )

    @classmethod
    def _payment_promises_conversation(
        cls,
        report: ReceivablesReport,
        question: str,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        asks_broken = bool(re.search(r"\b(?:incumplid|vencid|rota|quebrada|paso)\w*\b", question))
        asks_open = bool(re.search(r"\b(?:activ|vigent|abiert|pendient)\w*\b", question))
        if asks_broken and not asks_open:
            response = (
                f"Hay {metrics.broken_payment_promises} "
                f"{cls._promise_label(metrics.broken_payment_promises)} incumplida"
                f"{'s' if metrics.broken_payment_promises != 1 else ''}. "
                "Confirma el recaudo o actualiza el seguimiento antes de tomar una decisión."
            )
            codes = ("BROKEN_PAYMENT_PROMISES",)
            keys = ("broken_payment_promises",)
        elif asks_open and not asks_broken:
            response = (
                f"Hay {metrics.open_payment_promises} "
                f"{cls._promise_label(metrics.open_payment_promises)} activa"
                f"{'s' if metrics.open_payment_promises != 1 else ''} con saldo pendiente."
            )
            codes = ("OPEN_PAYMENT_PROMISES",)
            keys = ("open_payment_promises",)
        else:
            response = (
                f"Hay {metrics.open_payment_promises} "
                f"{cls._promise_label(metrics.open_payment_promises)} activa"
                f"{'s' if metrics.open_payment_promises != 1 else ''} y "
                f"{metrics.broken_payment_promises} "
                f"{cls._promise_label(metrics.broken_payment_promises)} incumplida"
                f"{'s' if metrics.broken_payment_promises != 1 else ''}."
            )
            codes = ("OPEN_PAYMENT_PROMISES", "BROKEN_PAYMENT_PROMISES")
            keys = ("open_payment_promises", "broken_payment_promises")
        return cls._answered(report, response, finding_codes=codes, metric_keys=keys)

    @classmethod
    def _collection_speed_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        if metrics.average_days_to_collect is None:
            response = (
                "Aún no hay facturas liquidadas con datos verificables para calcular el "
                "promedio operativo de recaudo."
            )
        else:
            response = (
                "El promedio operativo de recaudo es "
                f"{cls._format_amount(metrics.average_days_to_collect)} días, calculado sobre "
                f"{metrics.settled_sales_invoices} {cls._invoice_label(metrics.settled_sales_invoices)} "
                f"liquidada{'s' if metrics.settled_sales_invoices != 1 else ''}. "
                "No es un DSO certificado ni una conciliación bancaria."
            )
        return cls._answered(
            report,
            response,
            metric_keys=("average_days_to_collect", "settled_sales_invoices"),
        )

    @classmethod
    def _priority_conversation(cls, report: ReceivablesReport) -> ReceivablesConversation:
        if not report.findings:
            return cls._summary_conversation(report)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        priorities = sorted(
            report.findings,
            key=lambda finding: (severity_order[finding.severity.value], finding.code),
        )
        response = "Prioriza esta revisión: "
        if report.metrics.seriously_overdue_sales_invoices:
            count = report.metrics.seriously_overdue_sales_invoices
            response += (
                f"{count} {cls._invoice_label(count)} con saldo pendiente supera"
                f"{'n' if count != 1 else ''} los 90 días de vencimiento. "
            )
        response += priority_actions(priorities)
        return cls._answered(
            report,
            response,
            finding_codes=tuple(finding.code for finding in report.findings),
            metric_keys=(
                "open_sales_invoices",
                "overdue_sales_invoices",
                "due_today_sales_invoices",
                "broken_payment_promises",
            ),
        )

    @classmethod
    def _alert_explanation_conversation(
        cls,
        report: ReceivablesReport,
    ) -> ReceivablesConversation:
        if not report.findings:
            return cls._summary_conversation(report)
        explanations = "; ".join(
            f"{finding.message} Acción sugerida: {finding.recommendation}"
            for finding in report.findings[:3]
        )
        return cls._answered(
            report,
            f"Alertas de cartera actuales: {explanations}",
            finding_codes=tuple(finding.code for finding in report.findings),
            metric_keys=("open_sales_invoices", "overdue_sales_invoices"),
        )

    @classmethod
    def _concept_conversation(
        cls,
        report: ReceivablesReport,
        question: str,
    ) -> ReceivablesConversation:
        metrics = report.metrics
        if re.search(r"\b(?:vencid\w*|mora)\b", question):
            return cls._answered(
                report,
                (
                    "Una factura vencida conserva saldo pendiente después de su fecha de "
                    f"vencimiento. En el corte actual hay {metrics.overdue_sales_invoices} "
                    f"{cls._invoice_label(metrics.overdue_sales_invoices)} vencida"
                    f"{'s' if metrics.overdue_sales_invoices != 1 else ''}."
                ),
                finding_codes=("OVERDUE_SALES_INVOICES",),
                metric_keys=("overdue_sales_invoices",),
            )
        if re.search(r"\b(?:pago\s+parcial|parcial(?:es)?)\b", question):
            return cls._answered(
                report,
                (
                    "Un pago parcial cubre solo una parte del total de una factura; el resto "
                    f"del saldo sigue abierto. Hay {metrics.partially_paid_sales_invoices} "
                    f"{cls._invoice_label(metrics.partially_paid_sales_invoices)} con ese estado."
                ),
                finding_codes=("PARTIALLY_PAID_SALES_INVOICES",),
                metric_keys=("partially_paid_sales_invoices",),
            )
        if re.search(r"\b(?:sobrepago|pago\s+superior|pagado\s+de\s+mas)\b", question):
            return cls._answered(
                report,
                (
                    "Un sobrepago ocurre cuando los pagos registrados superan el total de la "
                    f"factura en la misma moneda. Hay {metrics.overpaid_sales_invoices} "
                    f"{cls._invoice_label(metrics.overpaid_sales_invoices)} para revisar."
                ),
                finding_codes=("OVERPAID_SALES_INVOICES",),
                metric_keys=("overpaid_sales_invoices",),
            )
        if re.search(r"\bpromesa\b", question):
            return cls._answered(
                report,
                (
                    "Una promesa de pago es un seguimiento con una fecha comprometida. "
                    f"Actualmente hay {metrics.open_payment_promises} activa"
                    f"{'s' if metrics.open_payment_promises != 1 else ''} y "
                    f"{metrics.broken_payment_promises} incumplida"
                    f"{'s' if metrics.broken_payment_promises != 1 else ''}."
                ),
                finding_codes=("OPEN_PAYMENT_PROMISES", "BROKEN_PAYMENT_PROMISES"),
                metric_keys=("open_payment_promises", "broken_payment_promises"),
            )
        if re.search(r"\b(?:moneda|divisa)\b", question):
            return cls._answered(
                report,
                (
                    "Los saldos se conservan por moneda y no se compensan ni convierten "
                    "automáticamente. Los pagos en moneda distinta requieren revisar la tasa "
                    "aplicada antes de interpretar el saldo."
                ),
                finding_codes=("PAYMENTS_WITH_CURRENCY_MISMATCH",),
                metric_keys=("outstanding_balances", "payments_with_currency_mismatch"),
            )
        if re.search(r"\b(?:sin\s+(?:fecha\s+de\s+)?vencimiento|vencimiento)\b", question):
            return cls._answered(
                report,
                (
                    "La fecha de vencimiento permite clasificar la antigüedad de una factura. "
                    f"Hay {metrics.sales_invoices_missing_due_date} "
                    f"{cls._invoice_label(metrics.sales_invoices_missing_due_date)} sin una fecha "
                    "verificable."
                ),
                finding_codes=("SALES_INVOICES_MISSING_DUE_DATE",),
                metric_keys=("sales_invoices_missing_due_date", "aging_buckets"),
            )
        if re.search(r"\b(?:antiguedad|tramos?)\b", question):
            return cls._answered(
                report,
                (
                    "La antigüedad agrupa los saldos abiertos según su vencimiento: no vencidos, "
                    "vence hoy, 1–30, 31–60, 61–90 y más de 90 días, además de los que no "
                    "tienen vencimiento."
                ),
                metric_keys=("aging_buckets",),
            )
        return cls._answered(
            report,
            (
                "El saldo pendiente es la parte de una factura de venta que aún no está cubierta "
                "por pagos relacionados. El diagnóstico lo muestra separado por moneda y sin "
                "exponer facturas o clientes individuales."
            ),
            metric_keys=("open_sales_invoices", "outstanding_balances"),
        )

    @classmethod
    def _help_conversation(cls, report: ReceivablesReport) -> ReceivablesConversation:
        return cls._answered(
            report,
            (
                "Puedes preguntar por prioridades y alertas, facturas abiertas, saldos por "
                "moneda, vencimientos y antigüedad, pagos parciales o superiores, promesas, "
                "seguimientos y promedio de recaudo. Para una factura, cliente o pago "
                "concreto, consulta Cartera operativa según tu rol."
            ),
            metric_keys=("open_sales_invoices", "outstanding_balances", "aging_buckets"),
        )

    @classmethod
    def _summary_conversation(cls, report: ReceivablesReport) -> ReceivablesConversation:
        return cls._answered(
            report,
            cls._fallback_summary(report),
            finding_codes=tuple(finding.code for finding in report.findings),
            metric_keys=(
                "open_sales_invoices",
                "overdue_sales_invoices",
                "due_today_sales_invoices",
            ),
        )

    @classmethod
    def _answered(
        cls,
        report: ReceivablesReport,
        response: str,
        *,
        finding_codes: tuple[str, ...] = (),
        metric_keys: tuple[str, ...] = (),
    ) -> ReceivablesConversation:
        return ReceivablesConversation(
            outcome="answered",
            response=response,
            evidence=cls._evidence_for(
                cls._finding_codes_for(report, *finding_codes),
                metric_keys,
            ),
            suggested_questions=cls._suggested_questions(),
        )

    @staticmethod
    def _asks_about_upcoming_due_dates(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:por\s+vencer|proxim[oa]s?\s+vencimiento(?:s)?|"
                r"venc(?:e|en)\s+(?:hoy|pronto)|vencimiento(?:s)?\s+"
                r"(?:proxim[oa]s?|pendientes?))\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_overdue_invoices(question: str) -> bool:
        return bool(re.search(r"\b(?:vencid\w*|mora|atrasad\w*|moros\w*)\b", question))

    @staticmethod
    def _asks_about_aging(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:antiguedad|tramos?|rango(?:s)?|1\s*(?:a|-|–)\s*30|"
                r"31\s*(?:a|-|–)\s*60|61\s*(?:a|-|–)\s*90|mas\s+de\s+90)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_outstanding_balance(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:saldo(?:s)?\s+(?:pendiente(?:s)?|abierto(?:s)?)|"
                r"cuanto\s+(?:me\s+)?deben?|monto\s+pendiente|por\s+moneda|"
                r"deuda(?:s)?)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_open_invoices(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:facturas?\s+(?:abiertas?|pendientes?|por\s+cobrar)|"
                r"abiertas?|saldo(?:s)?\s+pendiente(?:s)?|por\s+cobrar)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_sales_invoices(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:cuant[ao]s?|total|numero)\s+(?:de\s+)?facturas?"
                r"(?:\s+de\s+venta)?\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_unpaid_invoices(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:sin\s+pagos?|no\s+tienen?\s+pagos?|sin\s+pago\s+registrado)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_partial_payments(question: str) -> bool:
        return bool(re.search(r"\b(?:pagos?\s+parcial(?:es)?|pago\s+incompleto)\b", question))

    @staticmethod
    def _asks_about_overpaid_invoices(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:sobrepagos?|pagos?\s+superiores?|pagado\s+de\s+mas|"
                r"pago\s+duplicado)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_currency_mismatch(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:moneda\s+distinta|otra\s+moneda|moneda\s+diferente|"
                r"inconsisten\w*\s+de\s+moneda|divisa\s+distinta)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_missing_due_date(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:sin\s+(?:fecha\s+de\s+)?vencimiento|no\s+tienen?\s+"
                r"(?:fecha\s+de\s+)?vencimiento|falta\w*\s+(?:fecha\s+de\s+)?"
                r"vencimiento|sin\s+plazo)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_followups(question: str) -> bool:
        return bool(re.search(r"\b(?:seguimientos?|gestiones?\s+de\s+cobro)\b", question))

    @staticmethod
    def _asks_about_payment_promises(question: str) -> bool:
        return bool(re.search(r"\bpromesas?\s+de\s+pago\b|\bpromesas?\b", question))

    @staticmethod
    def _asks_about_collection_speed(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:promedio\s+(?:de\s+)?(?:dias\s+de\s+)?(?:recaudo|cobro)|"
                r"dias\s+de\s+(?:recaudo|cobro)|tiempo\s+de\s+cobro)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_settled_invoices(question: str) -> bool:
        return bool(re.search(r"\b(?:facturas?\s+(?:pagadas?|liquidadas?|cobradas?))\b", question))

    @staticmethod
    def _asks_about_missing_customer(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:sin\s+cliente(?:\s+asociado)?|cliente\s+asociado|"
                r"sin\s+tercero(?:\s+asociado)?)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_alert_explanation(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:que\s+significa|explica|interpreta)\b.{0,80}\b(?:alertas?|"
                r"cartera|vencid\w*|mora|promesa|pago\s+parcial|sobrepago|moneda)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_priority(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:alertas?|prioriza\w*|prioridad(?:es)?|revisar\s+primero|"
                r"que\s+debo\s+revisar|saldos?\s+requieren?\s+seguimiento|"
                r"estado\s+(?:actual\s+)?(?:de\s+)?(?:la\s+)?cartera|"
                r"como\s+esta\s+(?:la\s+)?cartera|gestionar\s+un\s+cobro|"
                r"antes\s+de\s+cobrar)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_summary(question: str) -> bool:
        return bool(re.search(r"\b(?:resumen|vision\s+general|panorama)\b", question))

    @staticmethod
    def _asks_about_cartera_concept(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:que|como)\s+(?:es|funciona)\s+(?:la\s+)?cartera\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_capabilities(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:que\s+(?:puedo|puedes)\s+(?:preguntar|hacer)|"
                r"como\s+puedes\s+ayudar(?:me)?|ayuda|capacidades?)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_concept(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:que\s+(?:es|significa)|define|explica)\b.{0,100}\b"
                r"(?:factura\s+vencid\w*|mora|pago\s+parcial|sobrepago|"
                r"pago\s+superior|promesa\s+de\s+pago|moneda|divisa|"
                r"antiguedad|saldo\s+pendiente|fecha\s+de\s+vencimiento)\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_cartera_status(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:hay|tengo|tenemos)\s+(?:la\s+)?cartera\b|"
                r"\b(?:como\s+va|estado\s+de)\s+(?:la\s+)?cartera\b",
                question,
            )
        )

    @staticmethod
    def _asks_about_collection_guidance(question: str) -> bool:
        normalized = ReceivablesAgent._normalize_question(question)
        return bool(
            re.search(
                r"\b(?:que\s+debo\s+revisar|como\s+prioriz\w*|"
                r"antes\s+de\s+(?:cobrar|gestionar\s+un\s+cobro)|"
                r"como\s+gestionar\s+la\s+cartera)\b",
                normalized,
            )
        )

    @staticmethod
    def _is_out_of_scope_topic(question: str) -> bool:
        return bool(_OUT_OF_SCOPE_TOPIC_REQUEST.search(ReceivablesAgent._normalize_question(question)))

    @staticmethod
    def _asks_operational_guidance(question: str) -> bool:
        return bool(_OPERATIONAL_GUIDANCE_REQUEST.search(ReceivablesAgent._normalize_question(question)))

    @staticmethod
    def _asks_for_unavailable_metric(question: str) -> bool:
        normalized = ReceivablesAgent._normalize_question(question)
        if re.search(r"\bmas\s+de\s+90\s+dias\b", normalized):
            return False
        return bool(_UNAVAILABLE_METRIC_REQUEST.search(normalized)) or bool(
            re.search(r"\b(?:contactad\w*|resuelt\w*|cancelad\w*)\b", normalized)
        )

    @staticmethod
    def _normalize_question(question: str) -> str:
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", question.casefold())
            if not unicodedata.combining(character)
        )

    @staticmethod
    def _requests_write(question: str) -> bool:
        return bool(_WRITE_REQUEST.search(ReceivablesAgent._normalize_question(question)))

    @staticmethod
    def _requests_individual_receivables_data(question: str) -> bool:
        normalized = ReceivablesAgent._normalize_question(question)
        return any(
            pattern.search(normalized)
            for pattern in (
                _INDIVIDUAL_LIST_REQUEST,
                _INDIVIDUAL_SELECTOR_REQUEST,
                _INDIVIDUAL_REFERENCE_REQUEST,
                _INDIVIDUAL_DESCRIPTOR_REQUEST,
                _INDIVIDUAL_WHAT_REQUEST,
                _INDIVIDUAL_CONDITION_REQUEST,
                _INDIVIDUAL_NAMED_PARTY_REQUEST,
            )
        )

    @staticmethod
    def _finding_for(report: ReceivablesReport, code: str):
        return next((finding for finding in report.findings if finding.code == code), None)

    @staticmethod
    def _finding_evidence_count(finding, key: str) -> int:
        if finding is None:
            return 0
        value = finding.evidence.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        formatted = f"{amount:,.2f}"
        return formatted.replace(",", "_").replace(".", ",").replace("_", ".")

    @classmethod
    def _balances_text(cls, balances) -> str:
        return ", ".join(
            f"{balance.currency_code} {cls._format_amount(balance.amount)}"
            for balance in balances
        )

    @classmethod
    def _aging_balances_text(cls, report: ReceivablesReport, keys: tuple[str, ...]) -> str:
        totals: dict[str, Decimal] = {}
        for bucket in report.metrics.aging_buckets:
            if bucket.key not in keys:
                continue
            for balance in bucket.outstanding_balances:
                totals[balance.currency_code] = (
                    totals.get(balance.currency_code, Decimal("0")) + balance.amount
                )
        return ", ".join(
            f"{currency_code} {cls._format_amount(amount)}"
            for currency_code, amount in sorted(totals.items())
        )

    @staticmethod
    def _payment_label(count: int) -> str:
        return "pago" if count == 1 else "pagos"

    @staticmethod
    def _followup_label(count: int) -> str:
        return "seguimiento" if count == 1 else "seguimientos"

    @staticmethod
    def _promise_label(count: int) -> str:
        return "promesa de pago" if count == 1 else "promesas de pago"

    @staticmethod
    def _aging_bucket_invoices(report: ReceivablesReport, key: str) -> int:
        return next(
            (bucket.invoices for bucket in report.metrics.aging_buckets if bucket.key == key),
            0,
        )

    @staticmethod
    def _finding_codes_for(report: ReceivablesReport, *codes: str) -> tuple[str, ...]:
        known_codes = {finding.code for finding in report.findings}
        return tuple(code for code in codes if code in known_codes)

    @staticmethod
    def _invoice_label(count: int) -> str:
        return "factura" if count == 1 else "facturas"

    @staticmethod
    def _due_verb(count: int) -> str:
        return "vence" if count == 1 else "vencen"

    @classmethod
    def _fallback_summary(cls, report: ReceivablesReport) -> str:
        metrics = report.metrics
        if metrics.sales_invoices == 0:
            return "No hay facturas de venta para analizar la cartera de esta empresa."
        return (
            f"Tienes {metrics.open_sales_invoices} {cls._invoice_label(metrics.open_sales_invoices)} "
            f"con saldo pendiente; {metrics.overdue_sales_invoices} están vencidas y "
            f"{metrics.due_today_sales_invoices} {cls._due_verb(metrics.due_today_sales_invoices)} hoy."
        )

    @staticmethod
    def _verified_finding_codes(
        report: ReceivablesReport,
        finding_codes: tuple[str, ...],
    ) -> tuple[str, ...]:
        known_codes = {finding.code for finding in report.findings}
        return tuple(code for code in finding_codes if code in known_codes)

    @staticmethod
    def _suggested_questions() -> tuple[str, ...]:
        return (
            "¿Qué saldos requieren seguimiento?",
            "¿Qué significa cada alerta de cartera?",
            "¿Qué debo revisar antes de gestionar un cobro?",
        )

    @staticmethod
    def _sanitized_suggested_questions(questions: tuple[str, ...]) -> tuple[str, ...]:
        values: list[str] = []
        for question in questions:
            safe_question = redact_sensitive_text(question, max_length=240)
            if safe_question and safe_question not in values:
                values.append(safe_question)
        return tuple(values)

    @staticmethod
    def _history(context: Context) -> list[dict[str, str]]:
        raw_history = context.metadata.get("receivables_history")
        if not isinstance(raw_history, list):
            return []
        history: list[dict[str, str]] = []
        for turn in raw_history[-8:]:
            if not isinstance(turn, dict):
                continue
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                history.append({"role": role, "content": content})
        return history

    @staticmethod
    def _remember_turn(context: Context, question: str, response: str) -> None:
        history = ReceivablesAgent._history(context)
        history.extend(
            (
                {
                    "role": "user",
                    "content": redact_sensitive_text(question, max_length=600),
                },
                {
                    "role": "assistant",
                    "content": redact_sensitive_text(response, max_length=600),
                },
            )
        )
        context.metadata["receivables_history"] = history[-8:]

    @staticmethod
    def _message_for(report: ReceivablesReport) -> str:
        if report.metrics.sales_invoices == 0:
            return "No hay facturas de venta para analizar la cartera de esta empresa."
        if report.summary.status.value == "healthy":
            return "La cartera no presenta saldos pendientes que requieran atención."
        return (
            "La cartera tiene saldos o relaciones de pago que conviene revisar antes de "
            "continuar con la gestión de cobro."
        )

    @staticmethod
    def _optional_text(value: object, max_length: int) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized[:max_length] or None
