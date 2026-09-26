"""
Secure File Browser for NIKOLA backend.
Prevents directory traversal attacks. Used by /get command and NL processors.
"""

from pathlib import Path
from typing import Optional

from backend.logger import get_logger
from backend.filesystem_policy import (
    FileOperation,
    FilesystemAccessError,
    authorize_path,
)

logger = get_logger(__name__)


def safe_path(user_path: str, root: str = "C:/") -> Optional[Path]:
    """Validate file path - prevent directory traversal attacks.
    
    Args:
        user_path: User-provided path
        root: Root directory to restrict access
        
    Returns:
        Resolved Path or None if escape attempted
    """
    try:
        target = authorize_path(user_path, FileOperation.READ, explicit_read=True)
        logger.debug("Path validated", path=str(target))
        return target
    except (FilesystemAccessError, OSError) as e:
        logger.warning("Path validation error", user_path=user_path, error=str(e))
        return None


def list_directory(path: str, root: str = "C:/") -> dict:
    """List directory contents securely.
    
    Args:
        path: Directory path
        root: Root directory for access control
        
    Returns:
        Dict with path, items list, count, and optional error
    """
    try:
        target = safe_path(path, root)
        if not target:
            return {
                "path": path,
                "items": [],
                "count": 0,
                "error": "Access denied"
            }
        
        if not target.exists():
            return {
                "path": str(target),
                "items": [],
                "count": 0,
                "error": "Directory not found"
            }
        
        if not target.is_dir():
            return {
                "path": str(target),
                "items": [],
                "count": 0,
                "error": "Not a directory"
            }
        
        # List items
        items = []
        for item in target.iterdir():
            try:
                stat = item.stat()
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else 0,
                    "path": str(item)
                })
            except (OSError, PermissionError):
                pass
        
        logger.info("Directory listed", path=str(target), count=len(items))
        
        return {
            "path": str(target),
            "items": items,
            "count": len(items),
            "error": None
        }
    except Exception as e:
        logger.error("List directory failed", path=path, error=str(e))
        return {
            "path": path,
            "items": [],
            "count": 0,
            "error": str(e)
        }


def read_file(filepath: str, root: str = "C:/", max_lines: int = 100) -> dict:
    """Read file contents securely.
    
    Args:
        filepath: File path
        root: Root directory for access control
        max_lines: Maximum lines to return (ignored, returns up to 10MB)
        
    Returns:
        Dict with path, content, size, and optional error
    """
    try:
        target = safe_path(filepath, root)
        if not target:
            return {
                "path": filepath,
                "content": "",
                "size": 0,
                "error": "Access denied"
            }
        
        if not target.exists():
            return {
                "path": str(target),
                "content": "",
                "size": 0,
                "error": "File not found"
            }
        
        if not target.is_file():
            return {
                "path": str(target),
                "content": "",
                "size": 0,
                "error": "Not a file"
            }
        
        # Check size (max 10MB)
        stat = target.stat()
        if stat.st_size > 10 * 1024 * 1024:
            return {
                "path": str(target),
                "content": "",
                "size": stat.st_size,
                "error": "File too large (max 10MB)"
            }
        
        # Read file
        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try latin-1 fallback
            with open(target, "r", encoding="latin-1") as f:
                content = f.read()
        
        logger.info("File read", path=str(target), size=stat.st_size)
        
        return {
            "path": str(target),
            "content": content,
            "size": stat.st_size,
            "error": None
        }
    except Exception as e:
        logger.error("Read file failed", filepath=filepath, error=str(e))
        return {
            "path": filepath,
            "content": "",
            "size": 0,
            "error": str(e)
        }


def delete_file(filepath: str, root: str = "C:/", confirmed: bool = False) -> dict:
    """Delete file securely.
    
    Args:
        filepath: File path
        root: Root directory for access control
        
    Returns:
        Dict with deleted path, type, and optional error
    """
    try:
        if not confirmed:
            return {"deleted": filepath, "type": None, "error": "Explicit confirmation required"}
        target = authorize_path(filepath, FileOperation.DELETE, explicit_read=True)
        if not target:
            return {
                "deleted": filepath,
                "type": None,
                "error": "Access denied"
            }
        
        if not target.exists():
            return {
                "deleted": str(target),
                "type": None,
                "error": "File not found"
            }
        
        # Delete
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
            file_type = "directory"
        else:
            target.unlink()
            file_type = "file"
        
        logger.info("File deleted", path=str(target), type=file_type)
        
        return {
            "deleted": str(target),
            "type": file_type,
            "error": None
        }
    except Exception as e:
        logger.error("Delete file failed", filepath=filepath, error=str(e))
        return {
            "deleted": filepath,
            "type": None,
            "error": str(e)
        }


def write_file(filepath: str, content: str, root: str = "C:/") -> dict:
    """Write to file securely.
    
    Args:
        filepath: File path
        content: Content to write
        root: Root directory for access control
        
    Returns:
        Dict with path, bytes written, and optional error
    """
    try:
        target = authorize_path(filepath, FileOperation.WRITE, explicit_read=True)
        if not target:
            return {
                "path": filepath,
                "bytes_written": 0,
                "error": "Access denied"
            }
        
        # Ensure parent directory exists
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        with open(target, "w", encoding="utf-8") as f:
            bytes_written = f.write(content)
        
        logger.info("File written", path=str(target), bytes=bytes_written)
        
        return {
            "path": str(target),
            "bytes_written": bytes_written,
            "error": None
        }
    except Exception as e:
        logger.error("Write file failed", filepath=filepath, error=str(e))
        return {
            "path": filepath,
            "bytes_written": 0,
            "error": str(e)
        }
