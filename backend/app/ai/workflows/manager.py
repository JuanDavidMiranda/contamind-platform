from app.ai.core.context import Context
from app.ai.workflows.core.base_workflow import BaseWorkflow
from app.ai.workflows.core.execution import WorkflowExecution
from app.ai.workflows.exogena.workflow import ExogenaWorkflow


class ChatWorkflow(BaseWorkflow):
    """Workflow seguro de respaldo para mensajes conversacionales."""

    id = "chat"
    name = "Asistente Contamind"
    description = "Atiende mensajes generales y orienta al usuario dentro de la plataforma."

    async def execute(
        self,
        execution: WorkflowExecution,
        context: Context,
    ) -> dict[str, object]:
        result = {
            "type": "assistant_message",
            "message": (
                "Hola, soy el asistente de Contamind. "
                "Puedo orientarte sobre obligaciones, exógena, renta y facturación electrónica."
            ),
            "workflow": self.id,
            "request_id": context.metadata.get("request_id"),
            "entities": context.entities,
        }
        execution.result = result
        return result


class WorkflowManager:
    def __init__(self) -> None:
        self._workflows = {
            "chat": ChatWorkflow(),
            "exogena": ExogenaWorkflow(),
        }

    def register(self, workflow: BaseWorkflow) -> None:
        self._workflows[workflow.id] = workflow

    def get(self, workflow_id: str) -> BaseWorkflow:
        return self._workflows[workflow_id]

    def list(self) -> list[str]:
        return list(self._workflows.keys())


workflow_manager = WorkflowManager()


def get(workflow_id: str) -> BaseWorkflow:
    return workflow_manager.get(workflow_id)
