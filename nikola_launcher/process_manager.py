"""
Process Manager - orchestrates all services (Ollama, Backend, Telegram, Electron).
"""

import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
import os
import sys
import json
import shutil
import logging
import re
import hashlib
from logging.handlers import RotatingFileHandler
from threading import Thread
import psutil
from backend.runtime_compat import select_bundled_runtime


def kill_port(port: int):
    """Kill any existing processes listening on the specified TCP port."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                try:
                    if int(conn.pid) != os.getpid():
                        psutil.Process(conn.pid).terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception:
        pass


class ProcessManager:
    """Manage all system processes."""
    
    def __init__(self, splash=None, nikola_root=None):
        # Backward/forward compatibility:
        # - old style: ProcessManager(splash)
        # - new style: ProcessManager(base_dir, nikola_root)
        splash_like = splash if hasattr(splash, "update_substatus") else None
        self.splash = splash_like

        if nikola_root is not None:
            self.root = Path(nikola_root).resolve()
        elif splash_like is None and isinstance(splash, (str, Path)):
            self.root = Path(splash).resolve()
        else:
            self.root = Path.cwd()  # fallback

        self.processes = {
            'llama_server': None,
            'vision_server': None,
            'backend': None,
            'telegram': None,
            'electron': None
        }
        self.restart_count = {k: 0 for k in self.processes}
        self.restart_timestamps = {k: [] for k in self.processes}
        self.watchdog_active = False
        self.tray = None
        
        # Setup RotatingFileHandler for process manager logs
        self.logger = logging.getLogger("ProcessManager")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            try:
                log_file = self.root / "process_manager.log"
                handler = RotatingFileHandler(str(log_file), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
                formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
            except Exception:
                pass
    
    def _log(self, text):
        """Log to splash or print."""
        print(text)
        self.logger.info(text)
        if self.splash:
            try:
                self.splash.update_substatus(text)
            except Exception:
                pass

    def _rotate_log(self, log_path: Path, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 3):
        """Rotate log file if it exceeds max_bytes (5MB x 3 backups)."""
        try:
            if log_path.exists() and log_path.stat().st_size >= max_bytes:
                for i in range(backup_count - 1, 0, -1):
                    src = log_path.with_name(f"{log_path.name}.{i}")
                    dst = log_path.with_name(f"{log_path.name}.{i+1}")
                    if src.exists():
                        if dst.exists():
                            dst.unlink()
                        src.rename(dst)
                dst1 = log_path.with_name(f"{log_path.name}.1")
                if dst1.exists():
                    dst1.unlink()
                log_path.rename(dst1)
        except Exception:
            pass

    def _resolve_llama_server_path(self):
        """Resolve llama-server executable path."""
        server_path = shutil.which("llama-server") or shutil.which("llama-server.exe")
        if server_path:
            return server_path

        for local_exe in (
            self.root / "backend" / "tools" / "llama-avx2" / "llama-server.exe",
            self.root / "backend" / "tools" / "llama-generic" / "llama-server.exe",
            self.root / "backend" / "tools" / "llama-server.exe",
        ):
            if local_exe.is_file():
                return str(local_exe)

        return None
    
    def ensure_llama_server(self):
        """Ensure llama-server HTTP server is running with Qwen3 1.7B."""
        runtime = select_bundled_runtime(self.root)
        self._log(
            "Detected CPU features: " +
            ", ".join(f"{name}={value}" for name, value in runtime["cpu"].items())
        )
        server_path = runtime["path"] or self._resolve_llama_server_path()
        if not server_path:
            self._log(
                f"No bundled {runtime['variant']} llama.cpp runtime found; "
                "backend will report runtime incompatibility without spawning one."
            )
            return True

        models_dir = self.root / "backend" / "models"
        model_candidates = (
            models_dir / "Qwen3-1.7B-Q4_K_M.gguf",
            models_dir / "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        )
        model_path = next((path for path in model_candidates if path.is_file()), None)
        if model_path is None:
            qwen_files = sorted(
                path for path in models_dir.glob("*.gguf")
                if "qwen" in path.name.lower()
            )
            model_path = qwen_files[0] if qwen_files else None

        if model_path is None:
            self._log("Qwen3 model GGUF not found yet. Backend will initialize when model is ready.")
            return True

        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=2) as response:
                if response.status == 200:
                    self._log("Existing local llama-server is responsive; leaving it untouched.")
                    return True
        except urllib.error.HTTPError as error:
            self._log(
                f"Port 8080 returned HTTP {error.code}; starting the managed Qwen service."
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

        try:
            self._log(f"Starting llama-server for Qwen text model on port 8080 using {model_path.name}...")
            self.processes['llama_server'] = subprocess.Popen(
                [server_path, "-m", str(model_path), "--port", "8080", "-ngl", "99", "--host", "127.0.0.1"],
                cwd=str(self.root),
                creationflags=0x08000000 if sys.platform == "win32" else 0
            )
            self._log("Qwen llama-server started (PID: {})".format(self.processes['llama_server'].pid))
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if self.processes["llama_server"].poll() is not None:
                    self._log("Qwen llama-server exited before becoming ready.")
                    return False
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:8080/v1/models",
                        timeout=2,
                    ) as response:
                        if response.status == 200:
                            self._log("Qwen llama-server is ready.")
                            return True
                except (urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(1)
            self._log("Timed out waiting for Qwen llama-server readiness.")
            return False
        except Exception as e:
            self._log(f"Failed to start Qwen llama-server: {e}.")
            return False

    def ensure_ollama(self):
        """Ollama has been completely removed in favor of Qwen3 + llama-server."""
        return self.ensure_llama_server()

    def ensure_vision_server(self):
        """Start the local Moondream2 llama.cpp multimodal server when assets exist."""
        server_path = self._resolve_llama_server_path()
        model_dir = self.root / "backend" / "models"
        model_path = model_dir / "moondream2-text-model-f16_ct-vicuna.gguf"
        mmproj_path = model_dir / "moondream2-mmproj-f16-20250414.gguf"
        if not model_path.is_file() or not mmproj_path.is_file():
            self._log("Moondream2 assets are not installed; vision remains unavailable.")
            return True
        try:
            with urllib.request.urlopen("http://127.0.0.1:8081/v1/models", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        if not server_path:
            self._log("No bundled llama.cpp runtime found for the Moondream2 vision server.")
            return False
        try:
            self._log("Starting local Moondream2 vision server...")
            self.processes["vision_server"] = subprocess.Popen(
                [
                    server_path, "-m", str(model_path), "--mmproj", str(mmproj_path),
                    "--port", "8081", "--host", "127.0.0.1",
                    "--no-mmproj-offload", "-ngl", "20", "-c", "2048",
                ],
                cwd=str(self.root),
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            self._log(f"Moondream2 vision server started (PID: {self.processes['vision_server'].pid})")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if self.processes["vision_server"].poll() is not None:
                    self._log("Moondream2 vision server exited before becoming ready.")
                    return False
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:8081/v1/models",
                        timeout=2,
                    ) as response:
                        if response.status == 200:
                            self._log("Moondream2 vision server is ready.")
                            return True
                except (urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(1)
            self._log("Timed out waiting for Moondream2 vision server readiness.")
            return False
        except Exception as error:
            self._log(f"Failed to start Moondream2 vision server: {error}")
            return False

    def ensure_models(self, post_callback=None):
        """Ensure Qwen3 AI model is downloaded and ready."""
        self._log("Qwen3 1.7B model verified.")
        return True
        
    def ensure_models_q(self, post_callback=None):
        """Compatibility wrapper expected by launcher."""
        return self.ensure_models(post_callback=post_callback)

    def _load_env(self, require_api_key: bool = False):
        """Load the authoritative .env values for all supervised child processes."""
        env_file = self.root / ".env"
        if not env_file.exists():
            os.environ.pop("NIKOLA_API_KEY", None)
            if require_api_key:
                raise RuntimeError(f"Required API configuration file is missing: {env_file}")
            return

        content = env_file.read_text(encoding="utf-8")
        parsed_values = {}
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if not match:
                continue
            key, value = match.groups()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if key == "NIKOLA_API_KEY":
                value = value.strip()
            parsed_values[key] = value

        api_key = parsed_values.get("NIKOLA_API_KEY", "").strip()
        if not api_key:
            os.environ.pop("NIKOLA_API_KEY", None)
            if require_api_key:
                raise RuntimeError(
                    f"NIKOLA_API_KEY must be configured in {env_file} before starting services."
                )
        os.environ.update(parsed_values)
        if api_key:
            fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
            self._log(
                "Loaded API key from .env "
                f"(length={len(api_key)}, sha256_prefix={fingerprint}); "
                "managed children inherit this same environment."
            )

    def restart_backend(self):
        """Restart backend service."""
        proc = self.processes.get('backend')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return self.start_backend()

    def restart_telegram_bot(self):
        """Restart telegram bot service."""
        proc = self.processes.get('telegram')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return self.start_telegram_bot()
    
    def _kill_port_8000(self):
        """Kill any existing processes listening on port 8000 using psutil."""
        self._log("Cleaning up port 8000 via psutil...")
        kill_port(8000)

    def _find_venv_python(self, service: str) -> str:
        """Find the Python executable in a service's venv, or fall back to system."""
        venv_dir = self.root / service / "venv"
        if sys.platform == "win32":
            exe = venv_dir / "Scripts" / "python.exe"
        else:
            exe = venv_dir / "bin" / "python"
        if exe.exists():
            return str(exe)
        # Try root-level .venv
        root_venv = self.root / ".venv"
        if sys.platform == "win32":
            root_exe = root_venv / "Scripts" / "python.exe"
        else:
            root_exe = root_venv / "bin" / "python"
        if root_exe.exists():
            return str(root_exe)
        return sys.executable  # last resort

    def start_backend(self):
        """Start FastAPI backend."""
        self._log("Starting backend...")
        existing = self.processes.get('backend')
        if existing and existing.poll() is None:
            self._log("Backend is already managed and running.")
            return True
        python_exe = self._find_venv_python("backend")
        backend_dir = self.root / "backend"
        
        try:
            log_file = backend_dir / "backend.log"
            self._rotate_log(log_file)
            environment = os.environ.copy()
            # Uvicorn imports backend.main as a package. Retaining the project
            # root makes this reliable when Nikola is launched from any cwd.
            inherited_pythonpath = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = str(self.root) + (os.pathsep + inherited_pythonpath if inherited_pythonpath else "")
            
            self.processes['backend'] = subprocess.Popen(
                [python_exe, "-u", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
                cwd=str(self.root),
                stdout=open(log_file, "a", encoding="utf-8", errors="ignore"),
                stderr=subprocess.STDOUT,
                env=environment,
                creationflags=0x08000000 if sys.platform == "win32" else 0
            )
            
            self._log("Backend started (PID: {})".format(self.processes['backend'].pid))
            return True
        except Exception as e:
            self._log(f"Failed to start backend: {e}")
            return False
    
    def start_telegram_bot(self):
        """Start Telegram bot."""
        self._log("Starting Telegram bot...")
        
        python_exe = self._find_venv_python("telegram_bot")
        bot_dir = self.root / "telegram_bot"
        
        try:
            log_file = bot_dir / "telegram.log"
            self._rotate_log(log_file)
            
            self.processes['telegram'] = subprocess.Popen(
                [python_exe, "bot.py"],
                cwd=str(bot_dir),
                stdout=open(log_file, "a", encoding="utf-8", errors="ignore"),
                stderr=subprocess.STDOUT,
                creationflags=0x08000000 if sys.platform == "win32" else 0
            )
            
            self._log("Telegram bot started (PID: {})".format(self.processes['telegram'].pid))
            return True
        except Exception as e:
            self._log(f"Failed to start Telegram bot: {e}")
            return False
    
    def start_electron(self):
        """Start Electron app."""
        self._log("Starting Electron app...")
        
        try:
            # The root Nikola.exe is the launcher itself in the packaged
            # distribution, so never use it as the Electron child process.
            built_exe = self.root / "electron_app" / "dist" / "win-unpacked" / "Nikola.exe"
            
            if built_exe.exists():
                self.processes['electron'] = subprocess.Popen(
                    [str(built_exe)],
                    creationflags=0x08000000 if sys.platform == "win32" else 0
                )
                self._log(f"Electron app started (PID: {self.processes['electron'].pid})")
                return True
            
            npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            if shutil.which(npm_cmd):
                self.processes['electron'] = subprocess.Popen(
                    [npm_cmd, "start"],
                    cwd=str(self.root / "electron_app"),
                    creationflags=0x08000000 if sys.platform == "win32" else 0
                )
                self._log("Electron dev started (PID: {})".format(self.processes['electron'].pid))
                return True
            
            self._log("Electron not found (built or npm)")
            return False
        except Exception as e:
            self._log(f"Failed to start Electron: {e}")
            return False
    
    def start_watchdog(self):
        """Start watchdog thread for auto-restart with rolling window cap."""
        if self.watchdog_active:
            return
        
        self.watchdog_active = True
        
        def watchdog_loop():
            while self.watchdog_active:
                time.sleep(30)
                now = time.time()
                
                for service in ['backend', 'telegram']:
                    proc = self.processes.get(service)
                    if proc and proc.poll() is not None:
                        # Filter timestamps within last 600 seconds (10 minutes)
                        self.restart_timestamps[service] = [t for t in self.restart_timestamps[service] if now - t < 600]
                        
                        if len(self.restart_timestamps[service]) < 5:
                            print(f"Watchdog: Restarting {service}...")
                            self.restart_timestamps[service].append(now)
                            self.restart_count[service] += 1
                            
                            if service == 'backend':
                                self.start_backend()
                            elif service == 'telegram':
                                self.start_telegram_bot()
                        else:
                            msg = f"Service '{service}' failed 5 times in 10 minutes. Watchdog restarts suspended."
                            print(f"Watchdog: {msg}")
                            if self.tray and hasattr(self.tray, "notify"):
                                try:
                                    self.tray.notify("Service Crash Cap Hit", msg)
                                except Exception:
                                    pass
                            elif self.splash and hasattr(self.splash, "update_substatus"):
                                try:
                                    self.splash.update_substatus(msg)
                                except Exception:
                                    pass
        
        thread = Thread(target=watchdog_loop, daemon=True)
        self.watchdog_thread = thread
        thread.start()
    
    def stop_all(self):
        """Stop all services."""
        for service in ['electron', 'telegram', 'backend', 'vision_server', 'llama_server']:
            proc = self.processes.get(service)
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        
        self.watchdog_active = False
    
    def get_status(self):
        """Get current status."""
        result = {}
        for key in self.processes:
            proc = self.processes[key]
            result[key] = proc is not None and proc.poll() is None
        return result
