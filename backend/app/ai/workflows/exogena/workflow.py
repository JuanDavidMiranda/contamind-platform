from app.ai.core.base_result import BaseResult
from app.ai.core.context import Context

from app.ai.workflows.core.base_workflow import BaseWorkflow


class ExogenaWorkflow(BaseWorkflow):

    id = "exogena"

    name = "Preparación Exógena"

    description = "Automatiza el proceso completo de exógena."

    async def execute(
        self,
        context: Context
    ) -> BaseResult:

        return BaseResult(

            success=True,

            message=(
                "Workflow Exógena iniciado correctamente."
            )
        )