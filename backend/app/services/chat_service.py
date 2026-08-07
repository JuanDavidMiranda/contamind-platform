from app.ai.orchestrator.orchestrator import Orchestrator
from app.ai.session.manager import SessionManager


class ChatService:

    def __init__(self):

        self.orchestrator = Orchestrator()
        self.sessions = SessionManager()

    async def process(
        self,
        message: str,
        session_id: str | None = None
    ):

        context = self.sessions.get(
            session_id or "default"
        )

        result = await self.orchestrator.handle_message(
            message,
            context
        )

        self.sessions.save(context)

        return result
