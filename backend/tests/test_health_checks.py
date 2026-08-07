import app.api.v1.health as health_module


def test_live_endpoint_returns_ok(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_endpoint_with_db_up(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "up"


class _BrokenEngine:
    class _Connection:
        def __enter__(self):
            raise RuntimeError("connection refused")

        def __exit__(self, *exc):
            return False

    def connect(self):
        return self._Connection()


def test_ready_endpoint_returns_503_without_leaking_internals(client, monkeypatch):
    monkeypatch.setattr(health_module, "engine", _BrokenEngine())
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["recoverable"] is True
    assert body["correlation_id"] is not None
    assert "postgresql" not in response.text.lower()
    assert "contamind" not in response.text.lower()
    assert "5433" not in response.text
    assert "password" not in response.text.lower()
