"""Activa el agente de tesorería desde una empresa autenticada."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class TreasuryWorkflow(BaseWorkflow):
    id = "treasury"
    name = "Tesorería y liquidez"
    description = "Diagnóstico de solo lectura de proyección y conciliación bancaria."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita tesorería desde una empresa autenticada.",
                data={"workflow": self.id},
                errors=["MISSING_TREASURY_SCOPE"],
            )
        result = await registry.get("treasury").execute(
            BaseTask(
                objective="treasury",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
