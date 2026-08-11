from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.ai.agents.accounting_health.agent import AccountingHealthAgent
from app.ai.agents.accounting_health.schemas import AccountingHealthConversationOutcome
from app.ai.registry import registry as agent_registry
from app.config.features import FEATURE_LLM
from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.accounting import JournalEntryLineRecord, JournalEntryRecord
from app.models.agent import AgentExecutionRecord
from app.models.data_source import ImportBatchRecord, PartyRecord
from app.models.user import User
from app.services.accounting_health_conversation_service import AccountingHealthNarration
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Accounting health test user",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: User, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _manual_source(client, owner: User, tenant_id: str, company_id: str) -> str:
    response = client.post(
        "/api/v1/data-sources",
        headers=_headers(owner),
        json={
            "tenant_id": tenant_id,
            "company_id": company_id,
            "connector_id": "health_manual",
            "display_name": "Contabilidad para salud",
            "kind": "manual_entry",
            "mode": "manual",
            "capabilities": ["parties", "items", "invoices", "payments", "journals"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_accounting_health_agent_reports_aggregates_with_company_scope(client):
    suffix = uuid4().hex
    owner = _create_user(f"health-owner-{suffix}@test.local")
    viewer = _create_user(f"health-viewer-{suffix}@test.local")
    outsider = _create_user(f"health-outsider-{suffix}@test.local")
    owner_headers = _headers(owner)
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=owner_headers,
        json={"tenant_name": f"Tenant health {suffix}", "company_name": "Empresa salud"},
    )
    assert onboarding.status_code == 201
    tenant_id = onboarding.json()["tenant"]["id"]
    company_id = onboarding.json()["company"]["id"]
    assert client.put(
        "/api/v1/company-memberships",
        headers=owner_headers,
        json={"user_id": viewer.id, "company_id": company_id, "role": "viewer"},
    ).status_code == 200
    source_id = _manual_source(client, owner, tenant_id, company_id)

    secret_document = "900111222"
    assert client.post(
        f"/api/v1/data-sources/{source_id}/parties",
        headers=owner_headers,
        json={"party_type": "customer", "name": "Tercero sin documento"},
    ).status_code == 201
    for name in ("Duplicado uno", "Duplicado dos"):
        assert client.post(
            f"/api/v1/data-sources/{source_id}/parties",
            headers=owner_headers,
            json={
                "party_type": "customer",
                "name": name,
                "document_type": "31",
                "document_number": secret_document,
            },
        ).status_code == 201

    item = client.post(
        f"/api/v1/data-sources/{source_id}/manual/items",
        headers=_headers(owner, idempotency_key="health-item"),
        json={
            "code": "HEALTH-ITEM",
            "name": "Ítem sin cuenta",
            "item_type": "service",
            "unit_price": "100",
        },
    )
    assert item.status_code == 201
    invoice = client.post(
        f"/api/v1/data-sources/{source_id}/manual/invoices",
        headers=_headers(owner, idempotency_key="health-invoice"),
        json={
            "invoice_type": "sale",
            "issue_date": "2026-08-11",
            "lines": [
                {
                    "item_id": item.json()["id"],
                    "description": "Venta sin tercero",
                    "quantity": "1",
                    "unit_price": "100",
                }
            ],
        },
    )
    assert invoice.status_code == 201
    assert client.post(
        f"/api/v1/data-sources/{source_id}/manual/payments",
        headers=_headers(owner, idempotency_key="health-payment"),
        json={"payment_date": "2026-08-11", "amount": "100"},
    ).status_code == 201

    db = SessionLocal()
    try:
        journal_id = str(uuid4())
        db.add(
            PartyRecord(
                id=str(uuid4()),
                company_id=company_id,
                data_source_id=source_id,
                party_type="customer",
                name="Duplicado inyectado para diagnóstico",
                document_type="31",
                document_number=secret_document,
                created_by_user_id=owner.id,
                updated_by_user_id=owner.id,
            )
        )
        db.add(
            ImportBatchRecord(
                id=str(uuid4()),
                data_source_id=source_id,
                company_id=company_id,
                entity="items",
                file_format="csv",
                content_sha256="a" * 64,
                accepted_rows=1,
                rejected_rows=2,
                created_by_user_id=owner.id,
            )
        )
        db.add(
            JournalEntryRecord(
                id=journal_id,
                company_id=company_id,
                data_source_id=source_id,
                entry_date=date(2026, 8, 11),
                description="Comprobante inconsistente de prueba",
                source_reference="HEALTH-001",
                idempotency_key="health-unbalanced",
                created_by_user_id=owner.id,
            )
        )
        db.add(
            JournalEntryLineRecord(
                id=str(uuid4()),
                journal_entry_id=journal_id,
                account_code="1305",
                debit="100",
                credit="0",
            )
        )
        db.commit()
    finally:
        db.close()

    no_token = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        json={"message": "revisa la salud contable"},
    )
    assert no_token.status_code == 401
    response = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers={**owner_headers, "X-Request-ID": "accounting-health-trace"},
        json={"message": "revisa la salud contable"},
    )
    assert response.status_code == 200
    body = response.json()
    assert UUID(body["conversation_id"])
    assert body["workflow"] == "accounting_health"
    assert body["agent_id"] == "accounting_health"
    assert body["report"]["company_id"] == company_id
    assert body["report"]["overall_status"] == "critical"
    assert body["report"]["summary"]["status"] == "critical"
    assert body["report"]["metrics"]["parties"] == 3
    codes = {finding["code"] for finding in body["report"]["findings"]}
    assert {
        "IMPORT_REJECTIONS",
        "PARTIES_MISSING_TAX_ID",
        "DUPLICATE_PARTY_DOCUMENT",
        "ITEMS_WITHOUT_LEDGER_ACCOUNT",
        "INVOICE_PARTY_MISSING",
        "UNLINKED_PAYMENTS",
        "UNBALANCED_JOURNAL",
    } <= codes
    assert secret_document not in response.text

    viewer_response = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers=_headers(viewer),
        json={"message": "diagnóstico contable", "conversation_id": body["conversation_id"]},
    )
    assert viewer_response.status_code == 200
    assert viewer_response.json()["report"]["metrics"]["parties"] == 3

    outsider_onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(outsider),
        json={"tenant_name": f"Tenant externo {suffix}", "company_name": "Empresa externa"},
    )
    assert outsider_onboarding.status_code == 201
    external_tenant_id = outsider_onboarding.json()["tenant"]["id"]
    external_company_id = outsider_onboarding.json()["company"]["id"]
    external_source_id = _manual_source(
        client,
        outsider,
        external_tenant_id,
        external_company_id,
    )
    assert client.post(
        f"/api/v1/data-sources/{external_source_id}/parties",
        headers=_headers(outsider),
        json={"party_type": "supplier", "name": "Tercero de otra empresa"},
    ).status_code == 201
    assert client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers=_headers(outsider),
        json={"message": "salud contable"},
    ).status_code == 403
    external_report = client.post(
        f"/api/v1/companies/{external_company_id}/agents/accounting-health/chat",
        headers=_headers(outsider),
        json={"message": "salud contable"},
    )
    assert external_report.status_code == 200
    assert external_report.json()["report"]["metrics"]["parties"] == 1
    isolated_main_report = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers=owner_headers,
        json={"message": "¿Qué requiere atención hoy?"},
    )
    assert isolated_main_report.status_code == 200
    assert isolated_main_report.json()["workflow"] == "accounting_health"
    assert isolated_main_report.json()["report"]["metrics"]["parties"] == 3
    assert isolated_main_report.json()["conversation"]["llm_used"] is False

    db = SessionLocal()
    try:
        executions = list(
            db.scalars(
                select(AgentExecutionRecord)
                .where(AgentExecutionRecord.company_id == company_id)
                .order_by(AgentExecutionRecord.started_at)
            )
        )
        assert len(executions) == 3
        assert executions[0].agent_id == "accounting_health"
        assert executions[0].correlation_id == "accounting-health-trace"
        assert "UNBALANCED_JOURNAL" in executions[0].finding_codes
        assert not hasattr(executions[0], "message")
    finally:
        db.close()


