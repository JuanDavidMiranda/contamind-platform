from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.agents.accounting_health.schemas import (
    AccountingHealthConversation,
    AccountingHealthReport,
)
from app.ai.agents.cash_flow.schemas import CashFlowConversation, CashFlowReport
from app.ai.agents.receivables.schemas import ReceivablesConversation, ReceivablesReport
from app.ai.agents.payables.schemas import PayablesConversation, PayablesReport


class ChatRequest(BaseModel):

    message: str

    session_id: str | None = None


class ChatResponse(BaseModel):

    success: bool

    response: str

    workflow: str | None = None


class CompanyChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    conversation_id: UUID | None = None


class CompanyChatResponse(BaseModel):
    success: bool
    response: str
    conversation_id: UUID
    workflow: str | None = None
    agent_id: str | None = None
    report: (
        AccountingHealthReport
        | ReceivablesReport
        | PayablesReport
        | CashFlowReport
        | None
    ) = None
    conversation: (
        AccountingHealthConversation
        | ReceivablesConversation
        | PayablesConversation
        | CashFlowConversation
        | None
    ) = None
