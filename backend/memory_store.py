"""Small, explicit memory tiers for local-only assistant state."""

import json
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import settings
from backend.logger import get_logger
from backend.audit import record_audit

logger = get_logger(__name__)


class TieredMemory:
    """Store only explicitly selected facts and retrieve relevant snippets."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._session: dict[str, list[str]] = {}
        self._project: list[str] = []
        self._path = Path(settings.resolve_path("~/nikola_memory.json"))
        self._long_term: list[str] = self._load_long_term()

    def _load_long_term(self) -> list[str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [str(item) for item in data.get("long_term", [])][:100]
        except (FileNotFoundError, ValueError, OSError):
            return []

    def _save_long_term(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"long_term": self._long_term}, indent=2), encoding="utf-8")

    def add_session(self, session_id: str, fact: str) -> None:
        with self._lock:
            self._session.setdefault(session_id, []).append(fact[:1000])
            self._session[session_id] = self._session[session_id][-20:]

    def add_project(self, fact: str) -> None:
        with self._lock:
            if fact and fact not in self._project:
                self._project.append(fact[:1000])
                self._project = self._project[-100:]
                record_audit("memory.write", tier="project")

    def add_long_term(self, fact: str, approved: bool) -> bool:
        if not approved:
            return False
        with self._lock:
            if fact and fact not in self._long_term:
                self._long_term.append(fact[:1000])
                self._long_term = self._long_term[-100:]
                self._save_long_term()
                record_audit("memory.write", tier="long_term")
        return True

    def relevant(self, query: str, session_id: str | None = None, limit: int = 8) -> dict[str, list[str]]:
        terms = {part.casefold() for part in query.split() if len(part) > 2}
        with self._lock:
            tiers = {
                "conversation": self._session.get(session_id or "", []),
                "project": self._project,
                "long_term": self._long_term,
            }
        return {
            tier: [fact for fact in facts if not terms or any(term in fact.casefold() for term in terms)][-limit:]
            for tier, facts in tiers.items()
        }

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"conversation": sum(len(items) for items in self._session.values()), "project": len(self._project), "long_term": len(self._long_term)}


memory = TieredMemory()
