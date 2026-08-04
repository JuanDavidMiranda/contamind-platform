from pydantic import BaseModel


class ChatRequest(BaseModel):

    message: str

    session_id: str | None = None


class ChatResponse(BaseModel):

    success: bool

    response: str

    workflow: str | None = None