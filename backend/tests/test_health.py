from app.config.settings import settings


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["application"] == "ContaMind AI"
    assert body["version"] == settings.VERSION
    assert body["status"] == "running"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ContaMind AI"


def test_api_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["version"] == settings.VERSION


def test_agents_endpoint(client):
    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
