"""
Dependency Installer - handles venv, pip, npm setup.
"""

import subprocess
import sys
import shutil
from pathlib import Path
import time


class DepInstaller:
    """Install project dependencies."""
    
    def __init__(self, splash=None):
        # Backward/forward compatibility:
        # - old style: DepInstaller(splash)
        # - new style: DepInstaller(nikola_root)
        if hasattr(splash, "update_substatus"):
            self.splash = splash
            self.root = Path.cwd()
        elif isinstance(splash, (str, Path)):
            self.splash = None
            self.root = Path(splash).resolve()
        else:
            self.splash = None
            self.root = Path.cwd()
    
    def _log(self, text):
        """Log to splash and stdout."""
        try:
            if sys.stdout is not None:
                print(text, flush=True)
        except Exception:
            pass
        if self.splash:
            try:
                self.splash.update_substatus(text)
            except Exception:
                pass
    
    def is_ollama_installed(self):
        """Ollama is no longer required. Qwen3 engine is managed internally."""
        return True

    
    def ensure_backend_venv(self, post_callback=None):
        """Create/verify backend venv and install requirements."""
        backend_dir = self.root / "backend"
        venv_dir = backend_dir / "venv"
        
        if sys.platform == "win32":
            python_exe = venv_dir / "Scripts" / "python.exe"
        else:
            python_exe = venv_dir / "bin" / "python"
        
        if not python_exe.exists():
            self._log("Creating backend venv...")
            
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    capture_output=True,
                    timeout=60,
                    text=True
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr if result.stderr else result.stdout
                    self._log(f"Venv creation failed: {error_msg[:200]}")
                    return False
                
                # Wait for venv to be ready
                time.sleep(1)
                
                if not python_exe.exists():
                    self._log(f"Venv created but python.exe not found at {python_exe}")
                    return False
                    
            except subprocess.TimeoutExpired:
                self._log("Venv creation timed out")
                return False
            except Exception as e:
                self._log(f"Failed to create venv: {str(e)[:200]}")
                return False
        
        deps_flag = venv_dir / ".deps_installed"
        if python_exe.exists() and deps_flag.exists():
            self._log("Backend requirements already verified")
            return True
            
        self._log("Installing backend requirements...")
        
        for attempt in range(3):
            try:
                self._log(f"Upgrading pip (attempt {attempt+1}/3)...")
                result = subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "--upgrade", "pip"],
                    capture_output=True,
                    timeout=120,
                    text=True
                )
                
                if result.returncode != 0:
                    self._log(f"pip upgrade failed: {result.stderr[-100:] if result.stderr else result.stdout[-100:]}")
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    return False
                
                self._log(f"Installing requirements (attempt {attempt+1}/3)...")
                result = subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "--prefer-binary", "-r", "requirements.txt"],
                    cwd=str(backend_dir),
                    capture_output=True,
                    timeout=300,
                    text=True
                )
                
                if result.returncode != 0:
                    self._log(f"pip failed: {result.stderr[-500:] if result.stderr else result.stdout[-500:]}")
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    return False
                
                try:
                    deps_flag.touch()
                except Exception:
                    pass
                self._log("Backend requirements installed")
                return True
            except subprocess.TimeoutExpired:
                self._log(f"Timeout on attempt {attempt+1}/3, retrying...")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else ""
                stdout = e.stdout.decode() if e.stdout else ""
                error_msg = (stderr if stderr else stdout)[-500:]
                self._log(f"Attempt {attempt+1} failed: {error_msg}")
                
                if attempt < 2:
                    time.sleep(2)
                    continue
                
                return False
            except Exception as e:
                self._log(f"Error: {str(e)[:200]}")
                return False
        
        return False
    
    def ensure_telegram_venv(self, post_callback=None):
        """Create/verify telegram venv and install requirements."""
        bot_dir = self.root / "telegram_bot"
        venv_dir = bot_dir / "venv"
        
        if sys.platform == "win32":
            python_exe = venv_dir / "Scripts" / "python.exe"
        else:
            python_exe = venv_dir / "bin" / "python"
        
        if not python_exe.exists():
            self._log("Creating telegram venv...")
            
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    capture_output=True,
                    timeout=60,
                    text=True
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr if result.stderr else result.stdout
                    self._log(f"Venv creation failed: {error_msg[:200]}")
                    return False
                
                # Wait a moment for venv to be fully initialized
                time.sleep(1)
                
                # Verify python exe exists
                if not python_exe.exists():
                    self._log(f"Venv created but python.exe not found at {python_exe}")
                    return False
                    
            except subprocess.TimeoutExpired:
                self._log("Venv creation timed out")
                return False
            except Exception as e:
                self._log(f"Failed to create venv: {str(e)[:200]}")
                return False
        
        deps_flag = venv_dir / ".deps_installed"
        if python_exe.exists() and deps_flag.exists():
            self._log("Telegram requirements already verified")
            return True
            
        self._log("Installing telegram requirements...")
        
        for attempt in range(3):
            try:
                result = subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "--upgrade", "pip"],
                    capture_output=True,
                    timeout=120,
                    text=True
                )
                
                if result.returncode != 0:
                    self._log(f"pip upgrade failed: {result.stderr[-100:] if result.stderr else result.stdout[-100:]}")
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    return False
                
                result = subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "--prefer-binary", "-r", "requirements.txt"],
                    cwd=str(bot_dir),
                    capture_output=True,
                    timeout=300,
                    text=True
                )
                
                if result.returncode != 0:
                    self._log(f"pip install failed: {result.stderr[-100:] if result.stderr else result.stdout[-100:]}")
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    return False
                
                try:
                    deps_flag.touch()
                except Exception:
                    pass
                self._log("Telegram requirements installed")
                return True
            except subprocess.TimeoutExpired:
                self._log(f"Attempt {attempt+1} timed out, retrying...")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False
            except Exception as e:
                self._log(f"Error on attempt {attempt+1}: {str(e)[:200]}")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False
        
        return False
        
        return False
    
    def ensure_electron_deps(self, post_callback=None):
        """Install Electron app dependencies."""
        electron_dir = self.root / "electron_app"
        node_modules = electron_dir / "node_modules"
        
        # Check if already installed
        if (node_modules / "electron").exists():
            self._log("Electron dependencies already installed")
            return True
        
        npm_exe = shutil.which("npm")
        if not npm_exe:
            self._log("npm not found - skipping Electron setup")
            return False
        
        self._log("Installing Electron dependencies...")
        
        try:
            subprocess.run(
                [npm_exe, "install"],
                cwd=str(electron_dir),
                check=True,
                capture_output=True,
                timeout=300,
                creationflags=0x08000000 if sys.platform == "win32" else 0
            )
            
            self._log("Electron dependencies installed")
            return True
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode() if e.stderr else ""
            self._log(f"npm install failed: {stderr[-100:] if stderr else 'Failed'}")
            return False
        except Exception as e:
            self._log(f"Error: {e}")
            return False
