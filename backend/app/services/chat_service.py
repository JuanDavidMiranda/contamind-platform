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

    async def process_company(
        self,
        message: str,
        *,
        user_id: int,
        company_id: str,
        conversation_id: str,
        correlation_id: str | None = None,
        workflow_id: str | None = None,
    ):
        """Procesa una conversación con una clave que no puede cruzar empresas."""

        session_key = f"company:{company_id}:user:{user_id}:conversation:{conversation_id}"
        context = self.sessions.get(session_key)
        context.user_id = str(user_id)
        context.company_id = company_id
        # Estos valores son efímeros: se eliminan antes de persistir la sesión en memoria.
        context.metadata["conversation_id"] = conversation_id
        if correlation_id is not None:
            context.metadata["correlation_id"] = correlation_id
        try:
            if workflow_id is None:
                return await self.orchestrator.handle_message(message, context)
            return await self.orchestrator.handle_message(
                message,
                context,
                forced_workflow=workflow_id,
            )
        finally:
            if context.workflow in {"accounting_health", "receivables"}:
                # El agente conserva solo el historial ya sanitizado; no dejamos
                # la pregunta ni entidades extraídas en la sesión temporal.
                context.user_message = ""
                context.entities = {}
            context.metadata.pop("conversation_id", None)
            context.metadata.pop("correlation_id", None)
            self.sessions.save(context)
