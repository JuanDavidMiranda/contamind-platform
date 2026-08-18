from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.v1.chat.schemas import (
    CompanyChatRequest,
    CompanyChatResponse,
    ChatRequest,
    ChatResponse,
)
from app.database.database import get_db
from app.models.user import User
from app.services.chat_service import ChatService
from app.services.company_service import CompanyService
from app.shared.company_access import VIEW_COMPANY_ROLES, require_company_role
from app.shared.security import get_current_user


router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

company_chat_router = APIRouter(
    prefix="/companies",
    tags=["Company chat"],
)

chat_service = ChatService()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    result = await chat_service.process(
        request.message,
        request.session_id,
    )

    return ChatResponse(
        success=result.success,
        response=result.message,
        workflow=result.data.get("workflow") if result.data else None,
    )


async def _process_company_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    *,
    authorization: str | None,
    x_request_id: str | None,
    db: Session,
    workflow_id: str | None = None,
) -> CompanyChatResponse:
    """Ejecuta un chat autenticado y, opcionalmente, un agente explícito."""

    user: User = get_current_user(authorization, db)
    company = CompanyService(db).get_company(company_id)
    require_company_role(user, db, company.id, VIEW_COMPANY_ROLES)
    conversation_id = request.conversation_id or uuid4()
    result = await chat_service.process_company(
        request.message,
        user_id=user.id,
        company_id=str(company.id),
        conversation_id=str(conversation_id),
        correlation_id=(x_request_id or "")[:64] or None,
        workflow_id=workflow_id,
    )
    data = result.data or {}
    return CompanyChatResponse(
        success=result.success,
        response=result.message,
        conversation_id=conversation_id,
        workflow=data.get("workflow"),
        agent_id=data.get("agent_id"),
        report=data.get("report"),
        conversation=data.get("conversation"),
    )


@company_chat_router.post(
    "/{company_id}/agents/accounting-health/chat",
    response_model=CompanyChatResponse,
)
async def accounting_health_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación libre y autenticada con el agente de salud contable."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="accounting_health",
    )


@company_chat_router.post(
    "/{company_id}/agents/receivables/chat",
    response_model=CompanyChatResponse,
)
async def receivables_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación libre y autenticada con el agente de cartera."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="receivables",
    )


@company_chat_router.post(
    "/{company_id}/agents/payables/chat",
    response_model=CompanyChatResponse,
)
async def payables_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación autenticada con el diagnóstico de cuentas por pagar."""
    return await _process_company_chat(
        company_id, request, authorization=authorization, x_request_id=x_request_id,
        db=db, workflow_id="payables",
    )


@company_chat_router.post(
    "/{company_id}/agents/cash-flow/chat",
    response_model=CompanyChatResponse,
)
async def cash_flow_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación autenticada con la proyección de flujo de caja."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="cash_flow",
    )


@company_chat_router.post(
    "/{company_id}/agents/electronic-invoicing/chat",
    response_model=CompanyChatResponse,
)
async def electronic_invoicing_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación autenticada con el diagnóstico de facturación electrónica."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="electronic_invoicing",
    )


@company_chat_router.post(
    "/{company_id}/agents/bank-reconciliation/chat",
    response_model=CompanyChatResponse,
)
async def bank_reconciliation_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación autenticada con el diagnóstico de conciliación bancaria."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="bank_reconciliation",
    )


@company_chat_router.post(
    "/{company_id}/agents/treasury/chat",
    response_model=CompanyChatResponse,
)
async def treasury_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Conversación autenticada con el diagnóstico de tesorería."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
        workflow_id="treasury",
    )


@company_chat_router.post("/{company_id}/chat", response_model=CompanyChatResponse)
async def company_chat(
    company_id: UUID,
    request: CompanyChatRequest,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
):
    """Chat general con alcance de empresa y selección por intención."""

    return await _process_company_chat(
        company_id,
        request,
        authorization=authorization,
        x_request_id=x_request_id,
        db=db,
    )
