from app.ai.registry import registry
from app.ai.core.base_task import BaseTask


class TaskExecutor:

    async def execute(
        self,
        task,
        context
    ):

        agent = registry.get(task.agent)

        result = await agent.execute(

            BaseTask(

                objective=task.objective

            ),

            context

        )

        task.completed = True

        return result