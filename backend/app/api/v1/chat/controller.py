from fastapi import APIRouter

from app.api.v1.chat.schemas import (
    ChatRequest,
    ChatResponse
)

from app.services.chat_service import ChatService

router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)

chat_service = ChatService()


@router.post(
    "",
    response_model=ChatResponse
)
async def chat(request: ChatRequest):

    result = await chat_service.process(
        request.message,
        request.session_id
    )

    return ChatResponse(

        success=result.success,

        response=result.message,

        workflow=result.data.get("workflow")
        if result.data else None
    )