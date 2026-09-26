from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": settings.NIKOLA_API_KEY}


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json().get("status") == "ok"


def test_status_endpoint():
    res = client.get("/status", headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "models_loaded" in data
    assert "indexed_files" in data
    assert "uptime_seconds" in data
    assert "request_count" in data
    assert "average_latency_ms" in data
    assert len(data["models_loaded"]) > 0


def test_models_list_endpoint():
    res = client.get("/models/list", headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "active_model" in data
    assert "qwen" in data["active_model"].lower() or "gguf" in data["active_model"].lower()


def test_ask_endpoint_non_rag():
    res = client.post(
        "/ask",
        json={"query": "Hello Nikola, respond with OK.", "use_rag": False},
        headers=AUTH_HEADERS
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert "conversation_id" in data


def test_solve_screen_endpoint():
    res = client.post("/solve-screen", headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "description" in data
    assert "solution" in data
