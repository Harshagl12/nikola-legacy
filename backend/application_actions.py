"""Allowlisted desktop application actions shared by text, voice, and NL routes."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import psutil

from backend.logger import get_logger

logger = get_logger(__name__)

_LAUNCH_VERIFY_TIMEOUT = 5.0
_CLOSE_VERIFY_TIMEOUT = 3.0
_SAFE_TARGET = re.compile(r"^[\w .()+:/?&=%#@-]{1,2048}$", re.UNICODE)
_WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "wikipedia": "https://www.wikipedia.org",
}


@dataclass(frozen=True)
class ApplicationSpec:
    app_id: str
    display_name: str
    executable: str
    candidate_paths: Callable[[], list[Path]]
    process_names: tuple[str, ...] = ()
    package_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplicationAction:
    action: str
    application: str
    url: str | None = None


@dataclass(frozen=True)
class ApplicationPlan:
    steps: tuple[ApplicationAction, ...]


@dataclass(frozen=True)
class ApplicationResolution:
    app_id: str
    display_name: str
    executable: Path | None = None
    error: str | None = None
    choices: tuple[str, ...] = ()


def _program_roots() -> tuple[Path, ...]:
    values = (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
    )
    return tuple(dict.fromkeys(Path(value) for value in values if value))


def _chrome_paths() -> list[Path]:
    paths = [
        root / "Google" / "Chrome" / "Application" / "chrome.exe"
        for root in _program_roots()
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")
    return paths


def _vscode_paths() -> list[Path]:
    paths = [
        root / "Microsoft VS Code" / "Code.exe"
        for root in _program_roots()
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(Path(local) / "Programs" / "Microsoft VS Code" / "Code.exe")
    return paths


def _visual_studio_paths() -> list[Path]:
    return [
        root / "Microsoft Visual Studio" / year / edition / "Common7" / "IDE" / "devenv.exe"
        for root in _program_roots()
        for year in ("2022", "2019", "2017")
        for edition in ("Community", "Professional", "Enterprise", "BuildTools")
    ]


def _windows_system_paths(executable: str) -> list[Path]:
    if sys.platform != "win32":
        return []
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return [root / "System32" / executable, root / executable]


_APPLICATIONS = {
    "chrome": ApplicationSpec("chrome", "Chrome", "chrome.exe", _chrome_paths),
    "vscode": ApplicationSpec("vscode", "Visual Studio Code", "Code.exe", _vscode_paths),
    "visual_studio": ApplicationSpec(
        "visual_studio",
        "Visual Studio",
        "devenv.exe",
        _visual_studio_paths,
    ),
    "calculator": ApplicationSpec(
        "calculator",
        "Calculator",
        "calc.exe",
        lambda: _windows_system_paths("calc.exe"),
        process_names=("CalculatorApp.exe",),
        package_prefixes=("Microsoft.WindowsCalculator_",),
    ),
    "notepad": ApplicationSpec(
        "notepad",
        "Notepad",
        "notepad.exe",
        lambda: _windows_system_paths("notepad.exe"),
    ),
    "explorer": ApplicationSpec(
        "explorer",
        "File Explorer",
        "explorer.exe",
        lambda: _windows_system_paths("explorer.exe"),
    ),
}

_ALIASES = {
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "chrome": "chrome",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "v s code": "vscode",
    "code insiders": "vscode",
    "visual studio": "visual_studio",
    "calculator": "calculator",
    "calc": "calculator",
    "notepad": "notepad",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "explorer": "explorer",
}

_NON_APPLICATION_TARGETS = (
    "file",
    "folder",
    "directory",
    "document",
    "screen",
    "desktop",
    "settings",
    "my ",
    "the file",
    "the folder",
    "the document",
)


def validate_url(raw_url: str) -> str:
    """Accept only explicit HTTP(S) URLs with a valid host and no credentials."""
    url = raw_url.strip().rstrip(".,!?")
    if any(ord(character) < 32 or character.isspace() for character in url):
        raise ValueError("Invalid URL")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("Only HTTP and HTTPS URLs can be opened")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid URL") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("Invalid URL")
    try:
        parsed.hostname.encode("idna")
    except UnicodeError as error:
        raise ValueError("Invalid URL") from error
    return url


def _resolve_website(value: str) -> str | None:
    normalized = value.strip().lower().rstrip(".,!?")
    if normalized in _WEBSITES:
        return _WEBSITES[normalized]
    if normalized.startswith(("http://", "https://")):
        return validate_url(normalized)
    if re.fullmatch(r"(?:www\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?:\.[a-z]{2,})(?:/[^\s]*)?", normalized):
        return validate_url(f"https://{normalized.removeprefix('www.')}")
    return None


def _application_target(value: str) -> tuple[str | None, str]:
    normalized = re.sub(r"\s+", " ", value.strip().lower()).strip(" .,!?:;")
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if normalized == alias:
            return _ALIASES[alias], ""
        if normalized.startswith(alias + " "):
            return _ALIASES[alias], normalized[len(alias):].strip()
    return None, normalized


def parse_application_command(text: str) -> ApplicationPlan | None:
    """Parse safe imperative app commands without asking the LLM to choose tools."""
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(r"^(?:hey\s+)?nikola[\s,.:!-]*", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.rstrip(" .!?")
    match = re.match(
        r"^(open|launch|start|run|close|quit|exit|focus|switch to|bring up|bring to front)\s+(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    verb = match.group(1).lower()
    target = match.group(2).strip()
    if not _SAFE_TARGET.fullmatch(target):
        return None

    if verb == "open":
        try:
            website = _resolve_website(target)
        except ValueError:
            return ApplicationPlan((ApplicationAction("invalid_url", "chrome", target),))
        if website:
            return ApplicationPlan((ApplicationAction("open_url", "chrome", website),))

    separator = re.search(r"\s+(?:and\s+)?(?:go to|navigate to|at)\s+(.+)$", target, re.IGNORECASE)
    url = _resolve_website(separator.group(1)) if separator else None
    app_text = target[:separator.start()].strip() if separator else target
    app_id, remainder = _application_target(app_text)

    if app_id is None:
        lowered = app_text.lower()
        if any(term in lowered for term in _NON_APPLICATION_TARGETS):
            return None
        if verb in {"close", "quit", "exit", "focus", "switch to", "bring up", "bring to front"}:
            return None
        if not _SAFE_TARGET.fullmatch(app_text):
            return None
        return ApplicationPlan((ApplicationAction("launch_application", lowered),))

    if separator and (not url or remainder):
        return ApplicationPlan((ApplicationAction("invalid_url", app_id, separator.group(1)),))

    if verb in {"close", "quit", "exit"}:
        return ApplicationPlan((ApplicationAction("close_application", app_id),))
    if verb in {"focus", "switch to", "bring up", "bring to front"}:
        return ApplicationPlan((ApplicationAction("focus_application", app_id),))
    if remainder:
        return None

    if url:
        return ApplicationPlan((
            ApplicationAction("launch_application", app_id),
            ApplicationAction("open_url", app_id, url),
        ))
    return ApplicationPlan((ApplicationAction("launch_application", app_id),))


class ApplicationResolver:
    """Resolve a fixed set of app IDs to expected executable paths."""

    def __init__(self, specifications: dict[str, ApplicationSpec] | None = None):
        self.specifications = specifications or _APPLICATIONS

    def _candidates(self, spec: ApplicationSpec) -> list[Path]:
        return spec.candidate_paths()

    def _validated_executable(self, spec: ApplicationSpec) -> Path | None:
        expected = os.path.normcase(spec.executable)
        seen: set[str] = set()
        for candidate in self._candidates(spec):
            try:
                resolved = candidate.expanduser().resolve(strict=True)
                normalized = os.path.normcase(str(resolved))
                if normalized in seen:
                    continue
                seen.add(normalized)
                if resolved.is_file() and os.path.normcase(resolved.name) == expected:
                    return resolved
            except (OSError, RuntimeError):
                continue
        return None

    def resolve(self, app_id: str) -> ApplicationResolution:
        if app_id == "visual_studio":
            visual_studio = self._validated_executable(self.specifications["visual_studio"])
            vscode = self._validated_executable(self.specifications["vscode"])
            if visual_studio and vscode:
                return ApplicationResolution(
                    app_id,
                    "Visual Studio",
                    error="AMBIGUOUS_APPLICATION",
                    choices=("Visual Studio", "Visual Studio Code"),
                )
            if vscode:
                return ApplicationResolution("vscode", "Visual Studio Code", vscode)
            if visual_studio:
                return ApplicationResolution("visual_studio", "Visual Studio", visual_studio)
            return ApplicationResolution(
                "visual_studio",
                "Visual Studio",
                error="APPLICATION_NOT_FOUND",
            )

        spec = self.specifications.get(app_id)
        if spec is None:
            return ApplicationResolution(
                app_id,
                app_id.replace("_", " ").title(),
                error="APPLICATION_NOT_FOUND",
            )
        executable = self._validated_executable(spec)
        if executable is None:
            return ApplicationResolution(
                app_id,
                spec.display_name,
                error="APPLICATION_NOT_FOUND",
            )
        return ApplicationResolution(app_id, spec.display_name, executable)


def _matching_processes(executable: Path, app_id: str | None = None) -> list[psutil.Process]:
    expected = os.path.normcase(str(executable.resolve()))
    spec = _APPLICATIONS.get(app_id or "")
    windows_apps_root = Path(
        os.environ.get("ProgramFiles", r"C:\Program Files")
    ) / "WindowsApps"
    processes: list[psutil.Process] = []
    for process in psutil.process_iter(("exe", "name")):
        try:
            actual = process.info.get("exe")
            if not actual:
                continue
            actual_path = Path(actual).resolve()
            if os.path.normcase(str(actual_path)) == expected:
                processes.append(process)
                continue
            if (
                spec is None
                or not spec.process_names
                or process.info.get("name") not in spec.process_names
                or not any(
                    actual_path.parent.name.startswith(prefix)
                    for prefix in spec.package_prefixes
                )
                or os.path.normcase(str(actual_path.parent.parent))
                != os.path.normcase(str(windows_apps_root.resolve(strict=False)))
            ):
                continue
            processes.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, RuntimeError):
            continue
    return processes


def _windows_for_processes(
    processes: list[psutil.Process],
    hosted_title: str | None = None,
) -> list[int]:
    if sys.platform != "win32":
        return []
    handles: list[int] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if any(process.pid == process_id.value for process in processes):
            handles.append(int(hwnd))
            return True
        if hosted_title and processes:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value.casefold() == hosted_title.casefold():
                try:
                    host = psutil.Process(process_id.value)
                    expected_host = Path(
                        os.environ.get("SystemRoot", r"C:\Windows")
                    ) / "System32" / "ApplicationFrameHost.exe"
                    if os.path.normcase(host.exe()) == os.path.normcase(str(expected_host)):
                        handles.append(int(hwnd))
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                    pass
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return handles


def _application_windows(
    processes: list[psutil.Process],
    app_id: str,
) -> list[int]:
    hosted_title = "Calculator" if app_id == "calculator" else None
    return _windows_for_processes(processes, hosted_title)


def _action_error(action: ApplicationAction, code: str, message: str) -> dict:
    return {
        "success": False,
        "action": action.action,
        "application": action.application,
        "code": code,
        "error": message,
    }


def _execute_action(
    action: ApplicationAction,
    resolver: ApplicationResolver,
) -> dict:
    if action.action == "invalid_url":
        return _action_error(action, "INVALID_URL", "Only valid HTTP or HTTPS URLs can be opened.")
    if action.action not in {
        "launch_application",
        "open_url",
        "close_application",
        "focus_application",
    }:
        return _action_error(action, "UNSUPPORTED_ACTION", "That application action is not supported.")
    if action.action == "open_url":
        try:
            url = validate_url(action.url or "")
        except ValueError:
            return _action_error(action, "INVALID_URL", "Only valid HTTP or HTTPS URLs can be opened.")
    else:
        url = None

    resolution_started = time.perf_counter()
    resolution = resolver.resolve(action.application)
    logger.info(
        "Application resolution completed",
        application=action.application,
        resolution_error=resolution.error,
        resolution_ms=round((time.perf_counter() - resolution_started) * 1000, 1),
    )
    if resolution.error == "AMBIGUOUS_APPLICATION":
        return {
            **_action_error(action, "AMBIGUOUS_APPLICATION", "Please choose an application."),
            "choices": list(resolution.choices),
        }
    if resolution.error or resolution.executable is None:
        return _action_error(
            action,
            "APPLICATION_NOT_FOUND",
            f"I couldn't find {resolution.display_name} on this computer.",
        )

    executable = resolution.executable
    result_action = ApplicationAction(action.action, resolution.app_id, url)
    if action.action == "launch_application":
        existing = _matching_processes(executable, resolution.app_id)
        if existing:
            return {
                "success": True,
                "action": action.action,
                "application": resolution.app_id,
                "display_name": resolution.display_name,
                "already_running": True,
                "process_id": existing[0].pid,
            }
        return _launch(result_action, resolution)
    if action.action == "open_url":
        return _launch(result_action, resolution)
    if action.action == "focus_application":
        return _focus(result_action, resolution)
    return _close(result_action, resolution)


def _launch(action: ApplicationAction, resolution: ApplicationResolution) -> dict:
    started = time.perf_counter()
    try:
        arguments = [str(resolution.executable)]
        if action.action == "open_url" and action.url:
            arguments.append(action.url)
        process = subprocess.Popen(arguments, shell=False, close_fds=True)
    except PermissionError:
        return _action_error(action, "PERMISSION_DENIED", f"I don't have permission to open {resolution.display_name}.")
    except (OSError, ValueError) as error:
        logger.warning("Application launch failed", application=action.application, error=str(error))
        return _action_error(action, "LAUNCH_FAILED", f"I couldn't open {resolution.display_name}.")

    deadline = time.monotonic() + _LAUNCH_VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        matches = _matching_processes(resolution.executable, resolution.app_id)
        window_ready = (
            action.application != "calculator"
            or bool(_application_windows(matches, resolution.app_id))
        )
        if matches and window_ready:
            logger.info(
                "Application action verified",
                action=action.action,
                application=resolution.app_id,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return {
                "success": True,
                "action": action.action,
                "application": resolution.app_id,
                "display_name": resolution.display_name,
                "already_running": False,
                "process_id": matches[0].pid,
                "url": action.url,
            }
        if process.poll() is not None and process.returncode:
            break
        time.sleep(0.1)
    logger.warning("Application launch could not be verified", application=action.application)
    return _action_error(action, "LAUNCH_UNVERIFIED", f"I couldn't verify that {resolution.display_name} opened.")


def _focus(action: ApplicationAction, resolution: ApplicationResolution) -> dict:
    if sys.platform != "win32":
        return _action_error(action, "UNSUPPORTED_PLATFORM", "Focusing applications is supported on Windows.")
    processes = _matching_processes(resolution.executable, resolution.app_id)
    windows = _application_windows(processes, resolution.app_id)
    if not windows:
        return _action_error(action, "PROCESS_NOT_FOUND", f"{resolution.display_name} is not open.")
    user32 = ctypes.windll.user32
    hwnd = windows[0]
    try:
        user32.ShowWindow(hwnd, 9)
        focused = bool(user32.SetForegroundWindow(hwnd))
        foreground = user32.GetForegroundWindow()
        if focused or foreground == hwnd:
            return {
                "success": True,
                "action": action.action,
                "application": action.application,
                "display_name": resolution.display_name,
            }
    except (OSError, psutil.Error):
        pass
    return _action_error(action, "FOCUS_FAILED", f"I couldn't focus {resolution.display_name}.")


def _close(action: ApplicationAction, resolution: ApplicationResolution) -> dict:
    if sys.platform != "win32":
        return _action_error(action, "UNSUPPORTED_PLATFORM", "Closing applications is supported on Windows.")
    processes = _matching_processes(resolution.executable, resolution.app_id)
    windows = _application_windows(processes, resolution.app_id)
    if not windows:
        return _action_error(action, "PROCESS_NOT_FOUND", f"{resolution.display_name} has no open window.")
    user32 = ctypes.windll.user32
    for hwnd in windows:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
    deadline = time.monotonic() + _CLOSE_VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        current_processes = _matching_processes(
            resolution.executable,
            resolution.app_id,
        )
        if not _application_windows(current_processes, resolution.app_id):
            return {
                "success": True,
                "action": action.action,
                "application": action.application,
                "display_name": resolution.display_name,
                "windows_closed": len(windows),
            }
        time.sleep(0.1)
    return _action_error(action, "CLOSE_UNVERIFIED", f"I couldn't verify that {resolution.display_name} closed.")


def execute_application_plan(
    plan: ApplicationPlan,
    resolver: ApplicationResolver | None = None,
) -> dict:
    """Execute only parsed, registered app actions in order, stopping on failure."""
    app_resolver = resolver or ApplicationResolver()
    started = time.perf_counter()
    results = []
    for action in plan.steps:
        result = _execute_action(action, app_resolver)
        results.append(result)
        if not result["success"]:
            break
    last = results[-1] if results else {"success": False, "code": "EMPTY_PLAN"}
    result = {
        "success": last["success"],
        "steps": results,
        "action": last.get("action"),
        "application": last.get("application"),
        "display_name": last.get("display_name"),
        "code": last.get("code"),
        "error": last.get("error"),
        "choices": last.get("choices", []),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info(
        "Application action plan completed",
        success=result["success"],
        action=result.get("action"),
        application=result.get("application"),
        steps=len(results),
        elapsed_ms=result["elapsed_ms"],
    )
    return result


def action_status_message(result: dict) -> str:
    """Return a friendly message without exposing internal exception details."""
    code = result.get("code")
    name = result.get("display_name") or str(
        result.get("application") or "application"
    ).replace("_", " ").title()
    if code == "AMBIGUOUS_APPLICATION":
        choices = result.get("choices", ["Visual Studio", "Visual Studio Code"])
        return f"Did you mean {' or '.join(choices)}?"
    if code == "APPLICATION_NOT_FOUND":
        return f"I couldn't find {name} on this computer."
    if code == "INVALID_URL":
        return "I couldn't open that URL. Please use a valid HTTP or HTTPS address."
    if not result.get("success"):
        if code == "PERMISSION_DENIED":
            return f"I don't have permission to open {name}."
        if code == "PROCESS_NOT_FOUND":
            return f"{name} isn't open."
        return f"I couldn't {result.get('action', 'complete the application action').replace('_', ' ')} for {name}."
    action = result.get("action")
    if action == "launch_application":
        return f"{name} is open."
    if action == "open_url":
        return f"{name} opened the requested page."
    if action == "close_application":
        return f"{name} is closed."
    if action == "focus_application":
        return f"{name} is in front."
    return f"{name} action completed."


def action_start_message(plan: ApplicationPlan) -> str:
    """Describe the next safe action for UI progress feedback."""
    if not plan.steps:
        return "Preparing the application action."
    action = plan.steps[0]
    name = _APPLICATIONS.get(action.application)
    display = name.display_name if name else action.application.replace("_", " ").title()
    if action.action == "launch_application":
        return f"Opening {display}..."
    if action.action == "open_url":
        return f"Opening the requested page in {display}..."
    if action.action == "close_application":
        return f"Closing {display}..."
    if action.action == "focus_application":
        return f"Focusing {display}..."
    return "Checking the requested application action..."
