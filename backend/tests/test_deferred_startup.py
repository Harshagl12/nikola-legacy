import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import backend.main as main
from backend.config import settings


def test_backend_import_defers_rag_and_uses_local_vault():
    assert main.rag is None
    assert Path(settings.VAULT_PATH).resolve() == Path(r"C:\nikola\vault").resolve()


def _client(monkeypatch):
    monkeypatch.setattr(main, "_schedule_service_initialization", lambda: None)
    return TestClient(main.app)


def test_health_and_ready_remain_available_when_services_fail(monkeypatch):
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_ERROR")
    monkeypatch.setitem(main.runtime_state, "rag", "RAG_ERROR")
    monkeypatch.setitem(main.runtime_state, "errors", {"model": "model unavailable", "rag": "vault rejected"})
    monkeypatch.setenv("NIKOLA_API_KEY", settings.NIKOLA_API_KEY)

    with _client(monkeypatch) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        status = client.get(
            "/status",
            headers={"X-API-Key": settings.NIKOLA_API_KEY},
        )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["pid"] == os.getpid()
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["backend"] == "BACKEND_READY"
    assert ready.json()["model"] == "MODEL_ERROR"
    assert ready.json()["rag"] == "RAG_ERROR"
    assert ready.json()["service_errors"] == {
        "model": "Initialization failed. Check backend/backend.log.",
        "rag": "Initialization failed. Check backend/backend.log.",
    }
    assert status.status_code == 200
    assert status.json()["rag_state"] == "RAG_ERROR"
    assert status.json()["service_errors"] == {
        "model": "model unavailable",
        "rag": "vault rejected",
    }


def test_rag_routes_return_service_unavailable_before_initialization(monkeypatch):
    monkeypatch.setattr(main, "rag", None)
    monkeypatch.setitem(main.runtime_state, "rag", "RAG_ERROR")
    monkeypatch.setenv("NIKOLA_API_KEY", settings.NIKOLA_API_KEY)

    with _client(monkeypatch) as client:
        response = client.get(
            "/rag/files",
            headers={"X-API-Key": settings.NIKOLA_API_KEY},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["detail"]["service"] == "rag"
    assert response.json()["detail"]["state"] == "RAG_ERROR"


def test_non_rag_chat_remains_available_without_rag(monkeypatch):
    monkeypatch.setattr(main, "rag", None)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_READY")
    monkeypatch.setenv("NIKOLA_API_KEY", settings.NIKOLA_API_KEY)
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "Hello from the local model."}}]
    }

    with patch("backend.llm_engine.get_llm", return_value=llm):
        with _client(monkeypatch) as client:
            response = client.post(
                "/ask",
                json={"query": "Say hello.", "use_rag": False},
                headers={"X-API-Key": settings.NIKOLA_API_KEY},
            )

    assert response.status_code == 200
    assert response.json()["answer"] == "Hello from the local model."
    assert response.json()["sources"] == []
