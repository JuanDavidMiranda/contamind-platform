from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class PayablesWorkflow(BaseWorkflow):
    id = "payables"
    name = "Cuentas por pagar"
    description = "Diagnóstico de solo lectura de obligaciones de compra."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(success=False, message="Solicita cuentas por pagar desde una empresa autenticada.", data={"workflow": self.id}, errors=["MISSING_PAYABLES_SCOPE"])
        result = await registry.get("payables").execute(BaseTask(objective="payables", payload={"conversation_id": context.metadata.get("conversation_id"), "correlation_id": context.metadata.get("correlation_id")}), context)
        result.data["workflow"] = self.id
        return result
