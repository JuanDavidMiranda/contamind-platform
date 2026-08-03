from app.ai.core.base_task import BaseTask
from app.ai.core.context import Context
from app.ai.core.base_result import BaseResult
from app.ai.orchestrator.dispatcher import Dispatcher
from app.ai.orchestrator.intent_resolver import IntentResolver


class Orchestrator:

    def __init__(self):

        self.dispatcher = Dispatcher()
        self.intent_resolver = IntentResolver()

    async def handle_message(
        self,
        message: str,
        context: Context
    ) -> BaseResult:

        agent_id = self.intent_resolver.resolve(message)

        task = BaseTask(
            objective=message
        )

        agent = self.dispatcher.dispatch(agent_id)

        return await agent.execute(
            task,
            context
        )