from app.ai.core.base_result import BaseResult
from app.ai.core.context import Context
from app.ai.core.base_task import BaseTask

from app.ai.registry import registry

from app.ai.workflows.core.base_workflow import BaseWorkflow


class ExogenaWorkflow(BaseWorkflow):

    id = "exogena"

    name = "Preparación Exógena"

    description = "Workflow de preparación de exógena."

    async def execute(
        self,
        context: Context
    ) -> BaseResult:

        dian_agent = registry.get("dian")

        result = await dian_agent.execute(

            BaseTask(

                objective="hola"

            ),

            context

        )

        return result