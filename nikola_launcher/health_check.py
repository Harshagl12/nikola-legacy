"""
Health check utilities for NIKOLA launcher.
"""

import time
import json
import urllib.request


def wait_for_backend(timeout=45):
    """Poll backend /health until ready or timeout."""
    start = time.time()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/ready",
        headers={"X-API-Key": "nikola-dev-secret-key"}
    )
    
    while time.time() - start < timeout:
        try:
            response = urllib.request.urlopen(req, timeout=2)
            if response.status == 200:
                return True
        except urllib.error.HTTPError as e:
            if e.code == 503:
                try:
                    payload = json.loads(e.read().decode("utf-8"))
                    if payload.get("error_type") in {
                        "cpu_incompatible",
                        "missing_runtime",
                        "missing_model",
                        "model_load_failure",
                        "runtime_crash",
                        "port_startup_failure",
                    }:
                        return False
                except (ValueError, UnicodeDecodeError):
                    pass
        except Exception:
            pass
        
        time.sleep(1)
    
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

    def wait_for_backend(self, timeout=45):
        return wait_for_backend(timeout=timeout)

    def is_backend_alive(self):
        return is_backend_alive()

    def is_llama_server_alive(self):
        return is_llama_server_alive()
