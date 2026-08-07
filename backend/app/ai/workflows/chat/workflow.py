from app.ai.core.base_result import BaseResult
from app.ai.workflows.core.base_workflow import BaseWorkflow


class ChatWorkflow(BaseWorkflow):

    id = "chat"

    name = "Chat general"

    description = (
        "Responde conversación general cuando no existe un "
        "workflow especializado para la solicitud."
    )

    async def execute(self, execution, context):

        message = (context.user_message or "").strip().lower()

        if message in ("hola", "buenas", "buenos días", "buenas tardes", "hey"):

            return BaseResult(
                success=True,
                message="¡Hola! Soy ContaMind AI. ¿En qué puedo ayudarte?",
                data={"workflow": self.id},
            )

        return BaseResult(
            success=True,
            message=(
                "No entendí tu solicitud. "
                "Puedes pedirme, por ejemplo: 'exógena'."
            ),
            data={"workflow": self.id},
        )
