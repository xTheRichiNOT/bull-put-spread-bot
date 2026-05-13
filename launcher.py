"""
Bull Put Spread Bot — GUI Launcher
"""
import customtkinter as ctk
import threading
import queue as queue_module
import json
import subprocess
import sys
import os
import platform
import shutil
import urllib.request
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH  = os.path.join(_BASE, "config.json")
BOT_PATH     = os.path.join(_BASE, "bot.py")
VERSION_FILE = os.path.join(_BASE, "version.txt")

# ── Version & Update-URL ─────────────────────────────────────────────────────
# Ersetze DEIN_USERNAME und DEIN_REPO mit deinen GitHub-Daten.
# Das Repo muss öffentlich sein ODER du verwendest einen Personal Access Token.
VERSION         = open(VERSION_FILE).read().strip() if os.path.exists(VERSION_FILE) else "1.0.0"
UPDATE_BASE_URL = "https://raw.githubusercontent.com/xTheRichiNOT/bull-put-spread-bot-releases/main"

# Dateien die beim Update heruntergeladen werden
UPDATE_FILES = ["bot.py", "version.txt", "requirements.txt"]
# launcher.py wird separat behandelt (läuft gerade) → wird als launcher.py.new gespeichert
# ────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "ib_host":             "127.0.0.1",
    "ib_port":             7497,
    "ib_account":          "",
    "min_vola":            0.28,
    "abstand_y":           0.10,
    "min_credit":          70,
    "min_risk_reward":     0.20,
    "max_delta":           0.28,
    "max_positions":       8,
    "max_per_sector":      2,
    "scan_intervall":      60,
    "auto_trade":          True,
    "take_profit_pct":     0.50,
    "stop_loss_mult":      2.0,
    "dte_exit":            21,
    "min_available_funds": 2000,
}

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

IB_SETUP_TEXT = """
╔══════════════════════════════════════════════════════════════════════════╗
║         Interactive Brokers Setup — Schritt für Schritt                 ║
╚══════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 1 — TWS herunterladen & installieren
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Öffne: www.interactivebrokers.com
  2. Navigiere zu: Handelsplattformen → Trader Workstation (TWS)
  3. Lade TWS herunter (empfohlen: "Latest" Version)
  4. Installiere TWS wie eine normale Anwendung

  ℹ  Alternativ: IB Gateway (leichter, läuft dauerhaft im Hintergrund)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 2 — Konto erstellen (Paper Trading = kostenlos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Paper Trading:  Kostenloses Demokonto mit $1.000.000 Testkapital
                  → Kein echtes Geld, ideal zum Testen des Bots
                  → Konto-Nummer beginnt mit "DU"  (z.B. DU1234567)

  Live Trading:   Echtes Brokerkonto
                  → Konto-Nummer beginnt mit "U"   (z.B. U1234567)

  So erstellst du ein Paper Trading Konto:
  1. Einloggen auf interactivebrokers.com
  2. Konto → Paper Trading Konto → Paper Trading Konto beantragen


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 3 — TWS starten & einloggen
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Starte TWS
  2. Wähle beim Login "Paper Trading" (für Tests)
     ODER  "Live Trading"  (für echten Handel)
  3. Gib deine IB-Zugangsdaten ein


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 4 — API aktivieren   ← WICHTIGSTER SCHRITT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  In TWS:   Edit → Global Configuration → API → Settings

  Folgende Einstellungen setzen:

  ✅  "Enable ActiveX and Socket Clients"       AKTIVIEREN
  ✅  "Allow connections from localhost only"    AKTIVIEREN
  ❌  "Read-Only API"                            DEAKTIVIEREN
       (sonst kann der Bot KEINE Orders platzieren!)

  Socket Port:
  ┌───────────────────────────────────────────────────────────┐
  │  TWS Paper Trading          →  Port 7497  (Standard)      │
  │  TWS Live Trading           →  Port 7496                  │
  │  IB Gateway Paper           →  Port 4002                  │
  │  IB Gateway Live            →  Port 4001                  │
  └───────────────────────────────────────────────────────────┘

  → Klicke "OK" dann "Apply"
  → TWS muss NICHT neugestartet werden


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 5 — Account-Nummer herausfinden
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  In TWS:
  • Oben rechts neben deinem Namen steht deine Account-Nummer
  • ODER:  Konto → Kontoauszug → Account-Nummer oben links

  Diese Nummer trägst du in den Einstellungen unter
  "Account-Nummer" ein  (z.B. DU1234567 oder U1234567)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 6 — Options-Handel freischalten
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Der Bot handelt Bull Put Spreads (Options-Strategie).
  Options müssen in deinem IB-Konto freigeschaltet sein.

  In TWS:  Konto → Konto-Management → Handelsberechtigungen
           → Options → Stufe 2 (oder höher) beantragen

  ℹ  Paper Trading Konten haben Options standardmäßig freigeschaltet


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SCHRITT 7 — Bot starten
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Checkliste vor dem ersten Start:

  ☐  TWS läuft und du bist eingeloggt
  ☐  API ist aktiviert  (Schritt 4)
  ☐  Account-Nummer in Einstellungen eingetragen
  ☐  Richtiger Port in Einstellungen  (7497 für Paper)
  ☐  "Auto-Trade" in Einstellungen nach Wunsch gesetzt
     (Aus = nur Signale anzeigen,  An = automatisch Orders platzieren)

  → Tab "Dashboard" → "Bot starten" klicken


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 HÄUFIGE FEHLER & LÖSUNGEN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ❌  "Connection refused" / "Timeout auf Port 7497"
      → TWS ist nicht geöffnet oder nicht eingeloggt
      → API nicht aktiviert  (Schritt 4 nochmal prüfen)
      → Falscher Port  (Paper=7497, Live=7496)

  ❌  "Error 201: Order rejected"
      → "Read-Only API" ist noch aktiviert → deaktivieren!
      → Options nicht freigeschaltet  (Schritt 6)

  ❌  Bot läuft aber platziert keine Orders
      → Markt ist geschlossen  (NYSE: Mo–Fr 15:30–22:00 MEZ)
      → AUTO_TRADE ist auf "Aus" gestellt
      → IV zu niedrig — kein Signal über den Filter
      → Portfolio voll  (Max. Positionen erreicht)

  ❌  Bot startet nicht (Python-Fehler)
      → Abhängigkeiten nicht installiert
      → install_mac.sh bzw. install_windows.bat nochmal ausführen
""".strip()


class BotLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Bull Put Spread Bot  v{VERSION}")
        self.geometry("960x740")
        self.minsize(820, 620)

        self.cfg     = load_config()
        self._proc   = None
        self._queue  = queue_module.Queue()
        self._running = False

        self._build_ui()
        self._poll_queue()

        # Check for updates silently in background
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ───────────────────────────────────────────────────────────
        self._hdr = ctk.CTkFrame(self, height=54, corner_radius=0,
                                 fg_color=("#111827", "#111827"))
        self._hdr.pack(fill="x")
        self._hdr.pack_propagate(False)

        ctk.CTkLabel(self._hdr, text=f"  Bull Put Spread Bot",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color="#38bdf8").pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(self._hdr, text=f"v{VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color="#475569").pack(side="left", pady=10)

        self._status_dot = ctk.CTkLabel(self._hdr, text="● GESTOPPT",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        text_color="#f87171")
        self._status_dot.pack(side="right", padx=20)

        # ── Update banner (hidden until update found) ─────────────────────
        self._update_bar = ctk.CTkFrame(self, height=0, corner_radius=0,
                                        fg_color=("#1e3a5f", "#1e3a5f"))
        self._update_bar.pack(fill="x")
        self._update_bar.pack_propagate(False)

        # ── Tabs ─────────────────────────────────────────────────────────────
        tabs = ctk.CTkTabview(self, anchor="nw")
        tabs.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        tabs.add("Dashboard")
        tabs.add("Einstellungen")
        tabs.add("IB-Setup Guide")

        self._build_dashboard(tabs.tab("Dashboard"))
        self._build_settings(tabs.tab("Einstellungen"))
        self._build_guide(tabs.tab("IB-Setup Guide"))

    # ── Dashboard tab ────────────────────────────────────────────────────────

    def _build_dashboard(self, parent):
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=6, pady=(8, 4))

        self._start_btn = ctk.CTkButton(
            ctrl, text="▶  Bot starten", width=170, height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#166534", hover_color="#14532d",
            command=self._start_bot)
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            ctrl, text="■  Stoppen", width=140, height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#991b1b", hover_color="#7f1d1d",
            state="disabled", command=self._stop_bot)
        self._stop_btn.pack(side="left", padx=(0, 14))

        ctk.CTkButton(
            ctrl, text="Log leeren", width=100, height=42,
            fg_color=("#374151", "#374151"), hover_color=("#4b5563", "#4b5563"),
            command=self._clear_log).pack(side="left")

        ctk.CTkLabel(parent, text="Live-Log:", anchor="w",
                     font=ctk.CTkFont(size=12)).pack(fill="x", padx=8, pady=(4, 1))

        self._log = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(family="Courier", size=12),
            state="disabled", wrap="word",
            fg_color=("#0f172a", "#0f172a"), text_color="#94a3b8")
        self._log.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    # ── Settings tab ─────────────────────────────────────────────────────────

    def _build_settings(self, parent):
        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True, padx=6, pady=6)
        scroll.columnconfigure(1, weight=0)
        scroll.columnconfigure(2, weight=1)

        self._fields = {}
        self._row = 0

        def section(title):
            ctk.CTkLabel(scroll, text=title,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#38bdf8", anchor="w").grid(
                row=self._row, column=0, columnspan=3,
                sticky="w", pady=(16, 3), padx=4)
            sep = ctk.CTkFrame(scroll, height=1, fg_color="#334155")
            sep.grid(row=self._row + 1, column=0, columnspan=3,
                     sticky="ew", padx=4, pady=(0, 6))
            self._row += 2

        def field(label, key, width=130, tip=""):
            ctk.CTkLabel(scroll, text=label, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(
                row=self._row, column=0, sticky="w", padx=(6, 16), pady=3)
            e = ctk.CTkEntry(scroll, width=width, font=ctk.CTkFont(size=12))
            e.insert(0, str(self.cfg.get(key, "")))
            e.grid(row=self._row, column=1, sticky="w", pady=3)
            if tip:
                ctk.CTkLabel(scroll, text=tip, text_color="#64748b",
                             font=ctk.CTkFont(size=11), anchor="w").grid(
                    row=self._row, column=2, sticky="w", padx=10)
            self._fields[key] = e
            self._row += 1

        def port_field(label, key):
            ctk.CTkLabel(scroll, text=label, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(
                row=self._row, column=0, sticky="w", padx=(6, 16), pady=3)
            options = [
                "7497  (TWS Paper Trading)",
                "7496  (TWS Live Trading)",
                "4002  (IB Gateway Paper)",
                "4001  (IB Gateway Live)",
            ]
            cur = str(self.cfg.get(key, 7497))
            default = next((o for o in options if o.startswith(cur)), options[0])
            var = ctk.StringVar(value=default)
            m = ctk.CTkOptionMenu(scroll, values=options, variable=var, width=230,
                                  font=ctk.CTkFont(size=12))
            m.grid(row=self._row, column=1, columnspan=2, sticky="w", pady=3)
            self._fields[key] = m
            self._row += 1

        def toggle_field(label, key):
            ctk.CTkLabel(scroll, text=label, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(
                row=self._row, column=0, sticky="w", padx=(6, 16), pady=3)
            var = ctk.BooleanVar(value=bool(self.cfg.get(key, True)))
            sw = ctk.CTkSwitch(scroll, text="", variable=var,
                               onvalue=True, offvalue=False)
            sw.grid(row=self._row, column=1, sticky="w", pady=3)
            self._fields[key] = var
            self._row += 1

        section("IB Verbindung")
        field("Host",           "ib_host",    tip="Normalerweise 127.0.0.1 — nicht ändern")
        port_field("Port",      "ib_port")
        field("Account-Nummer", "ib_account", width=160,
              tip="z.B. DU1234567 (Paper) oder U1234567 (Live)")

        section("Risiko-Management")
        field("Max. gleichzeitige Positionen",  "max_positions",       tip="Empfohlen: 6–10")
        field("Max. Positionen pro Sektor",     "max_per_sector",      tip="Verhindert Klumpenrisiko (empfohlen: 2)")
        field("Min. Kapitalreserve ($)",         "min_available_funds", tip="Kein neuer Trade wenn Konto darunter fällt")

        section("Strategie")
        field("Min. Implied Volatility (IV)",   "min_vola",        tip="0.28 = 28%  — IV-Filter für genug Prämie")
        field("OTM-Abstand Short Strike",       "abstand_y",       tip="0.10 = 10% unter aktuellem Kurs")
        field("Min. Credit pro Kontrakt ($)",   "min_credit",      tip="Empfohlen: 70–100 $")
        field("Min. Risk/Reward Ratio",         "min_risk_reward", tip="0.20 = Prämie ≥ 20% des max. Risikos")
        field("Max. Delta Short-Put",           "max_delta",       tip="0.28 = Short-Put max. 28% Ausübungswahrsch.")
        field("Scan-Intervall (Sekunden)",      "scan_intervall",  tip="Alle X Sekunden neu scannen")

        section("Exit-Regeln")
        field("Take-Profit (%)",   "take_profit_pct", tip="0.50 = schließen wenn 50% des Credits verdient")
        field("Stop-Loss Faktor",  "stop_loss_mult",  tip="2.0 = schließen wenn Verlust = 2× Credit")
        field("DTE-Exit (Tage)",   "dte_exit",        tip="Schließen wenn ≤ X Tage bis Verfall (Gamma-Schutz)")

        section("Automation")
        toggle_field("Auto-Trade — Orders automatisch platzieren", "auto_trade")

        ctk.CTkButton(
            scroll, text="💾  Einstellungen speichern", height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._save_settings).grid(
            row=self._row, column=0, columnspan=3,
            sticky="w", padx=6, pady=(20, 4))
        self._row += 1

        self._save_lbl = ctk.CTkLabel(scroll, text="", text_color="#4ade80",
                                      font=ctk.CTkFont(size=12))
        self._save_lbl.grid(row=self._row, column=0, columnspan=3,
                            sticky="w", padx=6)

    # ── Guide tab ─────────────────────────────────────────────────────────────

    def _build_guide(self, parent):
        box = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(family="Courier", size=12),
            wrap="word", state="normal",
            fg_color=("#0f172a", "#0f172a"), text_color="#cbd5e1")
        box.pack(fill="both", expand=True, padx=6, pady=6)
        box.insert("1.0", IB_SETUP_TEXT)
        box.configure(state="disabled")

    # ── Auto-Updater ──────────────────────────────────────────────────────────

    def _check_for_updates(self):
        """Läuft im Hintergrund-Thread — prüft version.txt im GitHub-Repo."""
        if "DEIN_USERNAME" in UPDATE_BASE_URL:
            return  # URL noch nicht konfiguriert
        try:
            url = f"{UPDATE_BASE_URL}/version.txt"
            req = urllib.request.Request(url, headers={"User-Agent": "BotLauncher"})
            with urllib.request.urlopen(req, timeout=6) as r:
                remote = r.read().decode().strip()
            if remote != VERSION:
                self.after(0, lambda: self._show_update_banner(remote))
        except Exception:
            pass  # kein Internet oder Repo nicht erreichbar — still ignorieren

    def _show_update_banner(self, remote_version: str):
        """Blendet den Update-Banner im Hauptthread ein."""
        self._update_bar.configure(height=44)

        ctk.CTkLabel(
            self._update_bar,
            text=f"  📦  Update verfügbar:  v{remote_version}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#7dd3fc",
        ).pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            self._update_bar,
            text="Jetzt updaten",
            width=140, height=30,
            fg_color="#0369a1", hover_color="#075985",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._do_update(remote_version),
        ).pack(side="left", padx=4)

        ctk.CTkLabel(
            self._update_bar,
            text="(Bot wird kurz gestoppt — Neustart danach erforderlich)",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        ).pack(side="left", padx=10)

    def _do_update(self, remote_version: str):
        """Lädt neue Dateien herunter und ersetzt sie."""
        if self._running:
            self._stop_bot()

        # Button deaktivieren während Update läuft
        for w in self._update_bar.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(state="disabled", text="Lädt...")

        threading.Thread(
            target=self._download_update,
            args=(remote_version,),
            daemon=True,
        ).start()

    def _download_update(self, remote_version: str):
        errors = []

        # Normale Dateien direkt ersetzen
        for filename in UPDATE_FILES:
            try:
                url = f"{UPDATE_BASE_URL}/{filename}"
                req = urllib.request.Request(url, headers={"User-Agent": "BotLauncher"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    content = r.read()
                dest = os.path.join(_BASE, filename)
                # Backup anlegen
                if os.path.exists(dest):
                    shutil.copy2(dest, dest + ".bak")
                with open(dest, "wb") as f:
                    f.write(content)
            except Exception as e:
                errors.append(f"{filename}: {e}")

        # launcher.py → als .new speichern (wird beim nächsten Start aktiviert)
        try:
            url = f"{UPDATE_BASE_URL}/launcher.py"
            req = urllib.request.Request(url, headers={"User-Agent": "BotLauncher"})
            with urllib.request.urlopen(req, timeout=15) as r:
                content = r.read()
            new_path = os.path.join(_BASE, "launcher.py.new")
            with open(new_path, "wb") as f:
                f.write(content)
        except Exception as e:
            errors.append(f"launcher.py: {e}")

        self.after(0, lambda: self._update_done(remote_version, errors))

    def _update_done(self, remote_version: str, errors: list):
        # Banner neu beschriften
        for w in self._update_bar.winfo_children():
            w.destroy()

        if errors:
            msg = f"  ❌  Fehler beim Update: {errors[0]}"
            color = "#f87171"
        else:
            msg = f"  ✅  Update auf v{remote_version} abgeschlossen — bitte neu starten!"
            color = "#4ade80"

        ctk.CTkLabel(
            self._update_bar, text=msg,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=color,
        ).pack(side="left", padx=12, pady=8)

        if not errors:
            ctk.CTkButton(
                self._update_bar,
                text="Jetzt neu starten",
                width=160, height=30,
                fg_color="#166534", hover_color="#14532d",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=self._restart_app,
            ).pack(side="left", padx=4)

    def _restart_app(self):
        """Startet den Launcher neu — aktiviert launcher.py.new falls vorhanden."""
        self.on_closing()
        if platform.system() == "Windows":
            subprocess.Popen([sys.executable] + sys.argv)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── Bot-Steuerung ─────────────────────────────────────────────────────────

    def _save_settings(self):
        try:
            for key, widget in self._fields.items():
                if isinstance(widget, ctk.BooleanVar):
                    self.cfg[key] = widget.get()
                elif isinstance(widget, ctk.CTkOptionMenu):
                    self.cfg[key] = int(widget.get().split()[0])
                else:
                    raw = widget.get().strip()
                    if key in ("ib_host", "ib_account"):
                        self.cfg[key] = raw
                    elif key in ("max_positions", "max_per_sector",
                                 "min_available_funds", "scan_intervall",
                                 "dte_exit", "min_credit"):
                        self.cfg[key] = int(raw)
                    else:
                        self.cfg[key] = float(raw)
            save_config(self.cfg)
            self._save_lbl.configure(text="✅  Einstellungen gespeichert!", text_color="#4ade80")
            self.after(3000, lambda: self._save_lbl.configure(text=""))
        except ValueError as e:
            self._save_lbl.configure(text=f"❌  Fehler: {e}", text_color="#f87171")

    def _start_bot(self):
        if self._running:
            return
        if not self.cfg.get("ib_account", "").strip():
            self._log_append(
                "⚠  Bitte zuerst die Account-Nummer in den Einstellungen eintragen!\n"
                "   (Tab 'Einstellungen' → Account-Nummer → Speichern)\n\n")
            return
        save_config(self.cfg)
        self._running = True
        self._status_dot.configure(text="● LÄUFT", text_color="#4ade80")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Bot wird gestartet...\n")
        threading.Thread(target=self._run_subprocess, daemon=True).start()

    def _run_subprocess(self):
        try:
            self._proc = subprocess.Popen(
                [sys.executable, BOT_PATH],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=_BASE,
            )
            for line in self._proc.stdout:
                self._queue.put(line)
            self._proc.wait()
        except Exception as e:
            self._queue.put(f"❌  Start-Fehler: {e}\n")
        finally:
            self._queue.put(None)

    def _stop_bot(self):
        if not self._running or self._proc is None:
            return
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Stoppe Bot...\n")
        try:
            self._proc.terminate()
            self._proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._proc.kill()

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._on_bot_stopped()
                else:
                    self._log_append(item)
        except queue_module.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_bot_stopped(self):
        self._running = False
        self._proc = None
        self._status_dot.configure(text="● GESTOPPT", text_color="#f87171")
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Bot gestoppt.\n")

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def on_closing(self):
        if self._running:
            self._stop_bot()
        self.destroy()


if __name__ == "__main__":
    # Aktiviere pending launcher-Update (launcher.py.new → launcher.py)
    _new = os.path.join(_BASE, "launcher.py.new")
    if os.path.exists(_new):
        try:
            shutil.move(_new, __file__)
        except Exception:
            pass  # Wenn es fehlschlägt: altes launcher.py bleibt erhalten

    app = BotLauncher()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