class _StubNarrator:
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.histories: list[object] = []

    async def narrate(self, *, question, report, history, actor_user_id, correlation_id=None):
        self.questions.append(question)
        self.histories.append(history)
        assert report.company_id
        assert actor_user_id > 0
        return AccountingHealthNarration(
            outcome=AccountingHealthConversationOutcome.ANSWERED,
            response="Debes revisar primero los comprobantes críticos.",
            finding_codes=("NO_ACCOUNTING_DATA",),
            suggested_questions=("¿Cómo corrijo ese comprobante?",),
            model="test-conversation-model",
        )


class _UnavailableNarrator:
    async def narrate(self, **kwargs):
        return None


def test_company_chat_answers_a_free_question_with_the_llm_narrator(client):
    suffix = uuid4().hex
    owner = _create_user(f"health-llm-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant LLM {suffix}", "company_name": "Empresa LLM"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]
    narrator = _StubNarrator()
    original_agent = agent_registry.get("accounting_health")
    agent_registry.register(AccountingHealthAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
            headers=_headers(owner),
            json={"message": "¿Qué debería revisar primero?"},
        )
        conversation_id = response.json()["conversation_id"]
        follow_up = client.post(
            f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
            headers=_headers(owner),
            json={
                "message": "¿Cómo corrijo ese hallazgo?",
                "conversation_id": conversation_id,
            },
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    assert follow_up.status_code == 200
    assert follow_up.json()["workflow"] == "accounting_health"
    body = response.json()
    assert body["workflow"] == "accounting_health"
    assert body["response"] == "Debes revisar primero los comprobantes críticos."
    assert body["conversation"] == {
        "outcome": "answered",
        "response": "Debes revisar primero los comprobantes críticos.",
        "evidence": [
            {
                "source": "accounting_health_snapshot",
                "finding_codes": ["NO_ACCOUNTING_DATA"],
                "metric_keys": [],
            }
        ],
        "suggested_questions": ["¿Cómo corrijo ese comprobante?"],
        "llm_used": True,
        "llm_model": "test-conversation-model",
    }
    assert narrator.questions == [
        "¿Qué debería revisar primero?",
        "¿Cómo corrijo ese hallazgo?",
    ]
    assert narrator.histories[0] == []
    assert narrator.histories[1] == [
        {
            "role": "user",
            "content": "¿Qué debería revisar primero?",
        },
        {
            "role": "assistant",
            "content": "Debes revisar primero los comprobantes críticos.",
        },
    ]


def test_general_company_chat_does_not_force_the_health_agent(client):
    suffix = uuid4().hex
    owner = _create_user(f"general-company-chat-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant general {suffix}", "company_name": "Empresa general"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]

    response = client.post(
        f"/api/v1/companies/{company_id}/chat",
        headers=_headers(owner),
        json={"message": "¿Qué debería revisar primero?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "chat"
    assert body["agent_id"] is None
    assert body["report"] is None
    assert body["conversation"] is None


def test_health_agent_blocks_sensitive_input_before_calling_the_narrator(client):
    suffix = uuid4().hex
    owner = _create_user(f"health-privacy-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant privacidad {suffix}", "company_name": "Empresa privacidad"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]
    narrator = _StubNarrator()
    original_agent = agent_registry.get("accounting_health")
    agent_registry.register(AccountingHealthAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
            headers=_headers(owner),
            json={"message": "Revisa el NIT 900111222, por favor."},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["outcome"] == "clarification_needed"
    assert body["conversation"]["llm_used"] is False
    assert narrator.questions == []
    assert "900111222" not in response.text


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuándo debo presentar la próxima exógena?",
        "¿Cuándo debo presentar la próxima exogema?",
    ],
)
def test_health_agent_blocks_exogena_and_a_single_typo_before_calling_the_narrator(
    client,
    monkeypatch,
    question,
):
    suffix = uuid4().hex
    owner = _create_user(f"health-out-of-scope-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant alcance {suffix}", "company_name": "Empresa alcance"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]
    monkeypatch.setattr(settings, "FEATURE_FLAGS", {FEATURE_LLM: False})
    narrator = _StubNarrator()
    original_agent = agent_registry.get("accounting_health")
    agent_registry.register(AccountingHealthAgent(conversation_narrator=narrator))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
            headers=_headers(owner),
            json={"message": question},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "accounting_health"
    assert body["agent_id"] == "accounting_health"
    assert body["response"] == body["conversation"]["response"]
    assert body["conversation"] == {
        "outcome": "out_of_scope",
        "response": (
            "Este agente no responde sobre información exógena ni sus fechas de "
            "presentación. Puedo ayudarte a revisar los hallazgos, la calidad y la "
            "integridad de la información contable disponible."
        ),
        "evidence": [],
        "suggested_questions": [
            "¿Qué hallazgo debo revisar primero?",
            "¿Cómo puedo corregir los hallazgos detectados?",
            "¿Qué significa cada alerta de salud contable?",
        ],
        "llm_used": False,
        "llm_model": None,
    }
    assert narrator.questions == []


def test_health_agent_audits_an_llm_fallback_without_storing_conversation(client, monkeypatch):
    suffix = uuid4().hex
    owner = _create_user(f"health-fallback-{suffix}@test.local")
    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=_headers(owner),
        json={"tenant_name": f"Tenant fallback {suffix}", "company_name": "Empresa fallback"},
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]
    monkeypatch.setattr(settings, "FEATURE_FLAGS", {FEATURE_LLM: True})
    original_agent = agent_registry.get("accounting_health")
    agent_registry.register(AccountingHealthAgent(conversation_narrator=_UnavailableNarrator()))
    try:
        response = client.post(
            f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
            headers=_headers(owner),
            json={"message": "¿Qué debería revisar primero?"},
        )
    finally:
        agent_registry.register(original_agent)

    assert response.status_code == 200
    assert response.json()["conversation"]["outcome"] == "temporarily_unavailable"
    db = SessionLocal()
    try:
        execution = db.scalar(
            select(AgentExecutionRecord).where(AgentExecutionRecord.company_id == company_id)
        )
        assert execution is not None
        assert execution.status == "degraded"
        assert execution.error_code == "LLM_UNAVAILABLE"
        assert not hasattr(execution, "message")
    finally:
        db.close()
