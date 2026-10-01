import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nikola_launcher.health_check import wait_for_backend
from nikola_launcher.process_manager import ProcessManager


def test_backend_readiness_stops_polling_when_child_exits():
    process = MagicMock()
    process.poll.return_value = 1

    with patch("urllib.request.urlopen") as urlopen:
        assert wait_for_backend(timeout=10, process=process) is False

    urlopen.assert_not_called()


def test_backend_readiness_requires_health_from_managed_child():
    process = SimpleNamespace(pid=1234, poll=lambda: None)
    parent = MagicMock()
    parent.pid = 1234
    parent.children.return_value = []
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"status": "ok", "pid": 1234}).encode()
    response.__enter__.return_value = response

    with patch("nikola_launcher.health_check.psutil.Process", return_value=parent), \
         patch("urllib.request.urlopen", return_value=response):
        assert wait_for_backend(timeout=1, process=process) is True


def test_backend_readiness_accepts_managed_windows_python_child():
    process = SimpleNamespace(pid=1234, poll=lambda: 0)
    child = SimpleNamespace(pid=4321)
    parent = MagicMock()
    parent.pid = 1234
    parent.children.return_value = [child]
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"status": "ok", "pid": 4321}).encode()
    response.__enter__.return_value = response

    with patch("nikola_launcher.health_check.psutil.Process", return_value=parent), \
         patch("urllib.request.urlopen", return_value=response):
        assert wait_for_backend(timeout=1, process=process) is True


def test_environment_values_are_loaded_for_supervised_children(tmp_path, monkeypatch):
    env_name = "NIKOLA_TEST_CHILD_ENV_HANDOFF"
    monkeypatch.delenv(env_name, raising=False)
    (tmp_path / ".env").write_text(
        f"export {env_name} = 'local-test-value'\n",
        encoding="utf-8",
    )

    ProcessManager(tmp_path)._load_env()

    assert os.environ[env_name] == "local-test-value"


def test_dotenv_key_is_authoritative_for_managed_children(tmp_path, monkeypatch):
    monkeypatch.setenv("NIKOLA_API_KEY", "inherited-stale-key")
    (tmp_path / ".env").write_text(
        "NIKOLA_API_KEY='dotenv-authoritative-key'\n",
        encoding="utf-8",
    )

    ProcessManager(tmp_path)._load_env(require_api_key=True)

    assert os.environ["NIKOLA_API_KEY"] == "dotenv-authoritative-key"
    assert os.environ.copy()["NIKOLA_API_KEY"] == "dotenv-authoritative-key"


def test_missing_dotenv_key_cannot_fall_back_to_inherited_key(tmp_path, monkeypatch):
    monkeypatch.setenv("NIKOLA_API_KEY", "inherited-stale-key")
    (tmp_path / ".env").write_text("VOICE_ENABLED=false\n", encoding="utf-8")

    try:
        ProcessManager(tmp_path)._load_env(require_api_key=True)
    except RuntimeError as error:
        assert "NIKOLA_API_KEY" in str(error)
    else:
        raise AssertionError("A missing authoritative .env key must stop service startup.")
    assert "NIKOLA_API_KEY" not in os.environ


def test_authoritative_key_is_inherited_by_new_child_processes(tmp_path, monkeypatch):
    key = "dotenv-authoritative-key"
    (tmp_path / ".env").write_text(f"NIKOLA_API_KEY={key}\n", encoding="utf-8")
    monkeypatch.delenv("NIKOLA_API_KEY", raising=False)
    ProcessManager(tmp_path)._load_env(require_api_key=True)

    assert os.environ.copy()["NIKOLA_API_KEY"] == key
