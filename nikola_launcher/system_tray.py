"""
System Tray — Windows tray icon, global hotkeys, and notifications.
"""

import os
import sys
import threading
import time
import logging
from pathlib import Path

import pystray
from PIL import Image

try:
    import ctypes
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except Exception:
    WIN32_AVAILABLE = False


def _make_icon(icon_path: Path):
    with Image.open(icon_path) as image:
        return image.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)


class NikolaTray:
    def __init__(self, pm, nikola_root: Path):
        self.pm = pm
        self.pm.tray = self
        self.nikola_root = Path(nikola_root)
        self.icon = None
        self._running = False

    def notify(self, title: str, message: str):
        """Display Windows system tray balloon notification."""
        if self.icon and self.icon.visible:
            try:
                self.icon.notify(message, title)
            except Exception as e:
                print(f"Tray notify failed: {e}")

    def _build_menu(self):
        def bk_label(_):
            return f"Backend: {'✓ running' if self.pm.get_status().get('backend') else '✗ stopped'}"
        def tg_label(_):
            return f"Telegram: {'✓ running' if self.pm.get_status().get('telegram') else '✗ stopped'}"

        return pystray.Menu(
            pystray.MenuItem("Nikola AI", None, enabled=False),
            pystray.MenuItem(bk_label, None, enabled=False),
            pystray.MenuItem(tg_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show sidebar (Ctrl+Shift+Space)", self._show_sidebar),
            pystray.MenuItem("Open vault folder", self._open_vault),
            pystray.MenuItem("View logs", self._open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart backend", lambda _: self.pm.restart_backend()),
            pystray.MenuItem("Restart Telegram bot", lambda _: self.pm.restart_telegram_bot()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Nikola", self._quit),
        )

    def _show_sidebar(self, icon=None, item=None):
        if WIN32_AVAILABLE:
            try:
                def enum_cb(hwnd, results):
                    title = win32gui.GetWindowText(hwnd)
                    if "nikola" in title.lower():
                        results.append(hwnd)
                results = []
                win32gui.EnumWindows(enum_cb, results)
                if results:
                    hwnd = results[0]
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    return
            except Exception:
                pass
        # Fallback — re-launch electron
        self.pm.start_electron()

    def _open_vault(self, icon=None, item=None):
        from backend.filesystem_policy import local_vault_path

        vault = local_vault_path(
            os.getenv("VAULT_PATH", str(self.nikola_root / "vault"))
        )
        if sys.platform == "win32":
            os.startfile(str(vault))

    def _open_logs(self, icon=None, item=None):
        if sys.platform == "win32":
            os.startfile(str(self.nikola_root))

    def _quit(self, icon=None, item=None):
        self._running = False
        self.pm.stop_all()
        if self.icon:
            self.icon.stop()

    def _refresh_loop(self):
        while self._running and self.icon:
            time.sleep(10)
            try:
                if self.icon and self.icon.visible:
                    self.icon.update_menu()
            except Exception:
                pass

    def _hotkey_loop(self):
        """Monitor for Ctrl+Shift+Space global hotkey on Windows."""
        if not WIN32_AVAILABLE or sys.platform != "win32":
            return
        
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        VK_SPACE = 0x20
        
        user32 = ctypes.windll.user32
        last_triggered = 0
        
        while self._running:
            time.sleep(0.05)
            try:
                ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                shift = user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
                space = user32.GetAsyncKeyState(VK_SPACE) & 0x8000
                
                if ctrl and shift and space:
                    now = time.time()
                    if now - last_triggered > 1.0:  # 1 second debounce
                        last_triggered = now
                        self._show_sidebar()
            except Exception:
                pass

    def run(self):
        self._running = True
        icon_root = Path(getattr(sys, "_MEIPASS", self.nikola_root / "nikola_launcher"))
        self.icon = pystray.Icon(
            "Nikola",
            _make_icon(icon_root / "nikola_icon.ico"),
            "Nikola AI",
            menu=self._build_menu(),
        )
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        self.icon.run()

    def stop(self):
        self._running = False
        if self.icon:
            self.icon.stop()
