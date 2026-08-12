from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai.agents.receivables.agent import ReceivablesAgent
from app.ai.agents.receivables.schemas import ReceivablesConversationOutcome
from app.ai.registry import registry as agent_registry
from app.config.features import FEATURE_LLM
from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.accounting import InvoiceRecord
from app.models.agent import AgentExecutionRecord
from app.models.user import User
from app.services.receivables_conversation_service import ReceivablesNarration
from app.shared.security import create_access_token, hash_password


pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Receivables LLM test user",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


class _StubNarrator:
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.histories: list[object] = []

    async def narrate(self, *, question, report, history, actor_user_id, correlation_id=None):
        self.questions.append(question)
        self.histories.append(history)
        assert report.company_id
        assert actor_user_id > 0
        return ReceivablesNarration(
            outcome=ReceivablesConversationOutcome.ANSWERED,
            response="Primero confirma los pagos pendientes antes de continuar.",
            finding_codes=("NO_SALES_INVOICES",),
            suggested_questions=("¿Cómo preparo la cartera para seguimiento?",),
            model="test-conversation-model",
        )


class _UnavailableNarrator:
    def __init__(self) -> None:
        self.calls = 0

    async def narrate(self, **kwargs):
        self.calls += 1
        return None


def _onboard_company(client, owner: User, suffix: str) -> str:
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant cartera LLM {suffix}", "company_name": "Empresa cartera"},
    )
    assert onboarding.status_code == 201
    return onboarding.json()["company"]["id"]


def test_receivables_agent_answers_with_llm_and_uses_sanitized_history(client):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-llm-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    narrator = _StubNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": "¿Puedes ayudarme a entender el diagnóstico disponible?"},
        )
        conversation_id = response.json()["conversation_id"]
        follow_up = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={
                    "message": "¿Qué conclusión general puedes dar?",
                "conversation_id": conversation_id,
            },
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    assert follow_up.status_code == 200
    body = response.json()
    assert body["workflow"] == "receivables"
    assert body["response"] == "Primero confirma los pagos pendientes antes de continuar."
    assert body["conversation"] == {
        "outcome": "answered",
        "response": "Primero confirma los pagos pendientes antes de continuar.",
        "evidence": [
            {
                "source": "receivables_snapshot",
                "finding_codes": ["NO_SALES_INVOICES"],
                "metric_keys": [],
            }
        ],
        "suggested_questions": ["¿Cómo preparo la cartera para seguimiento?"],
        "llm_used": True,
        "llm_model": "test-conversation-model",
    }
    assert narrator.questions == [
        "¿Puedes ayudarme a entender el diagnóstico disponible?",
        "¿Qué conclusión general puedes dar?",
    ]
    assert narrator.histories[0] == []
    assert narrator.histories[1] == [
        {
            "role": "user",
            "content": "¿Puedes ayudarme a entender el diagnóstico disponible?",
        },
        {
            "role": "assistant",
            "content": "Primero confirma los pagos pendientes antes de continuar.",
        },
    ]


def test_receivables_agent_blocks_sensitive_input_before_calling_narrator(client):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-privacy-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    narrator = _StubNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": "Revisa el NIT 900555888, por favor."},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == "clarification_needed"
    assert body["conversation"]["llm_used"] is False
    assert narrator.questions == []
    assert "900555888" not in response.text


@pytest.mark.parametrize(
    "message",
    (
        "cual es la factura que vence hoy?",
        "que factura vence hoy?",
        "dame el numero de la factura que vence hoy",
        "dame las facturas vencidas",
        "muestrame los clientes morosos",
        "de que cliente es la factura que vence hoy?",
        "dime el correo o telefono del deudor",
        "cuanto debe Cliente Acme?",
        "dime los pagos de la factura FV-001",
        "quien esta en mora?",
        "a quien debo cobrar?",
        "que dice la nota del seguimiento?",
    ),
)
def test_receivables_agent_blocks_individual_invoice_requests_before_narrator(client, message):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-individual-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    narrator = _StubNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": message},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == "out_of_scope"
    assert body["conversation"]["llm_used"] is False
    assert "no identifica facturas" in body["response"]
    assert narrator.questions == []


