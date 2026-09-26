"""Local append-only audit records for assistant actions."""

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import PROJECT_ROOT

_AUDIT_PATH = PROJECT_ROOT / "logs" / "activity-audit.jsonl"
_LOCK = Lock()


def record_audit(action: str, **details: Any) -> None:
    entry = {"timestamp": time.time(), "action": action, "details": details}
    with _LOCK:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, default=str) + "\n")
