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
