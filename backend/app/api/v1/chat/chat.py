from fastapi import APIRouter
from app.ai.core.context import Context
from app.ai.orchestrator.orchestrator import Orchestrator
from backend.app.api.v1.chat.schemas import ChatRequest
from app.ai.session import session_manager

router = APIRouter(tags=["Chat"])

@router.post("/chat")
async def chat(request: ChatRequest):

    orchestrator = Orchestrator()

    context = session_manager.get(
        request.conversation_id
    )

    context.user_message = request.message

    result = await orchestrator.handle_message(
        request.message,
        context
    )

    session_manager.save(context)

    return result