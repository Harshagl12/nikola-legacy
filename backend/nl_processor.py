"""
Natural Language Command Processor for NIKOLA.
Converts English commands to system operations.
All methods are sync (called via executor from async context).
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import psutil
import mss

from backend.application_actions import (
    action_status_message,
    execute_application_plan,
    parse_application_command,
)
from backend.logger import get_logger
from backend.filesystem_policy import FileOperation, authorize_path

logger = get_logger(__name__)


class NLProcessor:
    """Process natural language commands into system operations."""

    def process_command(self, text: str) -> dict:
        """Route text to correct method based on keywords.
        
        Args:
            text: Natural language command
            
        Returns:
            Dict with action, description, success, result, and optional error
        """
        text_lower = text.lower().strip()
        
        try:
            application_plan = parse_application_command(text)
            if application_plan is not None:
                result = execute_application_plan(application_plan)
                return {
                    "action": result.get("action", "application_action"),
                    "description": action_status_message(result),
                    "success": result.get("success", False),
                    "result": result,
                    "error": result.get("error"),
                }

            # screenshot
            if any(x in text_lower for x in ["screenshot", "screen", "capture", "snap"]):
                return self._screenshot()
            
            # list files
            elif any(x in text_lower for x in ["list", "show", "files", "directory"]):
                path = self._extract_path(text) or "."
                return self._list_files(path)
            
            # read file
            elif any(x in text_lower for x in ["read", "open", "show", "content", "display"]):
                path = self._extract_path(text)
                if path:
                    return self._read_file(path)
                return {"action": "read_file", "success": False, "error": "No file path found"}
            
            # delete file
            elif any(x in text_lower for x in ["delete", "remove", "trash"]):
                path = self._extract_path(text)
                if path:
                    return self._delete_file(path)
                return {"action": "delete_file", "success": False, "error": "No file path found"}
            
            # create directory
            elif any(x in text_lower for x in ["create", "mkdir", "new folder"]):
                path = self._extract_path(text)
                if path:
                    return self._create_directory(path)
                return {"action": "create_directory", "success": False, "error": "No path found"}
            
            # copy file
            elif any(x in text_lower for x in ["copy"]):
                src, dst = self._extract_two_paths(text)
                if src and dst:
                    return self._copy_file(src, dst)
                return {"action": "copy_file", "success": False, "error": "Paths not found"}
            
            # move file
            elif any(x in text_lower for x in ["move", "rename"]):
                src, dst = self._extract_two_paths(text)
                if src and dst:
                    return self._move_file(src, dst)
                return {"action": "move_file", "success": False, "error": "Paths not found"}
            
            # search
            elif any(x in text_lower for x in ["search", "find"]):
                import re
                match = re.search(r'search|find\s+(.+?)(?:\s+in\s+(.+)|$)', text_lower)
                query = match.group(1) if match else ""
                root = match.group(2) if match else "."
                if query:
                    return self._search_files(query, root)
                return {"action": "search_files", "success": False, "error": "No query"}
            
            # disk usage
            elif any(x in text_lower for x in ["disk", "storage", "space"]):
                return self._disk_usage()
            
            # system info
            elif any(x in text_lower for x in ["system", "info", "status"]):
                return self._system_info()
            
            # processes
            elif any(x in text_lower for x in ["process", "task", "running"]):
                return self._process_list()
            
            # open directory
            elif any(x in text_lower for x in ["open folder", "open directory"]):
                path = self._extract_path(text)
                if path:
                    return self._open_directory(path)
                return {"action": "open_directory", "success": False, "error": "Path not found"}
            
            else:
                logger.warning("Unknown command", text=text)
                return {
                    "action": "unknown",
                    "description": "Command not recognized",
                    "success": False,
                    "error": "No matching command pattern"
                }
        
        except Exception as e:
            logger.error("Command processing failed", text=text, error=str(e))
            return {
                "action": "error",
                "description": "Command processing failed",
                "success": False,
                "error": str(e)
            }

    def _screenshot(self) -> dict:
        """Take screenshot."""
        try:
            from PIL import Image

            with mss.mss() as sct:
                # Capture primary monitor (index 1 is first actual monitor)
                if len(sct.monitors) > 1:
                    monitor = sct.monitors[1]
                else:
                    monitor = sct.monitors[0]
                
                screenshot = sct.grab(monitor)
                img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            
            img.save(temp_path, "PNG")
            
            file_size = os.path.getsize(temp_path)
            
            return {
                "action": "screenshot",
                "description": "Screenshot captured",
                "success": True,
                "result": {
                    "file": temp_path,
                    "size": file_size,
                    "timestamp": None
                }
            }
        except Exception as e:
            logger.error("Screenshot failed", error=str(e))
            return {
                "action": "screenshot",
                "description": "Screenshot failed",
                "success": False,
                "error": str(e)
            }

    def _list_files(self, path: str) -> dict:
        """List files in directory."""
        try:
            p = authorize_path(path, FileOperation.READ, explicit_read=True, allow_missing=False)
            if not p.exists():
                return {
                    "action": "list_files",
                    "description": f"Directory not found: {path}",
                    "success": False,
                    "error": "Directory does not exist"
                }
            
            items = []
            for item in p.iterdir():
                try:
                    stat = item.stat()
                    items.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else 0,
                        "path": str(item)
                    })
                except:
                    pass
            
            return {
                "action": "list_files",
                "description": f"Listed {len(items)} items in {path}",
                "success": True,
                "result": {
                    "path": str(p),
                    "items": items,
                    "count": len(items)
                }
            }
        except Exception as e:
            logger.error("List files failed", path=path, error=str(e))
            return {
                "action": "list_files",
                "description": "List failed",
                "success": False,
                "error": str(e)
            }

    def _read_file(self, path: str) -> dict:
        """Read text file (max 10MB)."""
        try:
            p = authorize_path(path, FileOperation.READ, explicit_read=True, allow_missing=False)
            if not p.exists():
                return {
                    "action": "read_file",
                    "description": "File not found",
                    "success": False,
                    "error": "File does not exist"
                }
            
            size = p.stat().st_size
            if size > 10 * 1024 * 1024:
                return {
                    "action": "read_file",
                    "description": "File too large",
                    "success": False,
                    "error": "File larger than 10MB"
                }
            
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            return {
                "action": "read_file",
                "description": f"Read {size} bytes",
                "success": True,
                "result": {
                    "path": str(p),
                    "content": content,
                    "size": size
                }
            }
        except Exception as e:
            logger.error("Read file failed", path=path, error=str(e))
            return {
                "action": "read_file",
                "description": "Read failed",
                "success": False,
                "error": str(e)
            }

    def _delete_file(self, path: str) -> dict:
        """Delete file or directory."""
        return {
            "action": "delete_file",
            "description": "Explicit confirmation required",
            "success": False,
            "error": "Explicit confirmation required",
        }
        # Kept below for the future confirmed command path.
        try:
            p = authorize_path(path, FileOperation.DELETE, explicit_read=True, allow_missing=False)
            if not p.exists():
                return {
                    "action": "delete_file",
                    "description": "Path not found",
                    "success": False,
                    "error": "Path does not exist"
                }
            
            if p.is_dir():
                shutil.rmtree(p)
                return {
                    "action": "delete_file",
                    "description": f"Deleted directory",
                    "success": True,
                    "result": {"deleted": str(p), "type": "directory"}
                }
            else:
                p.unlink()
                return {
                    "action": "delete_file",
                    "description": f"Deleted file",
                    "success": True,
                    "result": {"deleted": str(p), "type": "file"}
                }
        except Exception as e:
            logger.error("Delete failed", path=path, error=str(e))
            return {
                "action": "delete_file",
                "description": "Delete failed",
                "success": False,
                "error": str(e)
            }

    def _create_directory(self, path: str) -> dict:
        """Create directory."""
        try:
            p = authorize_path(path, FileOperation.WRITE, explicit_read=True)
            p.mkdir(parents=True, exist_ok=True)
            
            return {
                "action": "create_directory",
                "description": f"Created directory",
                "success": True,
                "result": {"created": str(p)}
            }
        except Exception as e:
            logger.error("Create directory failed", path=path, error=str(e))
            return {
                "action": "create_directory",
                "description": "Create failed",
                "success": False,
                "error": str(e)
            }

    def _copy_file(self, src: str, dst: str) -> dict:
        """Copy file or directory."""
        try:
            src_p = authorize_path(src, FileOperation.READ, explicit_read=True, allow_missing=False)
            dst_p = authorize_path(dst, FileOperation.WRITE, explicit_read=True)
            
            if src_p.is_dir():
                shutil.copytree(src_p, dst_p)
            else:
                shutil.copy2(src_p, dst_p)
            
            return {
                "action": "copy_file",
                "description": "Copied",
                "success": True,
                "result": {"source": str(src_p), "destination": str(dst_p)}
            }
        except Exception as e:
            logger.error("Copy failed", src=src, dst=dst, error=str(e))
            return {
                "action": "copy_file",
                "description": "Copy failed",
                "success": False,
                "error": str(e)
            }

    def _move_file(self, src: str, dst: str) -> dict:
        """Move or rename file."""
        return {
            "action": "move_file",
            "description": "Explicit confirmation required",
            "success": False,
            "error": "Explicit confirmation required",
        }
        # Kept below for the future confirmed command path.
        try:
            src_p = authorize_path(src, FileOperation.READ, explicit_read=True, allow_missing=False)
            dst_p = authorize_path(dst, FileOperation.WRITE, explicit_read=True)
            
            shutil.move(str(src_p), str(dst_p))
            
            return {
                "action": "move_file",
                "description": "Moved",
                "success": True,
                "result": {"source": str(src_p), "destination": str(dst_p)}
            }
        except Exception as e:
            logger.error("Move failed", src=src, dst=dst, error=str(e))
            return {
                "action": "move_file",
                "description": "Move failed",
                "success": False,
                "error": str(e)
            }

    def _search_files(self, query: str, root: str = ".") -> dict:
        """Search files (max 5 levels, max 10k files, max 50 results)."""
        try:
            root_p = authorize_path(root, FileOperation.READ, explicit_read=True, allow_missing=False)
            results = []
            count = 0
            
            for item in root_p.rglob("*"):
                try:
                    item = authorize_path(item, FileOperation.READ, explicit_read=True)
                except (PermissionError, OSError):
                    continue
                if count >= 10000:
                    break
                
                # Check depth
                try:
                    rel = item.relative_to(root_p)
                    if len(rel.parts) > 5:
                        continue
                except:
                    continue
                
                # Check match
                match_type = None
                if query.lower() in item.name.lower():
                    match_type = "name"
                elif item.is_file():
                    try:
                        with open(item, "r", encoding="utf-8", errors="ignore") as f:
                            if query.lower() in f.read().lower():
                                match_type = "content"
                    except:
                        pass
                
                if match_type:
                    results.append({
                        "path": str(item),
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "match_type": match_type
                    })
                    if len(results) >= 50:
                        break
                
                count += 1
            
            return {
                "action": "search_files",
                "description": f"Found {len(results)} results",
                "success": True,
                "result": {
                    "query": query,
                    "root": str(root_p),
                    "results": results,
                    "count": len(results)
                }
            }
        except Exception as e:
            logger.error("Search failed", query=query, error=str(e))
            return {
                "action": "search_files",
                "description": "Search failed",
                "success": False,
                "error": str(e)
            }

    def _disk_usage(self) -> dict:
        """Get disk usage."""
        try:
            total, used, free = shutil.disk_usage("/")
            
            return {
                "action": "disk_usage",
                "description": "Disk usage",
                "success": True,
                "result": {
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "percent_used": round(100 * used / total, 1)
                }
            }
        except Exception as e:
            logger.error("Disk usage failed", error=str(e))
            return {
                "action": "disk_usage",
                "description": "Failed",
                "success": False,
                "error": str(e)
            }

    def _system_info(self) -> dict:
        """Get system information."""
        try:
            import platform
            
            cpu_percent = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            
            return {
                "action": "system_info",
                "description": "System info",
                "success": True,
                "result": {
                    "system": platform.system(),
                    "release": platform.release(),
                    "cpu_percent": cpu_percent,
                    "ram_used_gb": round(ram.used / (1024**3), 2),
                    "ram_total_gb": round(ram.total / (1024**3), 2)
                }
            }
        except Exception as e:
            logger.error("System info failed", error=str(e))
            return {
                "action": "system_info",
                "description": "Failed",
                "success": False,
                "error": str(e)
            }

    def _process_list(self) -> dict:
        """Get top 20 processes by memory."""
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    mem_mb = proc.info["memory_info"].rss / (1024**2)
                    processes.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "memory_mb": round(mem_mb, 1)
                    })
                except:
                    pass
            
            # Sort by memory descending
            processes.sort(key=lambda x: x["memory_mb"], reverse=True)
            processes = processes[:20]
            
            return {
                "action": "process_list",
                "description": f"Top 20 processes",
                "success": True,
                "result": {
                    "count": len(processes),
                    "processes": processes
                }
            }
        except Exception as e:
            logger.error("Process list failed", error=str(e))
            return {
                "action": "process_list",
                "description": "Failed",
                "success": False,
                "error": str(e)
            }

    def _open_directory(self, path: str) -> dict:
        """Open directory in explorer."""
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return {
                    "action": "open_directory",
                    "description": "Path not found",
                    "success": False,
                    "error": "Path does not exist"
                }
            
            os.startfile(str(p))
            
            return {
                "action": "open_directory",
                "description": "Opened",
                "success": True,
                "result": {"path": str(p)}
            }
        except Exception as e:
            logger.error("Open directory failed", path=path, error=str(e))
            return {
                "action": "open_directory",
                "description": "Failed",
                "success": False,
                "error": str(e)
            }

    def _extract_path(self, text: str) -> Optional[str]:
        """Extract file path from natural language."""
        import re
        
        # Check for quoted paths
        match = re.search(r'["\'](.+?)["\']', text)
        if match:
            return match.group(1)
        
        # Check for keywords
        keywords = {
            "desktop": "~/Desktop",
            "downloads": "~/Downloads",
            "vault": "~/vault",
            "documents": "~/Documents",
        }
        
        for keyword, path in keywords.items():
            if keyword in text.lower():
                return path
        
        # Try to extract C:\ or /path
        match = re.search(r'([A-Z]:\\[^ "\n]+|/[^ "\n]+)', text)
        if match:
            return match.group(1)
        
        return None

    def _extract_two_paths(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract source and destination paths from copy/move commands."""
        import re
        
        # Look for "from ... to ..." pattern
        match = re.search(r'(?:from|copy|move)\s+(.+?)\s+(?:to|into)\s+(.+?)(?:\s+|$)', text)
        if match:
            return match.group(1), match.group(2)
        
        return None, None
