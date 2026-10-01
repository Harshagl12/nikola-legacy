import sys
import re
import secrets
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from cryptography.fernet import Fernet


class FirstRunSetup:
    def __init__(self, base_dir, nikola_root):
        self.nikola_root = Path(nikola_root)
        self.marker = Path.home() / ".nikola_setup_done"
        self.env_file = self.nikola_root / ".env"
        self._completed = False

    def is_first_run(self) -> bool:
        if not self.marker.exists() or not self.env_file.exists():
            return True
        content = self.env_file.read_text(errors="replace")
        return "BOT_TOKEN=your_telegram" in content or "BOT_TOKEN=\n" in content

    def run_wizard(self):
        root = tk.Tk()
        root.title("Nikola Setup")
        root.geometry("520x420")
        root.configure(bg="#0a0a14")
        root.resizable(False, False)
        # Center
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"520x420+{(sw-520)//2}+{(sh-420)//2}")
        root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

        # --- shared state ---
        data = {
            "token":   tk.StringVar(value=""),
            "userid":  tk.StringVar(value=""),
            "voice":   tk.BooleanVar(value=True),
            "whisper": tk.StringVar(value="base"),
            "vault":   tk.StringVar(value=str(self.nikola_root / "vault")),
            "chroma":  tk.StringVar(value=str(self.nikola_root / "nikola_chroma")),
            "startup": tk.BooleanVar(value=False),
        }

        container = tk.Frame(root, bg="#0a0a14")
        container.pack(fill="both", expand=True)

        frames = {}
        for F in ("WelcomePage", "TelegramPage", "VoicePage", "FolderPage", "DonePage"):
            frame = tk.Frame(container, bg="#0a0a14")
            frame.place(relwidth=1, relheight=1)
            frames[F] = frame

        def show(name):
            frames[name].tkraise()

        # ── helpers ──────────────────────────────────────────────────────────
        BG, FG, ACC, HINT = "#0a0a14", "#e8e8f0", "#7c6af7", "#a0a0b8"
        BTN = dict(bg=ACC, fg="white", font=("Segoe UI", 10, "bold"),
                   bd=0, padx=18, pady=8, cursor="hand2", activebackground="#6a5ae0")

        def lbl(parent, text, size=11, color=FG, bold=False):
            return tk.Label(parent, text=text,
                            font=("Segoe UI", size, "bold" if bold else "normal"),
                            bg=BG, fg=color)

        def entry(parent, var, show_char=""):
            e = tk.Entry(parent, textvariable=var, width=48,
                         bg="#1a1a2e", fg=FG, insertbackground=FG,
                         relief="flat", font=("Segoe UI", 10),
                         show=show_char)
            e.configure(highlightthickness=1, highlightbackground="#333355",
                        highlightcolor=ACC)
            return e

        # ── Page 1: Welcome ──────────────────────────────────────────────────
        p = frames["WelcomePage"]
        lbl(p, "Welcome to Nikola", 24, ACC, bold=True).pack(pady=(50, 8))
        lbl(p, "Your private local AI agent.", 13, HINT).pack()
        lbl(p, "Let's set up in 4 quick steps.", 11, HINT).pack(pady=(0, 40))
        tk.Button(p, text="Get Started →", command=lambda: show("TelegramPage"), **BTN).pack()

        # ── Page 2: Telegram ─────────────────────────────────────────────────
        p = frames["TelegramPage"]
        lbl(p, "Telegram Bot Setup", 20, ACC, bold=True).pack(pady=(30, 16))

        lbl(p, "Bot Token", 10).pack(anchor="w", padx=50)
        token_e = entry(p, data["token"], show_char="•")
        token_e.pack(padx=50, pady=(2, 2))
        lbl(p, "Get from @BotFather → /newbot", 8, HINT).pack(anchor="w", padx=50)

        lbl(p, "Your Telegram User ID", 10).pack(anchor="w", padx=50, pady=(12, 0))
        uid_e = entry(p, data["userid"])
        uid_e.pack(padx=50, pady=(2, 2))
        lbl(p, "Get from @userinfobot on Telegram", 8, HINT).pack(anchor="w", padx=50)

        # show/hide toggle
        show_state = {"v": False}
        def toggle_token():
            show_state["v"] = not show_state["v"]
            token_e.config(show="" if show_state["v"] else "•")
            tog_btn.config(text="Hide" if show_state["v"] else "Show")
        tog_btn = tk.Button(p, text="Show", command=toggle_token,
                            bg="#1a1a2e", fg=HINT, bd=0, font=("Segoe UI", 8))
        tog_btn.pack(anchor="e", padx=50)

        def validate_telegram():
            tok = data["token"].get().strip()
            uid = data["userid"].get().strip()
            if not re.match(r"^\d+:[A-Za-z0-9_-]{35,}$", tok):
                messagebox.showerror("Invalid Token", "Bot token format is invalid.")
                return
            if not uid.isdigit():
                messagebox.showerror("Invalid User ID", "User ID must be a number.")
                return
            show("VoicePage")
        tk.Button(p, text="Next →", command=validate_telegram, **BTN).pack(pady=20)

        # ── Page 3: Voice ────────────────────────────────────────────────────
        p = frames["VoicePage"]
        lbl(p, "Voice Activation", 20, ACC, bold=True).pack(pady=(40, 20))
        tk.Checkbutton(p, text="Enable 'Hey Nikola' wake word",
                       variable=data["voice"],
                       bg=BG, fg=FG, selectcolor="#1e1e2d",
                       activebackground=BG, font=("Segoe UI", 11)).pack(anchor="w", padx=50)
        lbl(p, "Whisper model size:", 10).pack(anchor="w", padx=50, pady=(16, 2))
        ttk.Combobox(p, textvariable=data["whisper"],
                     values=["tiny", "base", "small", "medium"],
                     state="readonly", width=20).pack(anchor="w", padx=50)
        lbl(p, "Larger = more accurate but slower. 'base' is recommended.", 8, HINT).pack(anchor="w", padx=50, pady=(4, 0))
        tk.Button(p, text="Next →", command=lambda: show("FolderPage"), **BTN).pack(pady=30)

        # ── Page 4: Folders ──────────────────────────────────────────────────
        p = frames["FolderPage"]
        lbl(p, "Storage Paths", 20, ACC, bold=True).pack(pady=(30, 16))

        def browse(var):
            d = filedialog.askdirectory()
            if d:
                var.set(d)

        for label_txt, var in [("Vault folder (your documents):", data["vault"]),
                                ("ChromaDB path (vector store):", data["chroma"])]:
            lbl(p, label_txt, 10).pack(anchor="w", padx=50, pady=(8, 0))
            row = tk.Frame(p, bg=BG)
            row.pack(anchor="w", padx=50, fill="x")
            entry(row, var).pack(side="left", fill="x", expand=True)
            tk.Button(row, text="…", command=lambda v=var: browse(v),
                      bg="#1a1a2e", fg=FG, bd=0, padx=6).pack(side="left", padx=(4, 0))

        tk.Checkbutton(p, text="Launch Nikola on Windows startup",
                       variable=data["startup"],
                       bg=BG, fg=FG, selectcolor="#1e1e2d",
                       activebackground=BG, font=("Segoe UI", 10)).pack(anchor="w", padx=50, pady=14)
        tk.Button(p, text="Next →", command=lambda: show("DonePage"), **BTN).pack(pady=10)

        # ── Page 5: Done ─────────────────────────────────────────────────────
        p = frames["DonePage"]
        lbl(p, "All Set! 🎉", 24, ACC, bold=True).pack(pady=(40, 10))
        lbl(p, "Nikola is configured and ready to launch.", 12, HINT).pack()

        summary_var = tk.StringVar()
        def update_summary():
            tok = data["token"].get()
            masked = tok[:10] + "***" if len(tok) > 10 else tok
            summary_var.set(
                f"Token: {masked}\n"
                f"User ID: {data['userid'].get()}\n"
                f"Vault: {data['vault'].get()}\n"
                f"Voice: {'on' if data['voice'].get() else 'off'} / {data['whisper'].get()}"
            )
        tk.Label(p, textvariable=summary_var, bg="#111122", fg=HINT,
                 font=("Segoe UI", 9), justify="left",
                 relief="flat", padx=12, pady=8).pack(padx=50, pady=10, fill="x")

        def launch():
            update_summary()
            self._write_env(data)
            self._completed = True
            root.destroy()

        p.bind("<Visibility>", lambda e: update_summary())
        tk.Button(p, text="Launch Nikola 🚀", command=launch, **BTN).pack(pady=10)

        show("WelcomePage")
        root.mainloop()

        if not self._completed:
            sys.exit(0)

    def _write_env(self, data):
        key = Fernet.generate_key().decode()
        env = f"""OLLAMA_HOST=http://localhost:11434
VAULT_PATH={data['vault'].get()}
CHROMA_PATH={data['chroma'].get()}
BOT_TOKEN={data['token'].get().strip()}
ALLOWED_USER_ID={data['userid'].get().strip()}
BACKEND_URL=http://localhost:8000
NIKOLA_API_KEY={secrets.token_urlsafe(32)}
RUN_COMMANDS=false
VOICE_ENABLED={str(data['voice'].get()).lower()}
WAKE_WORD=hey nikola
WHISPER_MODEL={data['whisper'].get()}
TTS_ENGINE=pyttsx3
AUTOFILL_PROFILE_PATH=~/nikola_profile.json.enc
AUTOFILL_ENCRYPTION_KEY={key}
PROFILE_REQUIRES_CONFIRMATION=true
"""
        self.env_file.write_text(env)
        self.marker.touch()

        if data["startup"].get():
            try:
                import winreg
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                   r"Software\Microsoft\Windows\CurrentVersion\Run",
                                   0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(k, "Nikola", 0, winreg.REG_SZ, str(Path(sys.executable)))
                winreg.CloseKey(k)
            except Exception:
                pass
