"""Agente de salud contable con hechos deterministas y conversación restringida."""

from datetime import UTC, datetime
import logging
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.agents.accounting_health.schemas import (
    AccountingHealthConversation,
    AccountingHealthEvidence,
    AccountingHealthReport,
)
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
    AccountingHealthNarration,
    AccountingHealthNarrator,
    OpenAIAccountingHealthNarrator,
    contains_sensitive_text,
    redact_sensitive_text,
)
from app.services.accounting_health_service import AccountingHealthService


logger = logging.getLogger("contamind.accounting_health_agent")


# Esta ruta fuerza el agente de salud contable. Antes de acudir a la capa
# conversacional, identifica dominios que el producto resuelve en otro flujo.
# Las expresiones se evalúan sobre texto sin tildes para que "exógena" y
# "exogena" tengan el mismo comportamiento, incluso sin LLM configurado.
_OUT_OF_SCOPE_TOPIC_PATTERNS = (
    re.compile(r"\bmedios\s+magneticos\b"),
)
_OUT_OF_SCOPE_TERMS = ("exogena",)


class AccountingHealthAgent(BaseAgent):
    """Combina hechos deterministas con una narración conversacional restringida."""

    id = "accounting_health"
    name = "Agente de salud contable"
    description = (
        "Responde preguntas sobre cobertura, calidad e integridad usando "
        "hallazgos contables verificables."
    )
    version = "1.2.1"

    def __init__(
        self,
        session_factory=SessionLocal,
        conversation_narrator: AccountingHealthNarrator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._conversation_narrator = conversation_narrator or OpenAIAccountingHealthNarrator()

    async def execute(self, task: BaseTask, context: Context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="El agente requiere una empresa y un usuario autenticado.",
                errors=["MISSING_ACCOUNTING_SCOPE"],
            )
        try:
            company_id = UUID(context.company_id)
            actor_user_id = int(context.user_id)
        except (TypeError, ValueError):
            return BaseResult(
                success=False,
                message="El contexto de la empresa no es válido.",
                errors=["INVALID_ACCOUNTING_SCOPE"],
            )

        db: Session = self._session_factory()
        try:
            report = AccountingHealthService(db).analyze(company_id)
        except Exception:
            logger.exception("accounting health analysis failed")
            db.rollback()
            try:
                self._record_execution(
                    db,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    task=task,
                    report=None,
                    status="failed",
                    error_code="INTERNAL_ERROR",
                )
                db.commit()
            except Exception:
                db.rollback()
            return BaseResult(
                success=False,
                message="No fue posible generar el diagnóstico contable.",
                errors=["INTERNAL_ERROR"],
            )
        finally:
            db.close()

        conversation = await self._conversation_for(
            report=report,
            task=task,
            context=context,
            actor_user_id=actor_user_id,
        )

        db = self._session_factory()
        try:
            self._record_execution(
                db,
                company_id=company_id,
                actor_user_id=actor_user_id,
                task=task,
                report=report,
                status=(
                    "degraded"
                    if conversation.outcome.value == "temporarily_unavailable"
                    else "succeeded"
                ),
                error_code=(
                    "LLM_UNAVAILABLE"
                    if conversation.outcome.value == "temporarily_unavailable"
                    else None
                ),
            )
            db.commit()
        except Exception:
            logger.exception("accounting health audit failed")
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
                name="Salud contable",
                description=(
                    "Diagnóstico y explicación conversacional de cobertura, "
                    "calidad e integridad contable."
                ),
                keywords=[
                    "salud contable",
                    "diagnóstico contable",
                    "revisión contable",
                    "prioridades contables",
                    "calidad de datos contables",
                ],
            )
        ]

    def _record_execution(
        self,
        db: Session,
        *,
        company_id: UUID,
        actor_user_id: int,
        task: BaseTask,
        report: AccountingHealthReport | None,
        status: str,
        error_code: str | None = None,
    ) -> None:
        company = db.get(CompanyRecord, str(company_id))
        if company is None:
            return
        correlation_id = self._optional_text(task.payload.get("correlation_id"), max_length=64)
        conversation_id = self._optional_text(task.payload.get("conversation_id"), max_length=36)
        db.add(
            AgentExecutionRecord(
                id=str(uuid4()),
                tenant_id=company.tenant_id,
                company_id=str(company_id),
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
                agent_id=self.id,
                agent_version=self.version,
                operation=task.objective[:64],
                status=status,
                finding_count=len(report.findings) if report else 0,
                finding_codes=sorted({finding.code for finding in report.findings}) if report else [],
                error_code=error_code,
                correlation_id=correlation_id,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    async def _conversation_for(
        self,
        *,
        report: AccountingHealthReport,
        task: BaseTask,
        context: Context,
        actor_user_id: int,
    ) -> AccountingHealthConversation:
        if contains_sensitive_text(context.user_message):
            conversation = AccountingHealthConversation(
                outcome="clarification_needed",
                response=(
                    "Por seguridad, reformula la pregunta sin documentos, correos, "
                    "credenciales ni otros identificadores personales."
                ),
                evidence=self._evidence_for(
                    tuple(finding.code for finding in report.findings),
                ),
                suggested_questions=self._default_suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation

        if self._is_out_of_scope_question(context.user_message):
            conversation = AccountingHealthConversation(
                outcome="out_of_scope",
                response=(
                    "Este agente no responde sobre información exógena ni sus fechas de "
                    "presentación. Puedo ayudarte a revisar los hallazgos, la calidad y la "
                    "integridad de la información contable disponible."
                ),
                suggested_questions=self._default_suggested_questions(),
            )
            self._remember_turn(context, context.user_message, conversation.response)
            return conversation

        narration: AccountingHealthNarration | None = None
        try:
            narration = await self._conversation_narrator.narrate(
                question=context.user_message,
                report=report,
                history=self._history(context),
                actor_user_id=actor_user_id,
                correlation_id=self._optional_text(
                    task.payload.get("correlation_id"),
                    max_length=64,
                ),
            )
        except Exception:
            logger.warning(
                "accounting health narration failed",
                extra={"reason": "unexpected_narration_error"},
            )
        if narration is None:
            llm_enabled = is_enabled(FEATURE_LLM)
            conversation = AccountingHealthConversation(
                outcome="temporarily_unavailable" if llm_enabled else "answered",
                response=(
                    f"{self._message_for(report)} "
                    "La explicación conversacional no está disponible temporalmente."
                    if llm_enabled
                    else self._message_for(report)
                ),
                evidence=self._evidence_for(
                    tuple(finding.code for finding in report.findings),
                ),
                suggested_questions=self._default_suggested_questions(),
            )
        else:
            conversation = AccountingHealthConversation(
                outcome=narration.outcome,
                response=redact_sensitive_text(narration.response, max_length=4_000),
                evidence=self._evidence_for(
                    self._verified_finding_codes(report, narration.finding_codes),
                ),
                suggested_questions=tuple(
                    redact_sensitive_text(question, max_length=240)
                    for question in narration.suggested_questions
                    if redact_sensitive_text(question, max_length=240)
                ),
                llm_used=True,
                llm_model=narration.model,
            )
        self._remember_turn(context, context.user_message, conversation.response)
        return conversation

    @staticmethod
    def _evidence_for(finding_codes: tuple[str, ...]) -> tuple[AccountingHealthEvidence, ...]:
        if not finding_codes:
            return ()
        return (
            AccountingHealthEvidence(
                finding_codes=finding_codes,
            ),
        )

    @staticmethod
    def _verified_finding_codes(
        report: AccountingHealthReport,
        finding_codes: tuple[str, ...],
    ) -> tuple[str, ...]:
        known_codes = {finding.code for finding in report.findings}
        return tuple(code for code in finding_codes if code in known_codes)

    @staticmethod
    def _default_suggested_questions() -> tuple[str, ...]:
        return (
            "¿Qué hallazgo debo revisar primero?",
            "¿Cómo puedo corregir los hallazgos detectados?",
            "¿Qué significa cada alerta de salud contable?",
        )

    @staticmethod
    def _is_out_of_scope_question(question: str) -> bool:
        """Bloquea de forma local los dominios conocidos ajenos a salud contable."""

        normalized = "".join(
            character
            for character in unicodedata.normalize("NFKD", question.casefold())
            if not unicodedata.combining(character)
        )
        if any(pattern.search(normalized) for pattern in _OUT_OF_SCOPE_TOPIC_PATTERNS):
            return True
        words = re.findall(r"[a-z]+", normalized)
        return any(
            AccountingHealthAgent._is_one_edit_from(word, term)
            for word in words
            for term in _OUT_OF_SCOPE_TERMS
        )

    @staticmethod
    def _is_one_edit_from(value: str, target: str) -> bool:
        """Acepta una errata mínima sin usar coincidencia difusa amplia."""

        if value == target:
            return True
        if abs(len(value) - len(target)) > 1:
            return False
        if len(value) == len(target):
            return sum(left != right for left, right in zip(value, target, strict=True)) <= 1

        shorter, longer = (value, target) if len(value) < len(target) else (target, value)
        shorter_index = 0
        longer_index = 0
        edits = 0
        while shorter_index < len(shorter) and longer_index < len(longer):
            if shorter[shorter_index] == longer[longer_index]:
                shorter_index += 1
                longer_index += 1
                continue
            edits += 1
            if edits > 1:
                return False
            longer_index += 1
        return True

    @staticmethod
    def _history(context: Context) -> list[dict[str, str]]:
        raw_history = context.metadata.get("accounting_health_history")
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
        history = AccountingHealthAgent._history(context)
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
        context.metadata["accounting_health_history"] = history[-8:]

    @staticmethod
    def _optional_text(value: object, *, max_length: int) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized[:max_length] or None

    @staticmethod
    def _message_for(report: AccountingHealthReport) -> str:
        status = report.summary.status.value
        if status == "healthy":
            return "La salud contable no presenta alertas que requieran atención."
        if status == "critical":
            return "La salud contable tiene hallazgos críticos que requieren atención prioritaria."
        return "La salud contable tiene hallazgos que conviene revisar."
