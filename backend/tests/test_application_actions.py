import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.application_actions as actions
import backend.main as main
from backend.application_actions import (
    ApplicationAction,
    ApplicationPlan,
    ApplicationResolution,
    ApplicationResolver,
    ApplicationSpec,
    action_status_message,
    execute_application_plan,
    parse_application_command,
    validate_url,
)
from backend.config import settings
from backend.nl_processor import NLProcessor
from backend.voice_engine import VoiceEngine


@pytest.mark.parametrize(
    ("text", "action", "application"),
    [
        ("Open Chrome", "launch_application", "chrome"),
        ("Launch Chrome", "launch_application", "chrome"),
        ("Open VS Code", "launch_application", "vscode"),
        ("Open Calculator", "launch_application", "calculator"),
        ("Start Google Chrome", "launch_application", "chrome"),
        ("Nikola, open Chrome.", "launch_application", "chrome"),
        ("Close Chrome", "close_application", "chrome"),
        ("Focus Chrome", "focus_application", "chrome"),
        ("Open YouTube", "open_url", "chrome"),
    ],
)
def test_common_application_phrases_share_normalized_actions(text, action, application):
    plan = parse_application_command(text)

    assert plan is not None
    assert (plan.steps[0].action, plan.steps[0].application) == (action, application)


def test_open_chrome_and_website_creates_safe_sequential_plan():
    plan = parse_application_command("Open Chrome and go to YouTube")

    assert plan is not None
    assert [(step.action, step.application) for step in plan.steps] == [
        ("launch_application", "chrome"),
        ("open_url", "chrome"),
    ]
    assert plan.steps[1].url == "https://www.youtube.com"


def test_open_application_with_url_creates_sequential_plan():
    plan = parse_application_command("Open Chrome at https://example.com/path")

    assert plan is not None
    assert plan.steps[1] == ApplicationAction(
        "open_url",
        "chrome",
        "https://example.com/path",
    )


@pytest.mark.parametrize(
    "text",
    [
        "What is PCA?",
        "Search my documents for my resume",
        "Analyze my screen",
        "Open my resume",
        "Open folder C:\\Users\\Harsha\\Documents",
        "open Chrome; powershell -Command calc",
        "run C:\\Windows\\System32\\calc.exe",
    ],
)
def test_questions_rag_screen_and_untrusted_shell_or_paths_are_not_app_actions(text):
    assert parse_application_command(text) is None


def test_unknown_application_is_structured_and_never_resolved_from_user_path():
    plan = parse_application_command("Open Unregistered Application")

    assert plan is not None
    result = execute_application_plan(plan)

    assert result["success"] is False
    assert result["code"] == "APPLICATION_NOT_FOUND"
    assert action_status_message(result) == (
        "I couldn't find Unregistered Application on this computer."
    )


def test_visual_studio_is_ambiguous_when_both_products_are_installed(tmp_path):
    vs = tmp_path / "devenv.exe"
    code = tmp_path / "Code.exe"
    vs.touch()
    code.touch()
    specs = {
        "visual_studio": ApplicationSpec(
            "visual_studio", "Visual Studio", "devenv.exe", lambda: [vs]
        ),
        "vscode": ApplicationSpec(
            "vscode", "Visual Studio Code", "Code.exe", lambda: [code]
        ),
    }
    resolver = ApplicationResolver(specs)

    result = execute_application_plan(
        ApplicationPlan((ApplicationAction("launch_application", "visual_studio"),)),
        resolver,
    )

    assert result["code"] == "AMBIGUOUS_APPLICATION"
    assert result["choices"] == ["Visual Studio", "Visual Studio Code"]
    assert action_status_message(result) == (
        "Did you mean Visual Studio or Visual Studio Code?"
    )


def test_resolver_rejects_candidate_with_unexpected_executable_name(tmp_path):
    invalid = tmp_path / "powershell.exe"
    invalid.touch()
    spec = ApplicationSpec("chrome", "Chrome", "chrome.exe", lambda: [invalid])

    assert ApplicationResolver({"chrome": spec}).resolve("chrome").error == (
        "APPLICATION_NOT_FOUND"
    )


