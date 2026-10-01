from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
import backend.main as main
from backend.main import app
from backend.config import settings

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": settings.NIKOLA_API_KEY}


@pytest.fixture(autouse=True)
def prevent_background_service_initialization(monkeypatch):
    monkeypatch.setattr(main, "_schedule_service_initialization", lambda: None)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_LOADING")


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
    if data["model_state"] == "MODEL_READY":
        assert len(data["models_loaded"]) > 0
    else:
        assert data["models_loaded"] == []


def test_models_list_endpoint():
    res = client.get("/models/list", headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "active_model" in data
    assert "qwen" in data["active_model"].lower() or "gguf" in data["active_model"].lower()


def test_ask_endpoint_non_rag(monkeypatch):
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_READY")
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "OK"}}]
    }

    with patch("backend.llm_engine.get_llm", return_value=llm):
        res = client.post(
            "/ask",
            json={"query": "Hello Nikola, respond with OK.", "use_rag": False},
            headers=AUTH_HEADERS
        )

    assert res.status_code == 200
    data = res.json()
    assert data["answer"] == "OK"
    assert "conversation_id" in data


def test_solve_screen_endpoint(monkeypatch):
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_READY")
    monkeypatch.setitem(main.runtime_state, "vision", "VISION_UNAVAILABLE")
    monkeypatch.setitem(main.runtime_state, "errors", {"vision": "Vision model asset is missing"})
    llm = MagicMock()
    llm.supports_vision = False
    llm.text_infer.return_value = "Screen fallback."

    with patch("backend.llm_engine.get_llm", return_value=llm):
        res = client.post("/solve-screen", headers=AUTH_HEADERS)

    assert res.status_code == 503
    data = res.json()
    assert data["detail"]["code"] == "VISION_UNAVAILABLE"
    llm.text_infer.assert_not_called()
