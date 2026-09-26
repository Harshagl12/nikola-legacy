"""Centralized filesystem authorization for Nikola."""

import os
from enum import Enum
from pathlib import Path


ONE_DRIVE_MESSAGE = "OneDrive access is disabled by Nikola's privacy policy."


class FileOperation(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class FilesystemAccessError(PermissionError):
    """Raised when a canonical path is outside Nikola's filesystem policy."""


def _canonical(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _home() -> Path:
    return Path.home().resolve()


def _blocked_roots() -> tuple[Path, ...]:
    return (
        (_home() / "OneDrive").resolve(strict=False),
        Path(os.environ.get("OneDrive", str(_home() / "OneDrive"))).resolve(strict=False),
    )


def _sensitive_roots() -> tuple[Path, ...]:
    home = _home()
    return (
        Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve(strict=False),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(strict=False),
        Path(os.environ.get("ProgramW6432", r"C:\Program Files")).resolve(strict=False),
        home / "AppData",
        home / ".ssh",
    )


def allowed_read_roots() -> tuple[Path, ...]:
    home = _home()
    project = Path(__file__).resolve().parents[1]
    return (
        project,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Videos",
    )


def _is_blocked(path: Path) -> bool:
    return any(_is_within(path, root) for root in _blocked_roots())


def _is_sensitive(path: Path) -> bool:
    return any(_is_within(path, root) for root in _sensitive_roots())


def authorize_path(
    raw_path: str | os.PathLike[str],
    operation: FileOperation,
    *,
    explicit_read: bool = False,
    allow_missing: bool = True,
    internal_storage: bool = False,
) -> Path:
    """Canonicalize and authorize a path for a filesystem operation."""
    if not str(raw_path).strip():
        raise FilesystemAccessError("A filesystem path is required")

    target = _canonical(raw_path)
    if _is_blocked(target):
        raise FilesystemAccessError(ONE_DRIVE_MESSAGE)
    if _is_sensitive(target):
        raise FilesystemAccessError("Access to system or security-sensitive locations is disabled.")

    roots = tuple(root.resolve(strict=False) for root in allowed_read_roots())
    in_allowed_root = any(_is_within(target, root) for root in roots)
    if operation == FileOperation.READ:
        if not in_allowed_root and not explicit_read:
            raise FilesystemAccessError(
                "Path is outside Nikola's allowed local roots; explicit local read required."
            )
    elif operation in (FileOperation.WRITE, FileOperation.DELETE):
        writable_roots = roots[:4]
        if not internal_storage and not any(_is_within(target, root) for root in writable_roots):
            raise FilesystemAccessError(
                "Write and delete operations are restricted to Nikola, Desktop, Documents, and Downloads."
            )

    if not allow_missing and not target.exists():
        raise FileNotFoundError(str(target))
    return target


def local_vault_path(configured: str | os.PathLike[str]) -> Path:
    """Return a safe local vault path, rejecting OneDrive configuration."""
    target = authorize_path(configured, FileOperation.WRITE, internal_storage=True)
    target.mkdir(parents=True, exist_ok=True)
    return target
