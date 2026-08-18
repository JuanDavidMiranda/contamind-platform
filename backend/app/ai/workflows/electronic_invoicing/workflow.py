"""Activa el diagnóstico de facturación electrónica en una empresa autenticada."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class ElectronicInvoicingWorkflow(BaseWorkflow):
    id = "electronic_invoicing"
    name = "Facturación electrónica"
    description = "Diagnóstico agregado de solo lectura de evidencia electrónica."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita facturación electrónica desde una empresa autenticada.",
                data={"workflow": self.id},
                errors=["MISSING_ELECTRONIC_INVOICING_SCOPE"],
            )
        result = await registry.get("electronic_invoicing").execute(
            BaseTask(
                objective="electronic_invoicing",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
