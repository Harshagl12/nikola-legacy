"""
Nikola Executable Wrapper
Launches nikola_launcher/launcher.py using the local virtual environment.
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    try:
        # sys.argv[0] is the true path to Nikola.exe
        exe_path = Path(sys.argv[0]).resolve()
        base_dir = exe_path.parent
        
        # Guarantee we find the true Nikola root
        candidates = [
            base_dir,
            Path("C:/nikola"),
            Path("C:/nikola/nikola_launcher"),
            Path.cwd()
        ]
        nikola_root = None
        for cand in candidates:
            if cand and (cand / "nikola_launcher" / "launcher.py").exists():
                nikola_root = cand.resolve()
                break
        
        if not nikola_root:
            nikola_root = Path("C:/nikola").resolve()
            
        base_dir = nikola_root

        # Safely log inside nikola_root or user home
        try:
            log_file = base_dir / "wrapper_debug.log"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Wrapper starting. Argv0: {sys.argv[0]}, Base: {base_dir}\n")
        except Exception:
            pass

        venv_python = base_dir / ".venv" / "Scripts" / "python.exe"
        venv_pythonw = base_dir / ".venv" / "Scripts" / "pythonw.exe"
        backend_python = base_dir / "backend" / "venv" / "Scripts" / "python.exe"
        
        if venv_python.exists():
            python_exe = str(venv_python)
        elif venv_pythonw.exists():
            python_exe = str(venv_pythonw)
        elif backend_python.exists():
            python_exe = str(backend_python)
        else:
            python_exe = sys.executable

        launcher_script = str(base_dir / "nikola_launcher" / "launcher.py")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"Launching: {python_exe} {launcher_script}\n")

        creationflags = 0x08000000 if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [python_exe, launcher_script],
            cwd=str(base_dir),
            creationflags=creationflags
        )
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"Successfully launched PID: {proc.pid}\n")
    except Exception as e:
        try:
            log_file = Path.cwd() / "wrapper_debug.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"ERROR: {e}\n")
        except Exception:
            pass

if __name__ == "__main__":
    main()
