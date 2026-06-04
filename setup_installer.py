"""
Bull Put Spread Bot – Setup / Installer
Lädt die aktuelle Version herunter, installiert Abhängigkeiten und legt
eine Desktop-Verknüpfung an.
"""
import os, sys, subprocess, urllib.request, shutil, threading, winreg
import tkinter as tk
from tkinter import ttk, messagebox

VERSION     = "3.2.22"
REPO_RAW    = "https://raw.githubusercontent.com/xTheRichiNOT/bull-put-spread-bot/main"
FILES       = ["bot.py", "launcher.py", "backtest.py",
               "shadow_analyze.py", "version.txt", "requirements.txt"]
INSTALL_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                           "BullPutSpreadBot")


def _find_python():
    for cand in [sys.executable,
                 shutil.which("python"), shutil.which("python3"),
                 r"C:\Python312\python.exe", r"C:\Python311\python.exe",
                 r"C:\Python310\python.exe"]:
        if cand and os.path.isfile(cand):
            return cand
    return None


class InstallerUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Bull Put Spread Bot  v{VERSION}  –  Setup")
        self.geometry("480x240")
        self.resizable(False, False)
        self.configure(bg="#0d1117")

        tk.Label(self, text=f"Bull Put Spread Bot  v{VERSION}",
                 font=("Segoe UI", 14, "bold"),
                 fg="#4ade80", bg="#0d1117").pack(pady=(24, 4))
        tk.Label(self, text="Installation läuft …",
                 font=("Segoe UI", 10), fg="#94a3b8", bg="#0d1117").pack()

        self._status = tk.Label(self, text="",
                                font=("Consolas", 9),
                                fg="#60a5fa", bg="#0d1117")
        self._status.pack(pady=(8, 4))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("green.Horizontal.TProgressbar",
                        troughcolor="#1e293b", background="#4ade80",
                        bordercolor="#0d1117", lightcolor="#4ade80",
                        darkcolor="#22c55e")
        self._bar = ttk.Progressbar(self, style="green.Horizontal.TProgressbar",
                                    length=400, mode="determinate",
                                    maximum=len(FILES) + 3)
        self._bar.pack(pady=4)

        self._detail = tk.Label(self, text="",
                                font=("Consolas", 8), fg="#475569", bg="#0d1117")
        self._detail.pack()

        self.after(300, self._run)

    def _step(self, status, detail=""):
        self._status.configure(text=status)
        self._detail.configure(text=detail)
        self._bar.step(1)
        self.update_idletasks()

    def _run(self):
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self):
        try:
            # 1. Verzeichnis anlegen
            self.after(0, lambda: self._step("Verzeichnis anlegen …", INSTALL_DIR))
            os.makedirs(INSTALL_DIR, exist_ok=True)

            # 2. Dateien herunterladen
            for fname in FILES:
                self.after(0, lambda f=fname: self._step(
                    f"Lade {f} …", f"{REPO_RAW}/{f}"))
                url  = f"{REPO_RAW}/{fname}"
                dest = os.path.join(INSTALL_DIR, fname)
                urllib.request.urlretrieve(url, dest)

            # 3. pip-Abhängigkeiten installieren
            self.after(0, lambda: self._step("Installiere Abhängigkeiten …",
                                             "pip install -r requirements.txt"))
            py = _find_python()
            if py:
                req = os.path.join(INSTALL_DIR, "requirements.txt")
                subprocess.run([py, "-m", "pip", "install", "-r", req,
                                "--quiet", "--disable-pip-version-check"],
                               check=False)

            # 4. Desktop-Verknüpfung (.bat)
            self.after(0, lambda: self._step("Erstelle Desktop-Verknüpfung …"))
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            bat     = os.path.join(desktop, "Bull Put Spread Bot.bat")
            with open(bat, "w") as f:
                f.write(f'@echo off\n'
                        f'cd /d "{INSTALL_DIR}"\n'
                        f'"{py or "python"}" launcher.py\n')

            # 5. Fertig
            self.after(0, self._done)

        except Exception as exc:
            self.after(0, lambda e=exc: self._error(e))

    def _done(self):
        self._bar["value"] = self._bar["maximum"]
        self._status.configure(text="✅  Installation abgeschlossen!", fg="#4ade80")
        self._detail.configure(text="")
        if messagebox.askyesno("Fertig",
                               f"Bull Put Spread Bot v{VERSION} wurde installiert.\n\n"
                               "Bot jetzt starten?",
                               icon="info"):
            py = _find_python()
            if py:
                subprocess.Popen([py, os.path.join(INSTALL_DIR, "launcher.py")],
                                 cwd=INSTALL_DIR)
        self.destroy()

    def _error(self, exc):
        self._status.configure(text="❌  Fehler", fg="#f87171")
        self._detail.configure(text=str(exc))
        messagebox.showerror("Fehler", f"Installation fehlgeschlagen:\n{exc}")
        self.destroy()


if __name__ == "__main__":
    app = InstallerUI()
    app.mainloop()
