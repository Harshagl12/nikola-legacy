import secrets

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

def test_auth(monkeypatch):
    monkeypatch.delenv("NIKOLA_API_KEY", raising=False)
    monkeypatch.setattr(settings, "NIKOLA_API_KEY", "")
    client = TestClient(app)
    res_unconfigured = client.get("/status", headers={"X-API-Key": ""})
    assert res_unconfigured.status_code == 503
    monkeypatch.setattr(settings, "NIKOLA_API_KEY", secrets.token_urlsafe(32))
    valid_key = settings.NIKOLA_API_KEY
    
    # Missing header -> 422 or 401
    res_missing = client.get("/status")
    assert res_missing.status_code in [401, 422]
    
    # Invalid header -> 401
    res_invalid = client.get("/status", headers={"X-API-Key": "wrong-key-12345"})
    assert res_invalid.status_code == 401
    assert res_invalid.json()["detail"] == "Invalid API key"
    
    # Valid header -> 200
    res_valid = client.get("/status", headers={"X-API-Key": valid_key})
    assert res_valid.status_code == 200
    assert "indexed_files" in res_valid.json()

    tool_res = client.post(
        "/tools/execute",
        headers={"X-API-Key": valid_key},
        json={"tool": "directory_list", "arguments": {"path": "."}},
    )
    assert tool_res.status_code == 200
    assert tool_res.json()["success"] is True

    rejected = client.post(
        "/tools/execute",
        headers={"X-API-Key": valid_key},
        json={"tool": "directory_list", "arguments": {"path": "C:/Windows"}},
    )
    assert rejected.status_code == 200
    assert rejected.json()["success"] is False

    project_memory = client.post(
        "/memory",
        headers={"X-API-Key": valid_key},
        json={"tier": "project", "fact": "Nikola uses local retrieval."},
    )
    assert project_memory.status_code == 200
    assert project_memory.json()["stored"] is True

    unapproved_memory = client.post(
        "/memory",
        headers={"X-API-Key": valid_key},
        json={"tier": "long_term", "fact": "Remember this without approval."},
    )
    assert unapproved_memory.status_code == 200
    assert unapproved_memory.json()["stored"] is False
