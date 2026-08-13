"""Activa conciliación bancaria desde una empresa autenticada."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class BankReconciliationWorkflow(BaseWorkflow):
    id = "bank_reconciliation"
    name = "Conciliación bancaria"
    description = "Diagnóstico agregado de extractos y coincidencias bancarias."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita conciliación bancaria desde una empresa autenticada.",
                data={"workflow": self.id},
                errors=["MISSING_BANK_RECONCILIATION_SCOPE"],
            )
        result = await registry.get("bank_reconciliation").execute(
            BaseTask(
                objective="bank_reconciliation",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
