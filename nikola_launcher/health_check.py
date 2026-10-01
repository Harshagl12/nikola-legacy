"""
Health check utilities for NIKOLA launcher.
"""

import time
import json
import urllib.request
import urllib.error
import psutil


def _managed_process_ids(process):
    """Include the Windows venv launcher process and its real Python child."""
    try:
        parent = psutil.Process(process.pid)
        return {parent.pid, *(child.pid for child in parent.children(recursive=True))}
    except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
        return set()


def wait_for_backend(timeout=45, process=None):
    """Wait for the managed backend process to answer its unauthenticated liveness check."""
    start = time.time()
    req = urllib.request.Request("http://127.0.0.1:8000/health")
    
    while time.time() - start < timeout:
        managed_pids = _managed_process_ids(process) if process is not None else None
        if process is not None and not managed_pids:
            return False
        try:
            with urllib.request.urlopen(req, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and (
                    process is None or payload.get("pid") in managed_pids
                ):
                    return True
        except urllib.error.HTTPError:
            pass
        except Exception:
            pass
        
        time.sleep(0.25)
    
    return False


def is_backend_alive():
    """Single check if backend is responding.
    
    Returns:
        True if backend is alive
    """
    try:
        response = urllib.request.urlopen(
            "http://localhost:8000/health",
            timeout=2
        )
        return response.status == 200
    except:
        return False


def is_llama_server_alive():
    """Single check if llama-server is responding.
    
    Returns:
        True if llama-server is alive
    """
    try:
        response = urllib.request.urlopen(
            "http://localhost:8080/v1/models",
            timeout=2
        )
        return response.status == 200
    except:
        return False


class HealthChecker:
    """Compatibility wrapper expected by launcher."""

    def wait_for_backend(self, timeout=45, process=None):
        return wait_for_backend(timeout=timeout, process=process)

    def is_backend_alive(self):
        return is_backend_alive()

    def is_llama_server_alive(self):
        return is_llama_server_alive()
