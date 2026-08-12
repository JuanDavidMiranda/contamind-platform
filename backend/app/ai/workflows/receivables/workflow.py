"""Activa el agente de cartera desde el contexto autenticado de empresa."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class ReceivablesWorkflow(BaseWorkflow):
    id = "receivables"
    name = "Cartera"
    description = "Diagnóstico de solo lectura de saldos y pagos de ventas."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita la cartera desde una conversación autenticada de empresa.",
                data={"workflow": self.id},
                errors=["MISSING_RECEIVABLES_SCOPE"],
            )
        agent = registry.get("receivables")
        result = await agent.execute(
            BaseTask(
                objective="receivables",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
