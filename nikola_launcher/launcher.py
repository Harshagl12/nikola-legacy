"""
Nikola Launcher — Main entry point.
Becomes Nikola.exe via PyInstaller.

Architecture:
  - Main thread:  tkinter (splash + wizard) → pystray tray icon
  - Worker thread: all install/startup work, communicates via queue
"""

import sys
import os
import json
import queue
import socket
import threading
import time
import logging
import tkinter as tk
import tkinter.messagebox as mb
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution — frozen (.exe) or source
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR    = Path(sys.executable).parent
    NIKOLA_ROOT = BASE_DIR
else:
    BASE_DIR    = Path(__file__).resolve().parent
    NIKOLA_ROOT = BASE_DIR.parent

# Guarantee NIKOLA_ROOT is valid (never bare C:\)
if not (NIKOLA_ROOT / "nikola_launcher").exists():
    if Path("C:/nikola").exists():
        NIKOLA_ROOT = Path("C:/nikola").resolve()
        BASE_DIR = NIKOLA_ROOT / "nikola_launcher"

LOCK_PORT = 47821

# ---------------------------------------------------------------------------
# Logging — write to nikola_launcher.log in NIKOLA_ROOT or user home
# ---------------------------------------------------------------------------
LOG_FILE = NIKOLA_ROOT / "nikola_launcher.log"

logger = logging.getLogger("nikola")
logger.setLevel(logging.INFO)

try:
    _fh = logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8")
except (PermissionError, OSError):
    # Fallback to user home directory if root is not writable
    LOG_FILE = Path(os.path.expanduser("~")) / ".nikola" / "nikola_launcher.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8")

_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

