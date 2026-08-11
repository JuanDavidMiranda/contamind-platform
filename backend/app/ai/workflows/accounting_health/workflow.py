"""Activa el agente de salud contable desde el flujo de conversación seguro."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class AccountingHealthWorkflow(BaseWorkflow):
    id = "accounting_health"
    name = "Salud contable"
    description = "Diagnóstico determinista y de solo lectura de la empresa activa."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita la salud contable desde una conversación autenticada de empresa.",
                data={"workflow": self.id},
                errors=["MISSING_ACCOUNTING_SCOPE"],
            )
        agent = registry.get("accounting_health")
        result = await agent.execute(
            BaseTask(
                objective="accounting_health",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
