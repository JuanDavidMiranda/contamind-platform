from app.ai.orchestrator.orchestrator import Orchestrator
from app.ai.core.context import Context


class ChatService:

    def __init__(self):

        self.orchestrator = Orchestrator()

    async def process(
        self,
        message: str,
        session_id: str | None = None
    ):

        context = Context()

        if session_id:
            context.session_id = session_id

        return await self.orchestrator.handle_message(
            message,
            context
        )