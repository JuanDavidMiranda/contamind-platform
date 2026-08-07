import pytest

pytestmark = pytest.mark.integration


def _chat(client, message: str, session_id: str):
    return client.post(
        "/api/v1/chat",
        json={"message": message, "session_id": session_id},
    )


def test_greeting(client):
    response = _chat(client, "hola", "greet-1")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "Hola" in body["response"]
    assert body["workflow"] == "chat"


def test_unknown_message_falls_back_to_chat(client):
    response = _chat(client, "necesito ayuda con la DIAN", "unknown-1")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "No entendí" in body["response"]


def test_exogena_flow_completes_without_errors(client):
    session = "exo-1"

    r1 = _chat(client, "exogena", session)
    assert r1.status_code == 200
    assert "NIT" in r1.json()["response"]

    r2 = _chat(client, "900123456", session)
    assert r2.status_code == 200
    assert "año" in r2.json()["response"]

    r3 = _chat(client, "2026", session)
    assert r3.status_code == 200
    assert r3.json()["success"] is True
    body = r3.json()["response"]
    assert "2026" in body
    assert "900123456" in body


def test_exogena_flow_resets_after_completion(client):
    session = "exo-reset"

    _chat(client, "exogena", session)
    _chat(client, "900123456", session)
    r3 = _chat(client, "2026", session)
    assert r3.json()["success"] is True

    r4 = _chat(client, "hola", session)
    assert "Hola" in r4.json()["response"]


def test_rut_keyword_does_not_crash(client):
    response = _chat(client, "consulta el rut", "rut-1")
    assert response.status_code == 200
    assert response.json()["success"] is True
