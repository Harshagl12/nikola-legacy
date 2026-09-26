"""Validated local tools exposed to the assistant.

The model may select a tool name and structured arguments, but it never supplies
shell commands or executable code. Each tool validates its own arguments.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import PROJECT_ROOT, settings
from backend.filesystem_policy import FileOperation, allowed_read_roots, authorize_path
from backend.logger import get_logger
from backend.audit import record_audit

logger = get_logger(__name__)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["file_search", "file_read", "directory_list", "file_metadata"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class FileSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    extension: str | None = Field(default=None, pattern=r"^\.[A-Za-z0-9]{1,10}$")
    root: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FileReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    max_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class DirectoryListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    limit: int = Field(default=100, ge=1, le=500)


class FileMetadataArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)


ARGUMENT_MODELS = {
    "file_search": FileSearchArguments,
    "file_read": FileReadArguments,
    "directory_list": DirectoryListArguments,
    "file_metadata": FileMetadataArguments,
}


def _allowed_roots() -> list[Path]:
    return [root.resolve() for root in allowed_read_roots()]


def _safe_path(raw_path: str) -> Path:
    return authorize_path(raw_path, FileOperation.READ, explicit_read=True)


def _file_search(arguments: FileSearchArguments) -> dict[str, Any]:
    root = _safe_path(arguments.root or str(PROJECT_ROOT))
    if not root.is_dir():
        raise ValueError("Search root is not a directory")
    matches: list[dict[str, Any]] = []
    query = arguments.query.casefold()
    for candidate in root.rglob("*"):
        candidate = authorize_path(candidate, FileOperation.READ, explicit_read=True)
        if len(matches) >= arguments.limit:
            break
        if not candidate.is_file() or query not in candidate.name.casefold():
            continue
        if arguments.extension and candidate.suffix.lower() != arguments.extension.lower():
            continue
        matches.append({"path": str(candidate), "name": candidate.name})
    return {"query": arguments.query, "matches": matches, "count": len(matches)}


def _file_read(arguments: FileReadArguments) -> dict[str, Any]:
    target = _safe_path(arguments.path)
    if not target.is_file():
        raise ValueError("File not found")
    if target.stat().st_size > arguments.max_bytes:
        raise ValueError("File exceeds the requested read limit")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": str(target), "content": content, "size": target.stat().st_size}


def _directory_list(arguments: DirectoryListArguments) -> dict[str, Any]:
    target = _safe_path(arguments.path)
    if not target.is_dir():
        raise ValueError("Directory not found")
    items = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.casefold())[:arguments.limit]:
        try:
            child = authorize_path(child, FileOperation.READ, explicit_read=True)
        except (PermissionError, OSError):
            continue
        items.append({"name": child.name, "type": "directory" if child.is_dir() else "file", "path": str(child)})
    return {"path": str(target), "items": items, "count": len(items)}


def _file_metadata(arguments: FileMetadataArguments) -> dict[str, Any]:
    target = _safe_path(arguments.path)
    if not target.exists():
        raise ValueError("Path not found")
    stat = target.stat()
    return {"path": str(target), "type": "directory" if target.is_dir() else "file", "size": stat.st_size, "modified": stat.st_mtime}


def execute_tool(request: ToolRequest) -> dict[str, Any]:
    """Validate and execute one allowlisted local read tool."""
    try:
        arguments = ARGUMENT_MODELS[request.tool].model_validate(request.arguments)
        result = {
            "file_search": _file_search,
            "file_read": _file_read,
            "directory_list": _directory_list,
            "file_metadata": _file_metadata,
        }[request.tool](arguments)
        logger.info("Tool executed", tool=request.tool)
        record_audit("tool.execute", tool=request.tool, success=True)
        return {"tool": request.tool, "success": True, "result": result}
    except (ValidationError, ValueError, OSError) as error:
        logger.warning("Tool rejected", tool=request.tool, error=str(error))
        record_audit("tool.reject", tool=request.tool, error=str(error))
        return {"tool": request.tool, "success": False, "error": str(error)}
