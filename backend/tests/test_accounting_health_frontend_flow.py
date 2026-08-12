"""Recorrido HTTP que consume el cliente de salud contable.

Protege la integración entre las tres llamadas que hace el frontend: acceso,
empresas disponibles y conversación con el agente.
"""

from uuid import uuid4

import pytest

from app.config.features import FEATURE_LLM
from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.user import User
from app.shared.security import hash_password


pytestmark = pytest.mark.integration


def _create_test_user(email: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            full_name="Usuario de prueba del frontend",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_health_agent_frontend_flow_uses_authenticated_company_context(client, monkeypatch):
    monkeypatch.setitem(settings.FEATURE_FLAGS, FEATURE_LLM, False)
    suffix = uuid4().hex
    email = f"frontend-health-{suffix}@test.local"
    _create_test_user(email)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={
            "tenant_name": f"Tenant frontend {suffix}",
            "company_name": "Empresa de prueba frontend",
        },
    )
    assert onboarding.status_code == 201
    company_id = onboarding.json()["company"]["id"]

    available_companies = client.get("/api/v1/companies/mine", headers=headers)
    assert available_companies.status_code == 200
    companies = available_companies.json()
    assert len(companies) == 1
    assert {
        key: companies[0][key]
        for key in ("id", "name", "status", "functional_currency")
    } == {
        "id": company_id,
        "name": "Empresa de prueba frontend",
        "status": "active",
        "functional_currency": "COP",
    }

    chat = client.post(
        f"/api/v1/companies/{company_id}/agents/accounting-health/chat",
        headers=headers,
        json={"message": "¿Qué debo revisar primero?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["success"] is True
    assert body["workflow"] == "accounting_health"
    assert body["agent_id"] == "accounting_health"
    assert body["conversation"]["outcome"] == "answered"
    assert body["conversation"]["llm_used"] is False
    assert body["report"]["company_id"] == company_id
    assert body["report"]["metrics"]["parties"] == 0
    assert body["report"]["summary"]["finding_count"] >= 1


def test_health_agent_allows_the_browser_preflight_from_the_local_frontend(client):
    response = client.options(
        "/api/v1/companies/00000000-0000-0000-0000-000000000000/agents/accounting-health/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
