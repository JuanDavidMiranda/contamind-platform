from __future__ import annotations

import logging
from uuid import uuid4

from app.ai.core.context import Context
from app.ai.extractor.extractor import EntityExtractor
from app.ai.orchestrator.intent_resolver import IntentResolver
from app.ai.workflows import manager
from app.ai.workflows.core.execution import WorkflowExecution

logger = logging.getLogger(__name__)


class OrchestrationError(RuntimeError):
    """Error controlado durante la resolución o ejecución de un workflow."""

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        workflow_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.workflow_id = workflow_id


class Orchestrator:
    def __init__(self) -> None:
        self.intent_resolver = IntentResolver()
        self.extractor = EntityExtractor()

    async def handle_message(
        self,
        message: str,
        context: Context,
    ):
        normalized_message = message.strip()
        if not normalized_message:
            raise OrchestrationError("El mensaje no puede estar vacío.")

        request_id = str(context.metadata.setdefault("request_id", uuid4()))
        context.user_message = normalized_message

        workflow_id = self.intent_resolver.resolve(normalized_message)
        if not workflow_id:
            raise OrchestrationError(
                "No fue posible determinar el workflow solicitado.",
                request_id=request_id,
            )

        try:
            workflow = manager.get(workflow_id)
        except (KeyError, ValueError, AttributeError) as exc:
            raise OrchestrationError(
                "El workflow solicitado no está disponible.",
                request_id=request_id,
                workflow_id=workflow_id,
            ) from exc

        if workflow is None or not hasattr(workflow, "execute"):
            raise OrchestrationError(
                "El workflow configurado no se puede ejecutar.",
                request_id=request_id,
                workflow_id=workflow_id,
            )

        context.workflow = workflow_id
        context.state = "RUNNING"

        try:
            entities = self.extractor.extract(normalized_message)
            context.entities = entities or {}

            execution = WorkflowExecution(workflow_id=workflow.id)
            result = await workflow.execute(execution, context)

            context.state = "COMPLETED"
            logger.info(
                "Workflow completed",
                extra={
                    "request_id": request_id,
                    "workflow_id": workflow_id,
                    "company_id": context.company_id,
                    "user_id": context.user_id,
                },
            )
            return result
        except OrchestrationError:
            context.state = "FAILED"
            raise
        except Exception as exc:
            context.state = "FAILED"
            logger.exception(
                "Workflow execution failed",
                extra={
                    "request_id": request_id,
                    "workflow_id": workflow_id,
                    "company_id": context.company_id,
                    "user_id": context.user_id,
                },
            )
            raise OrchestrationError(
                "No fue posible completar la operación solicitada.",
                request_id=request_id,
                workflow_id=workflow_id,
            ) from exc