def test_resolver_accepts_expected_executable_name(tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.touch()
    spec = ApplicationSpec("chrome", "Chrome", "chrome.exe", lambda: [executable])

    result = ApplicationResolver({"chrome": spec}).resolve("chrome")

    assert result.executable == executable.resolve()
    assert result.error is None


def test_calculator_package_process_is_matched_only_inside_trusted_windowsapps(tmp_path, monkeypatch):
    trusted_root = tmp_path / "WindowsApps"
    package = trusted_root / "Microsoft.WindowsCalculator_test_x64__8wekyb3d8bbwe"
    trusted_executable = package / "CalculatorApp.exe"
    trusted_executable.parent.mkdir(parents=True)
    trusted_executable.touch()
    trusted_process = SimpleNamespace(
        info={"exe": str(trusted_executable), "name": "CalculatorApp.exe"},
        pid=456,
    )
    unrelated_executable = tmp_path / "Downloads" / "Microsoft.WindowsCalculator_fake" / "CalculatorApp.exe"
    unrelated_executable.parent.mkdir(parents=True)
    unrelated_executable.touch()
    unrelated_process = SimpleNamespace(
        info={"exe": str(unrelated_executable), "name": "CalculatorApp.exe"},
        pid=789,
    )
    monkeypatch.setenv("ProgramFiles", str(tmp_path))

    with patch.object(
        actions.psutil,
        "process_iter",
        return_value=[trusted_process, unrelated_process],
    ):
        matches = actions._matching_processes(Path("C:/Windows/System32/calc.exe"), "calculator")

    assert matches == [trusted_process]


def test_launch_uses_argument_array_without_a_shell_and_verifies_process():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    resolver = MagicMock()
    resolver.resolve.return_value = ApplicationResolution("chrome", "Chrome", executable)
    process = MagicMock()
    process.pid = 987
    process.poll.return_value = None

    with patch.object(actions, "_matching_processes", side_effect=[[], [SimpleNamespace(pid=987)]]), \
         patch.object(actions.subprocess, "Popen", return_value=process) as popen, \
         patch.object(actions.time, "sleep"):
        result = execute_application_plan(
            ApplicationPlan((ApplicationAction("launch_application", "chrome"),)),
            resolver,
        )

    popen.assert_called_once_with(
        [str(executable)],
        shell=False,
        close_fds=True,
    )
    assert result["success"] is True
    assert result["steps"][0]["process_id"] == 987


def test_calculator_launch_waits_for_its_window_before_reporting_success():
    executable = Path(
        "C:/Program Files/WindowsApps/Microsoft.WindowsCalculator/"
        "CalculatorApp.exe"
    )
    resolution = ApplicationResolution("calculator", "Calculator", executable)
    process = MagicMock()
    process.pid = 987
    process.poll.return_value = None
    windows = MagicMock(side_effect=[[], [1234]])

    with patch.object(
        actions,
        "_matching_processes",
        return_value=[SimpleNamespace(pid=987)],
    ), patch.object(actions, "_application_windows", windows), patch.object(
        actions.subprocess,
        "Popen",
        return_value=process,
    ), patch.object(actions.time, "sleep"):
        result = actions._launch(
            ApplicationAction("launch_application", "calculator"),
            resolution,
        )

    assert result["success"] is True
    assert windows.call_count == 2


def test_launch_failure_returns_friendly_structured_error():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    resolver = MagicMock()
    resolver.resolve.return_value = ApplicationResolution("chrome", "Chrome", executable)

    with patch.object(actions, "_matching_processes", return_value=[]), \
         patch.object(actions.subprocess, "Popen", side_effect=OSError("private OS detail")):
        result = execute_application_plan(
            ApplicationPlan((ApplicationAction("launch_application", "chrome"),)),
            resolver,
        )

    assert result["success"] is False
    assert result["code"] == "LAUNCH_FAILED"
    assert "private OS detail" not in action_status_message(result)


def test_already_running_application_is_not_launched_twice():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    resolver = MagicMock()
    resolver.resolve.return_value = ApplicationResolution("chrome", "Chrome", executable)
    running = SimpleNamespace(pid=321)

    with patch.object(actions, "_matching_processes", return_value=[running]), \
         patch.object(actions.subprocess, "Popen") as popen:
        result = execute_application_plan(
            ApplicationPlan((ApplicationAction("launch_application", "chrome"),)),
            resolver,
        )

    assert result["success"] is True
    assert result["steps"][0]["already_running"] is True
    popen.assert_not_called()


def test_focus_targets_only_a_window_owned_by_the_resolved_application():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    user32 = MagicMock()
    user32.SetForegroundWindow.return_value = True

    with patch.object(actions.sys, "platform", "win32"), \
         patch.object(actions.ctypes, "windll", SimpleNamespace(user32=user32)), \
         patch.object(actions, "_matching_processes", return_value=[SimpleNamespace(pid=55)]), \
         patch.object(actions, "_windows_for_processes", return_value=[808]):
        result = actions._focus(
            ApplicationAction("focus_application", "chrome"),
            ApplicationResolution("chrome", "Chrome", executable),
        )

    assert result["success"] is True
    user32.ShowWindow.assert_called_once_with(808, 9)
    user32.SetForegroundWindow.assert_called_once_with(808)


def test_close_sends_window_close_and_verifies_target_window_exit():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    user32 = MagicMock()

    with patch.object(actions.sys, "platform", "win32"), \
         patch.object(actions.ctypes, "windll", SimpleNamespace(user32=user32)), \
         patch.object(actions, "_matching_processes", return_value=[SimpleNamespace(pid=55)]), \
         patch.object(actions, "_windows_for_processes", side_effect=[[808], []]), \
         patch.object(actions.time, "sleep"):
        result = actions._close(
            ApplicationAction("close_application", "chrome"),
            ApplicationResolution("chrome", "Chrome", executable),
        )

    assert result["success"] is True
    assert result["windows_closed"] == 1
    user32.PostMessageW.assert_called_once_with(808, 0x0010, 0, 0)


def test_focus_and_close_report_when_application_has_no_open_window():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    resolution = ApplicationResolution("chrome", "Chrome", executable)

    with patch.object(actions.sys, "platform", "win32"), \
         patch.object(actions, "_matching_processes", return_value=[]), \
         patch.object(actions, "_windows_for_processes", return_value=[]):
        focused = actions._focus(
            ApplicationAction("focus_application", "chrome"),
            resolution,
        )
        closed = actions._close(
            ApplicationAction("close_application", "chrome"),
            resolution,
        )

    assert focused["code"] == "PROCESS_NOT_FOUND"
    assert closed["code"] == "PROCESS_NOT_FOUND"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("http://localhost:8080/path", "http://localhost:8080/path"),
    ],
)
def test_http_url_validation(url, expected):
    assert validate_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
        "https://user:password@example.com",
        "https://example.com:99999",
        "https://bad host.example",
    ],
)
def test_unsafe_or_invalid_url_is_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_invalid_open_url_is_reported_without_launching():
    plan = parse_application_command("Open Chrome at javascript:alert(1)")
    assert plan is not None
    assert plan.steps[0].action == "invalid_url"
    assert execute_application_plan(plan)["code"] == "INVALID_URL"


