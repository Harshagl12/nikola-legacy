#!/usr/bin/env python3
"""
Root forwarding script for NIKOLA Launcher.
Allows running 'python launcher.py' directly from the workspace root.
"""
import sys
import os
import subprocess
from pathlib import Path

def main():
    root_dir = Path(__file__).resolve().parent
    launcher_path = root_dir / "nikola_launcher" / "launcher.py"
    
    # Check for virtualenv python
    venv_python = root_dir / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists() and os.path.normpath(sys.executable) != os.path.normpath(str(venv_python)):
        python_exe = str(venv_python)
    else:
        python_exe = sys.executable
        
    print(f"[NIKOLA] Launching from workspace root via {python_exe}...")
    sys.stdout.flush()
    
    cmd = [python_exe, str(launcher_path)] + sys.argv[1:]
    try:
        return subprocess.call(cmd, cwd=str(root_dir))
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"[NIKOLA] Error launching: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
