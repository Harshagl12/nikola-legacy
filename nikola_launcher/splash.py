import tkinter as tk
import threading


class SplashWindow:
    def __init__(self):
        self._ready = threading.Event()
        self._root = None
        self._status_var = None
        self._substatus_var = None
        self._progress_var = None
        self._canvas = None
        self._bar = None

    def show(self):
        root = tk.Tk()
        self._root = root
        root.overrideredirect(True)
        root.configure(bg="#0a0a14")

        W, H = 440, 240
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        tk.Label(root, text="Nikola", font=("Segoe UI", 28, "bold"),
                 bg="#0a0a14", fg="#7c6af7").place(x=W//2, y=50, anchor="center")
        tk.Label(root, text="Local AI Agent", font=("Segoe UI", 12),
                 bg="#0a0a14", fg="#a0a0b8").place(x=W//2, y=82, anchor="center")

        self._status_var = tk.StringVar(value="Starting...")
        self._substatus_var = tk.StringVar(value="")

        tk.Label(root, textvariable=self._status_var, font=("Segoe UI", 11),
                 bg="#0a0a14", fg="#e8e8f0").place(x=W//2, y=130, anchor="center")
        tk.Label(root, textvariable=self._substatus_var, font=("Segoe UI", 9),
                 bg="#0a0a14", fg="#7878a0").place(x=W//2, y=152, anchor="center")

        # Progress bar
        canvas = tk.Canvas(root, width=W-40, height=6, bg="#1e1e2d",
                           highlightthickness=0)
        canvas.place(x=20, y=175)
        self._canvas = canvas
        self._bar = canvas.create_rectangle(0, 0, 0, 6, fill="#7c6af7", width=0)

        tk.Label(root, text="v1.0.0", font=("Segoe UI", 8),
                 bg="#0a0a14", fg="#444455").place(x=W-10, y=H-18, anchor="e")

        self._ready.set()
        root.mainloop()

    def _run_in_main(self, fn):
        if self._root:
            self._root.after(0, fn)

    def update_status(self, text, error=False):
        color = "#ff6b6b" if error else "#e8e8f0"
        def _do():
            if self._status_var:
                self._status_var.set(text)
            if self._root:
                for w in self._root.winfo_children():
                    if isinstance(w, tk.Label) and w.cget("textvariable") == str(self._status_var):
                        w.config(fg=color)
        self._run_in_main(_do)

    def update_substatus(self, text):
        def _do():
            if self._substatus_var:
                self._substatus_var.set(text[:80] if text else "")
        self._run_in_main(_do)

    def set_progress(self, val):
        def _do():
            if self._canvas and self._bar:
                width = int((val or 0) * (440 - 40))
                self._canvas.coords(self._bar, 0, 0, width, 6)
        self._run_in_main(_do)

    def close(self):
        def _do():
            if self._root:
                self._root.destroy()
                self._root = None
        self._run_in_main(_do)
