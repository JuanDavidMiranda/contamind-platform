from fastapi import APIRouter
from app.ai.core.context import Context
from app.ai.orchestrator.orchestrator import Orchestrator
from app.api.v1.schemas import ChatRequest

router = APIRouter(tags=["Chat"])


@router.post("/chat")
async def chat(request: ChatRequest):

    orchestrator = Orchestrator()

    context = Context(
        user_message=request.message
    )

    result = await orchestrator.handle_message(
        request.message,
        context
    )

    return result