def test_url_action_passes_only_validated_url_as_process_argument():
    executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    resolver = MagicMock()
    resolver.resolve.return_value = ApplicationResolution("chrome", "Chrome", executable)
    process = MagicMock()
    process.pid = 123
    process.poll.return_value = None

    with patch.object(actions, "_matching_processes", return_value=[SimpleNamespace(pid=123)]), \
         patch.object(actions.subprocess, "Popen", return_value=process) as popen:
        result = execute_application_plan(
            ApplicationPlan((
                ApplicationAction("open_url", "chrome", "https://example.com"),
            )),
            resolver,
        )

    popen.assert_called_once_with(
        [str(executable), "https://example.com"],
        shell=False,
        close_fds=True,
    )
    assert result["success"] is True


def test_existing_nl_processor_uses_shared_application_action_service():
    processor = NLProcessor()
    expected = {"success": True, "action": "launch_application", "application": "chrome"}

    with patch("backend.nl_processor.execute_application_plan", return_value=expected) as execute:
        result = processor.process_command("Open Chrome")

    execute.assert_called_once()
    assert result["result"] == expected
    assert result["description"] == "Chrome is open."


def test_authenticated_chat_route_uses_same_action_plan_without_model_or_rag(monkeypatch):
    monkeypatch.setattr(main, "rag", None)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_LOADING")
    result = {
        "success": True,
        "action": "launch_application",
        "application": "chrome",
        "display_name": "Chrome",
        "steps": [],
    }
    monkeypatch.setattr(main, "execute_application_plan", lambda _plan: result)

    response = TestClient(main.app).post(
        "/ask",
        headers={"X-API-Key": settings.NIKOLA_API_KEY},
        json={"query": "Open Chrome", "use_rag": True, "source": "voice"},
    )

    assert response.status_code == 200
    assert response.json()["action_state"] == "succeeded"
    assert response.json()["action_state"] == "succeeded"
    assert response.json()["action_result"] == result
    assert response.json()["answer"] == "Chrome is open."
    event = TestClient(main.app).get(
        "/actions/recent",
        headers={"X-API-Key": settings.NIKOLA_API_KEY},
    )
    assert event.json()["state"] == "succeeded"
    assert event.json()["source"] == "voice"


