"""Activa el diagnóstico de preparación de información exógena."""

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.registry import registry
from app.ai.workflows.core.base_workflow import BaseWorkflow


class ExogenousInformationWorkflow(BaseWorkflow):
    id = "exogenous_information"
    name = "Información exógena"
    description = "Diagnóstico agregado de preparación de datos por año gravable."

    async def execute(self, execution, context) -> BaseResult:
        if context.company_id is None or context.user_id is None:
            return BaseResult(
                success=False,
                message="Solicita información exógena desde una empresa autenticada.",
                data={"workflow": self.id},
                errors=["MISSING_EXOGENOUS_INFORMATION_SCOPE"],
            )
        result = await registry.get("exogenous_information").execute(
            BaseTask(
                objective="exogenous_information",
                payload={
                    "conversation_id": context.metadata.get("conversation_id"),
                    "correlation_id": context.metadata.get("correlation_id"),
                },
            ),
            context,
        )
        result.data["workflow"] = self.id
        return result
