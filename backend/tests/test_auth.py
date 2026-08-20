import pytest
from sqlalchemy import select

from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.user import User
from app.shared.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _create_user(email: str, *, is_admin: bool = False, password: str = "password123") -> User:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name="Test User",
                password_hash=hash_password(password),
                is_platform_admin=is_admin,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def test_login_success(client):
    _create_user("login-ok@test.local")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "login-ok@test.local", "password": "password123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client):
    _create_user("login-wrong@test.local")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "login-wrong@test.local", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_login_unknown_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "no-existe@test.local", "password": "password123"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_protected_route_without_token(client):
    response = client.get("/api/v1/admin/subscriptions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING_TOKEN"


def test_protected_route_with_invalid_token(client):
    response = client.get(
        "/api/v1/admin/subscriptions",
        headers={"Authorization": "Bearer no-es-un-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_protected_route_with_expired_token(client, monkeypatch):
    user = _create_user("expired@test.local")
    monkeypatch.setattr(settings, "AUTH_TOKEN_TTL_MINUTES", -1)
    token = create_access_token(user)
    response = client.get(
        "/api/v1/admin/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_EXPIRED_TOKEN"


def test_non_admin_forbidden(client):
    user = _create_user("not-admin@test.local")
    token = create_access_token(user)
    response = client.get(
        "/api/v1/admin/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_can_list_subscriptions(client):
    user = _create_user("is-admin@test.local", is_admin=True)
    token = create_access_token(user)
    response = client.get(
        "/api/v1/admin/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_private_beta_access_can_onboard_once_and_rotate_its_password(client):
    administrator = _create_user("beta-platform-admin@test.local", is_admin=True)
    administrator_headers = {"Authorization": f"Bearer {create_access_token(administrator)}"}

    created = client.post(
        "/api/v1/admin/beta-access",
        headers=administrator_headers,
        json={
            "full_name": "Cliente de prueba",
            "email": "cliente-beta@test.local",
            "temporary_password": "TemporalBeta2026",
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert isinstance(created_body["id"], int)
    assert created_body["full_name"] == "Cliente de prueba"
    assert created_body["email"] == "cliente-beta@test.local"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "cliente-beta@test.local", "password": "TemporalBeta2026"},
    )
    assert login.status_code == 200
    assert login.json()["requires_password_change"] is True
    original_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {original_token}"}

    blocked_onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=headers,
        json={"tenant_name": "Cliente beta", "company_name": "Empresa cliente"},
    )
    assert blocked_onboarding.status_code == 403
    assert blocked_onboarding.json()["error"]["code"] == "AUTH_PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "TemporalBeta2026",
            "new_password": "NuevaClaveBeta2026",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["access_token"]
    assert changed.json()["requires_password_change"] is False
    rotated_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}

    onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=rotated_headers,
        json={"tenant_name": "Cliente beta", "company_name": "Empresa cliente"},
    )
    assert onboarding.status_code == 201
    second_onboarding = client.post(
        "/api/v1/companies/onboarding",
        headers=rotated_headers,
        json={"tenant_name": "Otro tenant", "company_name": "Otra empresa"},
    )
    assert second_onboarding.status_code == 409
    second_company = client.post(
        f"/api/v1/tenants/{onboarding.json()['tenant']['id']}/companies",
        headers=rotated_headers,
        json={"name": "Empresa no permitida", "functional_currency": "COP"},
    )
    assert second_company.status_code == 409

    expired_session = client.get("/api/v1/companies/mine", headers=headers)
    assert expired_session.status_code == 401
    assert expired_session.json()["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "cliente-beta@test.local", "password": "TemporalBeta2026"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "cliente-beta@test.local", "password": "NuevaClaveBeta2026"},
    ).json()["requires_password_change"] is False


def test_only_a_platform_admin_can_create_private_beta_access(client):
    user = _create_user("beta-no-admin@test.local")
    response = client.post(
        "/api/v1/admin/beta-access",
        headers={"Authorization": f"Bearer {create_access_token(user)}"},
        json={
            "full_name": "No autorizado",
            "email": "no-autorizado-beta@test.local",
            "temporary_password": "TemporalBeta2026",
        },
    )
    assert response.status_code == 403


def test_beta_access_rejects_a_weak_temporary_password(client):
    administrator = _create_user("beta-password-admin@test.local", is_admin=True)
    response = client.post(
        "/api/v1/admin/beta-access",
        headers={"Authorization": f"Bearer {create_access_token(administrator)}"},
        json={
            "full_name": "Clave débil",
            "email": "clave-debil-beta@test.local",
            "temporary_password": "demasiadocorta",
        },
    )
    assert response.status_code == 422
    assert "demasiadocorta" not in response.text