def test_authenticated_streaming_chat_reports_action_start_and_completion(monkeypatch):
    monkeypatch.setattr(main, "rag", None)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_LOADING")
    monkeypatch.setattr(
        main,
        "execute_application_plan",
        lambda _plan: {
            "success": True,
            "action": "launch_application",
            "application": "chrome",
            "display_name": "Chrome",
            "steps": [],
        },
    )

    response = TestClient(main.app).post(
        "/ask",
        headers={"X-API-Key": settings.NIKOLA_API_KEY},
        json={"query": "Open Chrome", "stream": True},
    )

    assert response.status_code == 200
    assert '"event": "action_start"' in response.text
    assert '"source": "text"' in response.text
    assert "Opening Chrome..." in response.text
    assert '"action_state": "succeeded"' in response.text
    assert "Chrome is open." in response.text


def test_screen_request_keeps_using_existing_screen_analyzer(monkeypatch):
    screen_response = SimpleNamespace(
        description="Current screen context.",
        solution="Screen analysis result.",
        model_dump=lambda: {
            "description": "Current screen context.",
            "solution": "Screen analysis result.",
        },
    )
    monkeypatch.setattr(main, "solve_screen", AsyncMock(return_value=screen_response))
    monkeypatch.setattr(main, "rag", None)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_READY")

    response = TestClient(main.app).post(
        "/ask",
        headers={"X-API-Key": settings.NIKOLA_API_KEY},
        json={"query": "Nikola, analyze my screen.", "use_rag": True},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "Current screen context.\n\nScreen analysis result."
    )
    assert response.json()["action_result"]["solution"] == "Screen analysis result."


def test_explicit_document_search_is_routed_to_existing_rag(monkeypatch):
    class FakeRag:
        queried = False

        async def query(self, query):
            self.queried = True
            return ["A verified indexed document."], ["resume.txt"]

    fake_rag = FakeRag()
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "The indexed resume is available."}}]
    }
    monkeypatch.setattr(main, "rag", fake_rag)
    monkeypatch.setitem(main.runtime_state, "model", "MODEL_READY")

    with patch("backend.llm_engine.get_llm", return_value=llm), \
         patch("backend.main.get_capabilities", return_value={
             "daily_response_limit": None,
             "local_inference": True,
             "llama_server_url": "http://127.0.0.1:8080/v1",
             "configured_model": "local-model",
             "native_model_loaded": False,
             "external_server_required": False,
         }), \
         patch("backend.main.verify_answer", return_value=(
             "The indexed resume is available.",
             {"supported": True, "rejected_claims": 0},
         )):
        response = TestClient(main.app).post(
            "/ask",
            headers={"X-API-Key": settings.NIKOLA_API_KEY},
            json={"query": "Search my documents for my resume.", "use_rag": False},
        )

    assert response.status_code == 200
    assert fake_rag.queried is True
    assert response.json()["sources"] == ["resume.txt"]