# Also log to console when running from source
if not getattr(sys, "frozen", False):
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Single-instance lock
# ---------------------------------------------------------------------------
def acquire_lock():
    """Try to acquire port lock. Return socket if successful, None if already locked."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Allow reuse of port in TIME_WAIT state (handles stale locks)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError as e:
        s.close()
        logger.warning(f"Could not acquire lock (port {LOCK_PORT} in use): {e}")
        return None

# ---------------------------------------------------------------------------
# Queue message types
# ---------------------------------------------------------------------------
MSG_STATUS   = "status"
MSG_SUBSTATUS = "substatus"
MSG_PROGRESS = "progress"
MSG_DONE     = "done"
MSG_ERROR    = "error"
MSG_WIZARD   = "wizard"   # request wizard on main thread


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        lock = acquire_lock()
        if lock is None:
            logger.info("Another instance is already running — activating it.")
            sys.exit(0)

        # Ensure nikola_launcher package is importable
        if not getattr(sys, "frozen", False):
            # Running from source: keep project packages and launcher modules importable.
            sys.path.insert(0, str(NIKOLA_ROOT))
            sys.path.insert(0, str(BASE_DIR))
        # Frozen builds must resolve third-party packages from PyInstaller's
        # isolated runtime, not copied package folders beside Nikola.exe.

        from dep_installer   import DepInstaller
        from process_manager import ProcessManager
        from health_check    import HealthChecker
        from first_run       import FirstRunSetup

        work_q  = queue.Queue()   # worker → main thread
        reply_q = queue.Queue()   # main thread → worker (wizard done)

        pm        = ProcessManager(NIKOLA_ROOT, NIKOLA_ROOT)
        health    = HealthChecker()
        installer = DepInstaller(NIKOLA_ROOT)
        setup     = FirstRunSetup(NIKOLA_ROOT, NIKOLA_ROOT)

        TOTAL_STEPS = 13
        step_count  = [0]

        def post(kind, value=""):
            work_q.put((kind, value))

        def advance(msg, error=False):
            step_count[0] += 1
            logger.info(msg)
            post(MSG_STATUS, msg)
            post(MSG_PROGRESS, step_count[0] / TOTAL_STEPS)

        # ── Worker thread ────────────────────────────────────────────────────────
        def worker():
            try:
                pm._load_env()

                # 1
                advance("Checking Qwen3 1.7B engine...")
                pm.ensure_llama_server()
                pm.ensure_vision_server()

                # 2
                advance("Verifying local AI models...")
                pm.ensure_models_q(post)


                # 3
                advance("Checking vault folder...")
                from backend.filesystem_policy import local_vault_path

                local_vault_path(os.getenv("VAULT_PATH", str(NIKOLA_ROOT / "vault")))

                # 4
                advance("Setting up backend environment...")
                installer.ensure_backend_venv(post)

                # 5
                advance("Setting up Telegram bot environment...")
                installer.ensure_telegram_venv(post)

                # 6
                advance("Checking Electron dependencies...")
                installer.ensure_electron_deps(post)

                # 7 — First-run wizard (runs on MAIN thread)
                advance("Checking configuration...")
                if setup.is_first_run():
                    post(MSG_WIZARD, "")
                    reply_q.get()   # block until wizard finishes
                pm._load_env(require_api_key=True)

                # 8
                advance("Starting Nikola backend...")
                if not pm.start_backend():
                    raise RuntimeError("Nikola's local backend could not be started.")

                # 9
                advance("Confirming Nikola backend is responding...")
                if not health.wait_for_backend(
                    timeout=20,
                    process=pm.processes.get("backend"),
                ):
                    raise RuntimeError(
                        "Nikola's backend exited or did not expose its health endpoint. "
                        "Check backend/backend.log."
                    )

                # 10
                advance("Starting Telegram bot...")
                pm.start_telegram_bot()

                # 11
                advance("Opening Nikola assistant...")
                pm.start_electron()

                # 12
                advance("Starting service watchdog...")
                pm.start_watchdog()

                # 13
                advance("Backend online; local services are initializing...")
                time.sleep(1)

                post(MSG_DONE, "")

            except Exception as e:
                logger.exception("Fatal launch error in worker")
                post(MSG_ERROR, str(e))

    # ── Build Splash UI (main thread) ─────────────────────────────────────────
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg="#0a0a14")
        root.attributes("-topmost", True)

        W, H = 440, 240
        root.geometry(f"{W}x{H}+{(root.winfo_screenwidth()-W)//2}+{(root.winfo_screenheight()-H)//2}")

        tk.Label(root, text="Nikola", font=("Segoe UI", 28, "bold"),
                 bg="#0a0a14", fg="#7c6af7").place(x=W//2, y=48, anchor="center")
        tk.Label(root, text="Local AI Agent", font=("Segoe UI", 12),
                 bg="#0a0a14", fg="#a0a0b8").place(x=W//2, y=80, anchor="center")

        status_var    = tk.StringVar(value="Starting…")
        substatus_var = tk.StringVar(value="")

        status_lbl = tk.Label(root, textvariable=status_var,
                              font=("Segoe UI", 11), bg="#0a0a14", fg="#e8e8f0")
        status_lbl.place(x=W//2, y=130, anchor="center")

        tk.Label(root, textvariable=substatus_var, font=("Segoe UI", 9),
                 bg="#0a0a14", fg="#7878a0").place(x=W//2, y=152, anchor="center")

        bar_canvas = tk.Canvas(root, width=W-40, height=6, bg="#1e1e2d",
                               highlightthickness=0)
        bar_canvas.place(x=20, y=175)
        bar_rect = bar_canvas.create_rectangle(0, 0, 0, 6, fill="#7c6af7", width=0)

        tk.Label(root, text="v1.0.0", font=("Segoe UI", 8),
                 bg="#0a0a14", fg="#444455").place(x=W-8, y=H-16, anchor="e")

        root.update()

        # ── Shared state for wizard coordination ──────────────────────────────────
        wizard_pending = [False]

        def run_wizard_on_main():
            root.withdraw()   # hide splash during wizard
            setup.run_wizard()
            root.deiconify()
            reply_q.put("done")

        # ── Queue poll — runs on main thread via after() ──────────────────────────
        def poll():
            try:
                while True:
                    kind, value = work_q.get_nowait()

                    if kind == MSG_STATUS:
                        status_var.set(value)
                        status_lbl.config(fg="#e8e8f0")

                    elif kind == MSG_SUBSTATUS:
                        substatus_var.set(str(value)[:75] if value else "")

                    elif kind == MSG_PROGRESS:
                        w = int(float(value) * (W - 40))
                        bar_canvas.coords(bar_rect, 0, 0, w, 6)

                    elif kind == MSG_WIZARD:
                        wizard_pending[0] = True

                    elif kind == MSG_DONE:
                        root.destroy()
                        return   # stop polling — will fall through to tray

                    elif kind == MSG_ERROR:
                        root.destroy()
                        mb.showerror("Nikola — Error", value)
                        pm.stop_all()
                        sys.exit(1)
                        return

            except queue.Empty:
                pass

            # Run wizard after emptying queue
            if wizard_pending[0]:
                wizard_pending[0] = False
                run_wizard_on_main()

            root.after(100, poll)

        # ── Start worker + poll loop ────────────────────────────────────────────
        threading.Thread(target=worker, daemon=True).start()
        root.after(100, poll)
        root.mainloop()   # blocks until root.destroy()

        # ── Tray (runs on main thread after splash exits) ─────────────────────────
        from tray import NikolaTray
        tray = NikolaTray(pm, NIKOLA_ROOT)
        tray.run()

        lock.close()
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in launcher")
        try:
            # Try to show error dialog
            root = tk.Tk()
            root.withdraw()
            mb.showerror("Nikola Launcher Error", 
                        f"Failed to start Nikola:\n\n{str(e)}\n\n"
                        "Check logs at:\n"
                        f"{LOG_FILE}")
            root.destroy()
        except Exception:
            pass  # If UI fails, at least it's in the log
        sys.exit(1)


def _pillow_self_test(report_path: Path) -> int:
    """Import Pillow through this runtime and write a non-secret test report."""
    try:
        import PIL
        from PIL import Image, ImageGrab
        import PIL._imaging

        report = {
            "ok": True,
            "pillow": str(Path(PIL.__file__).resolve()),
            "image": str(Path(Image.__file__).resolve()),
            "image_grab": str(Path(ImageGrab.__file__).resolve()),
            "imaging": str(Path(PIL._imaging.__file__).resolve()),
        }
    except Exception as error:
        report = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    self_test_argument = next(
        (argument for argument in sys.argv[1:] if argument.startswith("--pillow-self-test=")),
        None,
    )
    if self_test_argument:
        sys.exit(_pillow_self_test(Path(self_test_argument.split("=", 1)[1])))
    main()
