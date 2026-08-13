"""Activa el agente de flujo de caja desde una empresa autenticada."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class CashFlowWorkflow(BaseWorkflow):
    id = "cash_flow"
    name = "Flujo de caja"
    description = "Proyección de solo lectura de movimientos por vencimiento."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita flujo de caja desde una empresa autenticada.",
                data={"workflow": self.id},
                errors=["MISSING_CASH_FLOW_SCOPE"],
            )
        result = await registry.get("cash_flow").execute(
            BaseTask(
                objective="cash_flow",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