def test_always_on_voice_posts_to_shared_authenticated_ask_route():
    response = MagicMock(status_code=200)
    response.json.return_value = {"answer": "Chrome is open."}

    class ClientContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return response

    captured = {}
    engine = VoiceEngine.__new__(VoiceEngine)
    engine.backend_url = "http://127.0.0.1:8000"
    engine._async_speak = AsyncMock()

    async def exercise_voice_request():
        with patch("backend.voice_engine.settings.NIKOLA_API_KEY", "configured-key"), \
             patch("backend.voice_engine.httpx.AsyncClient", return_value=ClientContext()):
            await engine._handle_query("open Chrome")

    asyncio.run(exercise_voice_request())

    assert captured["url"] == "http://127.0.0.1:8000/ask"
    assert captured["headers"] == {"X-API-Key": "configured-key"}
    assert captured["json"] == {
        "query": "open Chrome",
        "use_rag": True,
        "source": "voice",
    }
    engine._async_speak.assert_awaited_once_with("Chrome is open.")


def test_wake_word_recognizes_nikola_and_removes_spoken_prefix():
    engine = VoiceEngine.__new__(VoiceEngine)
    engine.wake_word = "hey nikola"

    assert engine._contains_wake_word("Nikola, open Chrome")
    assert engine._contains_wake_word("Hey Nikola, open Chrome")
    assert engine._remove_wake_word("Nikola, open Chrome").strip(" ,.!?") == "open Chrome"


def test_local_tts_is_reused_for_voice_response():
    engine = VoiceEngine.__new__(VoiceEngine)
    engine._enabled = True
    engine.piper_engine = MagicMock()

    engine.speak("Chrome is open.")

    engine.piper_engine.speak.assert_called_once_with("Chrome is open.")


def test_local_whisper_transcription_remains_available():
    engine = VoiceEngine.__new__(VoiceEngine)
    engine.whisper_model = MagicMock()
    engine.whisper_model.transcribe.return_value = (
        iter([SimpleNamespace(text=" open Chrome ")]),
        SimpleNamespace(),
    )

    assert engine._transcribe([b"\x00\x00" * 480]) == "open chrome"


def test_microphone_selector_prefers_default_input_and_reports_device(monkeypatch):
    engine = VoiceEngine.__new__(VoiceEngine)
    engine._microphone_state = "MICROPHONE_UNKNOWN"
    engine._microphone_device = None
    engine._microphone_index = None
    engine._last_voice_error = None
    devices = [
        {"name": "Default output", "max_input_channels": 0},
        {"name": "Microphone Array", "max_input_channels": 2},
    ]
    fake_sounddevice = SimpleNamespace(
        default=SimpleNamespace(device=(1, 3)),
        query_devices=lambda: devices,
    )
    monkeypatch.setattr("backend.voice_engine.sd", fake_sounddevice)

    assert engine._choose_sounddevice_input() == 1
    assert engine.microphone_device == "Microphone Array"
    assert engine.microphone_state == "MICROPHONE_UNKNOWN"


def test_microphone_selector_reports_unavailable_input(monkeypatch):
    engine = VoiceEngine.__new__(VoiceEngine)
    engine._microphone_state = "MICROPHONE_UNKNOWN"
    engine._microphone_device = None
    engine._microphone_index = None
    engine._last_voice_error = None
    fake_sounddevice = SimpleNamespace(
        default=SimpleNamespace(device=(-1, -1)),
        query_devices=lambda: [{"name": "Output only", "max_input_channels": 0}],
    )
    monkeypatch.setattr("backend.voice_engine.sd", fake_sounddevice)

    assert engine._choose_sounddevice_input() is None
    assert engine.microphone_state == "MICROPHONE_UNAVAILABLE"
    assert engine.last_voice_error == "No input microphone device found"


def test_filesystem_policy_stays_separate_from_application_actions():
    plan = parse_application_command("Open Chrome")

    assert plan is not None
    assert plan.steps == (ApplicationAction("launch_application", "chrome"),)
    assert not hasattr(actions, "authorize_path")
