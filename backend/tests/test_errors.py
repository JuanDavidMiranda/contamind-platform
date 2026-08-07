import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.errors import AppError, register_exception_handlers
from app.shared.logging import RequestLoggingMiddleware

pytestmark = pytest.mark.integration


def test_validation_error_shape(client):
    response = client.post("/api/v1/chat", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["recoverable"] is True
    assert isinstance(body["error"]["details"], list)


def test_not_found_error_shape(client):
    response = client.get("/api/v1/ruta-inexistente")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["recoverable"] is True
    assert body["correlation_id"] is not None


def test_unexpected_error_shape():
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secreto interno")

    register_exception_handlers(app)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["recoverable"] is False
    assert "secreto interno" not in response.text


def test_app_error_shape():
    app = FastAPI()

    @app.get("/recurso")
    def recurso():
        raise AppError(
            message="Recurso no disponible.",
            code="resource_unavailable",
            status_code=409,
            details={"resource": "ejemplo"},
        )

    register_exception_handlers(app)

    with TestClient(app) as test_client:
        response = test_client.get("/recurso")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "resource_unavailable"
    assert body["error"]["details"] == {"resource": "ejemplo"}


def test_http_exception_keeps_detail(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "x@y.com", "password": "password123"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
    assert body["error"]["recoverable"] is True
    assert "inválidos" in body["error"]["message"]


def test_existing_endpoints_unchanged(client):
    assert client.get("/health").status_code == 200
    assert client.post(
        "/api/v1/chat", json={"message": "hola", "session_id": "err-1"}
    ).status_code == 200


def test_correlation_id_propagates_to_errors(client):
    response = client.get(
        "/api/v1/ruta-inexistente",
        headers={"X-Request-ID": "trace-abc-123"},
    )
    assert response.status_code == 404
    assert response.json()["correlation_id"] == "trace-abc-123"


def test_correlation_id_propagates_to_internal_error():
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secreto")

    register_exception_handlers(app)
    app.add_middleware(RequestLoggingMiddleware)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom", headers={"X-Request-ID": "trace-xyz"})
    assert response.status_code == 500
    assert response.json()["correlation_id"] == "trace-xyz"