@pytest.mark.parametrize(
    ("message", "outcome", "expected_fragment"),
    (
        (
            "Actualiza el vencimiento de una factura.",
            "out_of_scope",
            "no crea, modifica, cobra",
        ),
        (
            "Anula una factura de venta.",
            "out_of_scope",
            "no crea, modifica, cobra",
        ),
        (
            "Envia un recordatorio de cobro.",
            "out_of_scope",
            "no crea, modifica, cobra",
        ),
        (
            "Genera nomina.",
            "out_of_scope",
            "se limita al diagnóstico agregado",
        ),
        (
            "Que IVA aplica?",
            "out_of_scope",
            "se limita al diagnóstico agregado",
        ),
        (
            "Debo demandar al cliente?",
            "out_of_scope",
            "se limita al diagnóstico agregado",
        ),
        (
            "Cuantas vencen en los proximos 7 dias?",
            "clarification_needed",
            "no tengo una métrica verificable",
        ),
        (
            "Cual es el DSO?",
            "clarification_needed",
            "no tengo una métrica verificable",
        ),
        (
            "Cuantos seguimientos estan resueltos?",
            "clarification_needed",
            "no tengo una métrica verificable",
        ),
        (
            "Como actualizo las condiciones de pago?",
            "answered",
            "Cartera operativa",
        ),
    ),
)
def test_receivables_agent_resolves_local_scope_before_calling_narrator(
    client,
    message,
    outcome,
    expected_fragment,
):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-scope-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    narrator = _StubNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": message},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == outcome
    assert body["conversation"]["llm_used"] is False
    assert expected_fragment in body["response"]
    assert narrator.questions == []


def test_receivables_agent_answers_aggregate_invoice_questions_locally(client):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-aggregate-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    narrator = _StubNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": "Cuales alertas se relacionan con facturas vencidas?"},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    assert response.json()["conversation"]["outcome"] == "answered"
    assert response.json()["conversation"]["llm_used"] is False
    assert narrator.questions == []


def test_receivables_agent_audits_llm_fallback_as_degraded(client, monkeypatch):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-fallback-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    monkeypatch.setattr(settings, "FEATURE_FLAGS", {FEATURE_LLM: True})
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=_UnavailableNarrator()))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": "¿Puedes ayudarme a entender el diagnóstico disponible?"},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == "answered"
    assert body["conversation"]["llm_used"] is False
    assert "La explicación conversacional no está disponible" not in body["response"]
    db = SessionLocal()
    try:
        execution = db.scalar(
            select(AgentExecutionRecord).where(
                AgentExecutionRecord.company_id == company_id,
                AgentExecutionRecord.agent_id == "receivables",
            )
        )
        assert execution is not None
        assert execution.status == "degraded"
        assert execution.error_code == "LLM_UNAVAILABLE"
        assert not hasattr(execution, "message")
    finally:
        db.close()


def test_receivables_agent_answers_upcoming_due_dates_without_calling_llm(client, monkeypatch):
    suffix = uuid4().hex
    owner = _create_user(f"receivables-upcoming-{suffix}@test.local")
    company_id = _onboard_company(client, owner, suffix)
    db = SessionLocal()
    try:
        db.add_all(
            [
                InvoiceRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    data_source_id="source-not-required-for-analysis",
                    invoice_type="sale",
                    issue_date=date.today(),
                    due_date=date.today() + timedelta(days=7),
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    subtotal=Decimal("100"),
                    tax_total=Decimal("0"),
                    withholding_total=Decimal("0"),
                    total=Decimal("100"),
                    idempotency_key=f"upcoming-{suffix}",
                    created_by_user_id=owner.id,
                ),
                InvoiceRecord(
                    id=str(uuid4()),
                    company_id=company_id,
                    data_source_id="source-not-required-for-analysis",
                    invoice_type="sale",
                    issue_date=date.today(),
                    due_date=date.today(),
                    currency_code="COP",
                    exchange_rate=Decimal("1"),
                    subtotal=Decimal("200"),
                    tax_total=Decimal("0"),
                    withholding_total=Decimal("0"),
                    total=Decimal("200"),
                    idempotency_key=f"today-{suffix}",
                    created_by_user_id=owner.id,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "FEATURE_FLAGS", {FEATURE_LLM: True})
    narrator = _UnavailableNarrator()
    original_agent = agent_registry.get("receivables")
    agent_registry.register(ReceivablesAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/receivables/chat",
            headers=_headers(owner),
            json={"message": "¿Cuántas facturas tengo por vencer?"},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == "answered"
    assert body["response"] == (
        "Tienes 1 factura con vencimiento futuro y 1 que vence hoy."
    )
    assert body["conversation"]["evidence"] == [
        {
            "source": "receivables_snapshot",
            "finding_codes": [],
            "metric_keys": ["due_today_sales_invoices", "aging_buckets"],
        }
    ]
    db = SessionLocal()
    try:
        execution = db.scalar(
            select(AgentExecutionRecord).where(
                AgentExecutionRecord.company_id == company_id,
                AgentExecutionRecord.agent_id == "receivables",
            )
        )
        assert execution is not None
        assert execution.status == "succeeded"
        assert execution.error_code is None
    finally:
        db.close()
    assert narrator.calls == 0
