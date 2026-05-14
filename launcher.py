"""
Bull Put Spread Bot — GUI Launcher
"""
# ── Self-update Bootstrap (nur im frozen .app) ────────────────────────────────
# Prüft ob eine heruntergeladene launcher.py in Application Support liegt und
# führt diese aus statt der eingebackenen Version. Ermöglicht UI-Updates via
# GitHub ohne Schreibzugriff auf das (ggf. schreibgeschützte) .app-Bundle.
import os as _os, sys as _sys
if getattr(_sys, 'frozen', False) and '--bootstrap' not in _sys.argv:
    if _sys.platform == "darwin":
        _b = _os.path.join(_os.path.expanduser("~"), "Library",
                           "Application Support", "BullPutSpreadBot")
    elif _sys.platform == "win32":
        _b = _os.path.join(_os.environ.get("APPDATA", _os.path.expanduser("~")),
                           "BullPutSpreadBot")
    else:
        _b = _os.path.join(_os.path.expanduser("~"), ".local",
                           "share", "BullPutSpreadBot")
    _custom = _os.path.join(_b, "launcher.py")
    if _os.path.exists(_custom):
        _sys.argv.append('--bootstrap')
        with open(_custom, encoding='utf-8') as _lf:
            exec(compile(_lf.read(), _custom, 'exec'),
                 {'__file__': _custom, '__name__': '__main__', '__spec__': None})
        raise SystemExit(0)
# ─────────────────────────────────────────────────────────────────────────────

import customtkinter as ctk
import threading
import asyncio
import queue as queue_module
import json
import socket
import ssl
import subprocess
import sys
import os
import platform
import shutil
import urllib.request
from datetime import datetime, timedelta


def _ssl_context():
    """SSL-Kontext mit certifi-Zertifikaten. Fallback: unverified (nie crashen)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl._create_unverified_context()  # noqa: S501
        return ctx

# ── Pfade ─────────────────────────────────────────────────────────────────────
# _BASE       = beschreibbares Verzeichnis (Application Support / Quellordner)
# _BUNDLE_BASE = schreibgeschützter Bundle-Inhalt (nur im frozen .app)
if getattr(sys, 'frozen', False):
    _exec_dir = os.path.dirname(sys.executable)
    _resources = os.path.join(os.path.dirname(_exec_dir), "Resources")
    _BUNDLE_BASE = _resources if os.path.isdir(_resources) else _exec_dir

    if sys.platform == "darwin":
        _BASE = os.path.join(os.path.expanduser("~"), "Library",
                             "Application Support", "BullPutSpreadBot")
    elif sys.platform == "win32":
        _BASE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                             "BullPutSpreadBot")
    else:
        _BASE = os.path.join(os.path.expanduser("~"), ".local",
                             "share", "BullPutSpreadBot")
    os.makedirs(_BASE, exist_ok=True)
else:
    _BUNDLE_BASE = os.path.dirname(os.path.abspath(__file__))
    _BASE = _BUNDLE_BASE

CONFIG_PATH = os.path.join(_BASE, "config.json")
BOT_PATH    = os.path.join(_BASE, "bot.py")

# Version: AppSupport (heruntergeladen) hat Vorrang vor Bundle-Version
_ver_as  = os.path.join(_BASE, "version.txt")
_ver_bnd = os.path.join(_BUNDLE_BASE, "version.txt")
VERSION_FILE = _ver_as if os.path.exists(_ver_as) else _ver_bnd

# ── Version & Update-URL ─────────────────────────────────────────────────────
# Ersetze DEIN_USERNAME und DEIN_REPO mit deinen GitHub-Daten.
# Das Repo muss öffentlich sein ODER du verwendest einen Personal Access Token.
VERSION         = open(VERSION_FILE).read().strip() if os.path.exists(VERSION_FILE) else "1.0.0"
UPDATE_BASE_URL = "https://raw.githubusercontent.com/xTheRichiNOT/bull-put-spread-bot-releases/main"

# Alle Dateien die beim Auto-Update heruntergeladen werden (inkl. launcher.py)
UPDATE_FILES = ["bot.py", "launcher.py", "version.txt", "requirements.txt"]

# Changelog — pro Version eine Liste mit Änderungen (wird im Update-Dialog angezeigt)
CHANGELOG: dict[str, list[str]] = {
    "1.0.20": [
        "🆕  Portfolio-Tab: alle drei Bereiche per Mauziehen vergrößerbar/verkleinerbar",
        "🆕  Chart-Bereich standardmäßig größer als die Tabelle darunter",
        "✅  Chart passt sich automatisch an wenn Bereich gezogen wird",
    ],
    "1.0.19": [
        "✅  Credit und TP-Ziel in offenen Positionen jetzt als Gesamtbetrag ($92 statt $0.92)",
        "✅  Sidebar-Logo: Icon aus icon.png, 'SPREAD BOT' nicht mehr abgeschnitten",
    ],
    "1.0.18": [
        "🆕  Offene Positionen: neue Spalte 'Akt. P&L' zeigt unrealisierten Gewinn/Verlust",
        "✅  Zeitraum-Button 'Alle' umbenannt in 'Gesamt'",
        "✅  Breakeven-SL: Error 201 behoben (TP-Order wird jetzt zuerst storniert)",
        "✅  Marktöffnungszeit-Anzeige korrigiert (09:30 statt 09:29)",
    ],
    "1.0.17": [
        "🆕  P&L GESAMT Karte: Realisiert + Unrealisiert kombiniert mit Aufschlüsselung",
        "🆕  Bot rekonstruiert Spread-Details (Strikes, Credit) aus IB-Positionen beim Start",
        "🆕  Unrealisiertes P&L wird von Bot berechnet und alle 15s im Dashboard angezeigt",
        "✅  Positionen werden auch bei geschlossenem Markt in positions.json geschrieben",
        "✅  MARGIN GEBUNDEN Karte zeigt korrekte Werte auch für ältere Bot-Positionen",
    ],
    "1.0.16": [
        "🆕  Update-Dialog — bei neuem Update wird gefragt ob jetzt aktualisiert werden soll",
        "🆕  Option 'Immer automatisch updaten' im Update-Dialog (kein Dialog mehr)",
        "🆕  Einstellungen: Sicherer Modus — Haken sperrt alle Felder gegen Änderungen",
        "🆕  Einstellungen: 'Standardwerte zurücksetzen' Button",
    ],
    "1.0.15": [
        "🆕  Sidebar-Navigation (Dashboard / Portfolio / Einstellungen / IB-Setup)",
        "🆕  4 Metric-Cards: Broker-Status, Kapital, Positionen, Gesamt P&L",
        "🆕  Live Broker-Status in Sidebar (Verbunden / Getrennt / Verbinde...)",
        "🆕  Verfügbare Mittel werden direkt aus Bot-Log extrahiert und angezeigt",
        "✅  Bot-Status-Karte in Sidebar aktualisiert sich bei Start/Stop",
    ],
    "1.0.14": [
        "🆕  Live-Ticker: Offene Positionen mit DTE, Credit, TP-Ziel, Status",
        "🆕  Zeitraum-Filter: 1W / 1M / 3M / 6M / Alle",
        "🆕  Kumulativer P&L-Chart (Linie über Zeit)",
        "🆕  Stats: Gesamt P&L, Win-Rate, Ø P&L pro Trade, Gesamt seit Start",
        "🆕  Auto-Refresh alle 15 Sekunden während Bot läuft",
        "✅  bot.py schreibt jetzt nach Application Support (gleicher Pfad wie Launcher)",
        "✅  opened_at Timestamp bei neuen Trades",
    ],
    "1.0.13": [
        "🆕  Changelog-Fenster nach Updates (dieses Fenster)",
        "✅  Aktuell-Meldung bleibt 4 Sekunden sichtbar",
        "✅  SSL-Zertifikatsfehler behoben (certifi)",
        "✅  Updates in Application Support (keine Schreibrechtsprobleme mehr)",
        "✅  Config.json bleibt bei Updates erhalten",
        "✅  Fortschrittsbalken beim Download",
        "✅  TWS / IB Gateway Check vor Bot-Start",
    ],
}

# Prefs (getrennt von Config — bleiben bei Reset erhalten)
PREFS_PATH = os.path.join(_BASE, "prefs.json")

def _load_prefs() -> dict:
    try:
        with open(PREFS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_prefs(prefs: dict):
    try:
        with open(PREFS_PATH, "w") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass
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
    # Vorhandene Config in AppSupport laden
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    # Beim ersten Start: Bundle-Config migrieren falls vorhanden
    if _BASE != _BUNDLE_BASE:
        bundle_cfg = os.path.join(_BUNDLE_BASE, "config.json")
        if os.path.exists(bundle_cfg):
            try:
                with open(bundle_cfg) as f:
                    data = json.load(f)
                if data.get("ib_account", "").strip():
                    return {**DEFAULT_CONFIG, **data}
            except Exception:
                pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Design-System ─────────────────────────────────────────────────────────────
C = {
    "bg":        "#080d1a",   # tiefstes Hintergrund
    "surface":   "#0d1526",   # Panel/Card
    "surface2":  "#111e33",   # erhöhte Fläche
    "border":    "#1a2f50",   # subtile Rahmen
    "accent":    "#00c896",   # Cyan-Grün Akzent
    "accent2":   "#0ea5e9",   # Blau für Info
    "green":     "#22c55e",   # Aktiv / Profit
    "green2":    "#4ade80",   # Puls-Hell
    "red":       "#ef4444",   # Gestoppt / Verlust
    "amber":     "#f59e0b",   # Warnung
    "text":      "#e2e8f0",   # Primärtext
    "muted":     "#4a6080",   # Sekundärtext
    "header":    "#060b17",   # Header-Hintergrund
    "dim":       "#2d4a6b",   # Sehr gedämpft (leere Listen, Platzhalter)
}

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


class ChangelogDialog(ctk.CTkToplevel):
    """Zeigt nach einem Auto-Update die Änderungen der neuen Version an."""

    def __init__(self, parent: ctk.CTk, version: str, changes: list, on_done):
        super().__init__(parent)
        self.title(f"Update installiert — v{version}")
        self.geometry("500x380")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()
        self._on_done   = on_done
        self._no_more   = ctk.BooleanVar(value=False)
        self._build(version, changes)

    def _build(self, version: str, changes: list):
        # Header
        hdr = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color=C["header"])
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  ⬡  BULL PUT SPREAD BOT",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=12, pady=14)
        ctk.CTkLabel(hdr, text=f"v{version}  ",
                     font=ctk.CTkFont(size=12),
                     text_color=C["muted"]).pack(side="right", pady=14)

        # Titel
        ctk.CTkLabel(self, text="Was ist neu?",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["text"],
                     fg_color=C["surface2"]).pack(fill="x", padx=0, pady=0, ipady=8)

        # Änderungsliste
        scroll = ctk.CTkScrollableFrame(self, fg_color=C["surface"],
                                        corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        for line in changes:
            ctk.CTkLabel(scroll, text=f"  {line}",
                         font=ctk.CTkFont(size=12),
                         text_color=C["text"],
                         anchor="w").pack(fill="x", padx=8, pady=4)

        # Footer
        foot = ctk.CTkFrame(self, height=56, corner_radius=0,
                            fg_color=C["surface2"])
        foot.pack(fill="x")
        foot.pack_propagate(False)

        ctk.CTkCheckBox(foot, text="In Zukunft nicht mehr anzeigen",
                        variable=self._no_more,
                        font=ctk.CTkFont(size=11),
                        text_color=C["muted"],
                        fg_color=C["accent"], hover_color="#009e78",
                        checkmark_color="#000000").pack(side="left", padx=16, pady=16)

        ctk.CTkButton(foot, text="OK  ✓", width=110, height=34,
                      fg_color=C["accent"], hover_color="#009e78",
                      text_color="#000000",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._close).pack(side="right", padx=16, pady=10)

    def _close(self):
        self._on_done(self._no_more.get())
        self.destroy()


class UpdateDialog(ctk.CTkToplevel):
    """Fragt den Benutzer ob ein gefundenes Update installiert werden soll."""

    def __init__(self, parent: ctk.CTk, current_v: str, remote_v: str, on_result):
        """on_result(do_update: bool, always_auto: bool)"""
        super().__init__(parent)
        self.title("Update verfügbar")
        self.geometry("440x270")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()
        self._on_result   = on_result
        self._always_auto = ctk.BooleanVar(value=False)
        self._build(current_v, remote_v)

    def _build(self, current_v: str, remote_v: str):
        hdr = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color=C["header"])
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  ⬡  UPDATE VERFÜGBAR",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=12, pady=14)

        body = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0)
        body.pack(fill="both", expand=True)

        ctk.CTkLabel(body,
                     text=f"v{current_v}   →   v{remote_v}",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["accent"]).pack(pady=(22, 6))

        ctk.CTkLabel(body,
                     text="Eine neue Version ist verfügbar.\nMöchtest du jetzt updaten?",
                     font=ctk.CTkFont(size=12),
                     text_color=C["text"],
                     justify="center").pack(pady=(0, 16))

        ctk.CTkCheckBox(body,
                        text="Immer automatisch updaten (kein Dialog mehr)",
                        variable=self._always_auto,
                        font=ctk.CTkFont(size=11),
                        text_color=C["muted"],
                        fg_color=C["accent"], hover_color="#009e78",
                        checkmark_color="#000000").pack(pady=(0, 4))

        foot = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=C["surface2"])
        foot.pack(fill="x")
        foot.pack_propagate(False)

        ctk.CTkButton(foot, text="Später", width=100, height=34,
                      fg_color=C["surface"], hover_color=C["border"],
                      text_color=C["muted"],
                      font=ctk.CTkFont(size=12),
                      command=self._skip).pack(side="left", padx=16, pady=11)

        ctk.CTkButton(foot, text="Jetzt updaten  ↓", width=160, height=34,
                      fg_color=C["accent"], hover_color="#009e78",
                      text_color="#000000",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._do_update).pack(side="right", padx=16, pady=11)

    def _do_update(self):
        self._on_result(True, self._always_auto.get())
        self.destroy()

    def _skip(self):
        self._on_result(False, self._always_auto.get())
        self.destroy()


class SetupWizard(ctk.CTkToplevel):
    """Erststart-Wizard: führt den Kunden durch Platform / Software / Modus / Account."""

    # Port-Matrix: (software, trading_mode) → port
    _PORTS = {
        ("TWS",     "Paper"): 7497,
        ("TWS",     "Live"):  7496,
        ("Gateway", "Paper"): 4002,
        ("Gateway", "Live"):  4001,
    }

    def __init__(self, parent: ctk.CTk, cfg: dict, on_done):
        super().__init__(parent)
        self.title("Ersteinrichtung")
        self.geometry("560x480")
        self.resizable(False, False)
        self.grab_set()           # Modal — Hauptfenster blockiert
        self.lift()
        self.focus_force()

        self._cfg    = cfg
        self._done   = on_done
        self._step   = 0

        # Wizard-State
        self._platform  = ctk.StringVar(value="Desktop")
        self._software  = ctk.StringVar(value="TWS")
        self._mode      = ctk.StringVar(value="Paper")
        self._account   = ctk.StringVar(value=cfg.get("ib_account", ""))
        self._host      = ctk.StringVar(value=cfg.get("ib_host", "127.0.0.1"))

        self._build()

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, height=54, corner_radius=0,
                           fg_color=("#111827", "#111827"))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  Ersteinrichtung",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#38bdf8").pack(side="left", padx=8, pady=10)
        self._step_lbl = ctk.CTkLabel(hdr, text="Schritt 1 / 4",
                                      font=ctk.CTkFont(size=11),
                                      text_color="#64748b")
        self._step_lbl.pack(side="right", padx=16)

        # Content area
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=28, pady=10)

        # Navigation
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=28, pady=(0, 20))
        self._back_btn = ctk.CTkButton(nav, text="← Zurück", width=110, height=36,
                                       fg_color=("#374151", "#374151"),
                                       hover_color=("#4b5563", "#4b5563"),
                                       command=self._back)
        self._back_btn.pack(side="left")
        self._next_btn = ctk.CTkButton(nav, text="Weiter →", width=130, height=36,
                                       fg_color="#0369a1", hover_color="#075985",
                                       font=ctk.CTkFont(weight="bold"),
                                       command=self._next)
        self._next_btn.pack(side="right")

        self._show_step()

    def _clear_content(self):
        for w in self._content.winfo_children():
            w.destroy()

    def _show_step(self):
        self._clear_content()
        self._step_lbl.configure(text=f"Schritt {self._step + 1} / 4")
        self._back_btn.configure(state="normal" if self._step > 0 else "disabled")
        self._next_btn.configure(text="Fertig  ✓" if self._step == 3 else "Weiter →")

        steps = [self._step_platform, self._step_software,
                 self._step_mode,     self._step_account]
        steps[self._step]()

    # ── Step 1: Platform ──────────────────────────────────────────────────────
    def _step_platform(self):
        ctk.CTkLabel(self._content,
                     text="Wo läuft der Bot?",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(self._content,
                     text="Wähle aus wo IB Gateway / TWS installiert ist.",
                     text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 16))

        for val, title, desc in [
            ("Desktop",
             "Gleicher Computer  (Mac / Windows)",
             "Bot und TWS / IB Gateway laufen auf demselben Rechner.\nHost bleibt 127.0.0.1"),
            ("Server",
             "Externer Server  (Linux VPS / Strato)",
             "IB Gateway läuft auf einem anderen Rechner im Netzwerk.\nDu gibst die IP-Adresse des Servers ein."),
        ]:
            f = ctk.CTkFrame(self._content,
                             fg_color=("#1e293b", "#1e293b"),
                             corner_radius=8)
            f.pack(fill="x", pady=4)
            rb = ctk.CTkRadioButton(f, text=title, variable=self._platform, value=val,
                                    font=ctk.CTkFont(size=13, weight="bold"),
                                    command=self._show_step)
            rb.pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(f, text=desc, text_color="#64748b",
                         font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=32, pady=(0, 10))

        if self._platform.get() == "Server":
            ctk.CTkLabel(self._content, text="IP-Adresse des Servers:",
                         font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(12, 2))
            ctk.CTkEntry(self._content, textvariable=self._host,
                         width=200, placeholder_text="z.B. 192.168.1.10").pack(anchor="w")

    # ── Step 2: Software ──────────────────────────────────────────────────────
    def _step_software(self):
        ctk.CTkLabel(self._content,
                     text="Welche IB-Software verwendest du?",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(self._content,
                     text="Beide funktionieren mit dem Bot. IB Gateway empfohlen für Hintergrundbetrieb.",
                     text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 16))

        for val, title, desc in [
            ("TWS",
             "Trader Workstation  (TWS)",
             "Die vollständige Handelsplattform mit grafischer Oberfläche.\n"
             "Muss offen und eingeloggt bleiben."),
            ("Gateway",
             "IB Gateway  (empfohlen)",
             "Leichtgewichtige Version ohne große Oberfläche.\n"
             "Ideal für Hintergrundbetrieb — weniger RAM, kein großes Fenster."),
        ]:
            f = ctk.CTkFrame(self._content,
                             fg_color=("#1e293b", "#1e293b"),
                             corner_radius=8)
            f.pack(fill="x", pady=4)
            rb = ctk.CTkRadioButton(f, text=title, variable=self._software, value=val,
                                    font=ctk.CTkFont(size=13, weight="bold"))
            rb.pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(f, text=desc, text_color="#64748b",
                         font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=32, pady=(0, 10))

    # ── Step 3: Trading Mode ──────────────────────────────────────────────────
    def _step_mode(self):
        sw  = self._software.get()
        ctk.CTkLabel(self._content,
                     text="Paper Trading oder Live Trading?",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(self._content,
                     text="Paper Trading empfohlen zum Testen — kein echtes Geld.",
                     text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 16))

        for val, title, desc, color in [
            ("Paper",
             "Paper Trading  (Demokonto)",
             "Kostenloses Testkonto mit $1.000.000 Spielgeld.\n"
             f"Port: {self._PORTS[(sw, 'Paper')]}",
             "#166534"),
            ("Live",
             "Live Trading  (echtes Geld)",
             "Echte Orders mit echtem Kapital.\n"
             f"Port: {self._PORTS[(sw, 'Live')]}  ⚠️  Nur wenn du weißt was du tust!",
             "#7f1d1d"),
        ]:
            f = ctk.CTkFrame(self._content,
                             fg_color=("#1e293b", "#1e293b"),
                             corner_radius=8)
            f.pack(fill="x", pady=4)
            rb = ctk.CTkRadioButton(f, text=title, variable=self._mode, value=val,
                                    font=ctk.CTkFont(size=13, weight="bold"),
                                    fg_color=color)
            rb.pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(f, text=desc, text_color="#64748b",
                         font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=32, pady=(0, 10))

    # ── Step 4: Account ───────────────────────────────────────────────────────
    def _step_account(self):
        sw, mode = self._software.get(), self._mode.get()
        port = self._PORTS[(sw, mode)]
        prefix = "DU" if mode == "Paper" else "U"

        ctk.CTkLabel(self._content,
                     text="Deine IB Account-Nummer",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(8, 4))

        # Summary box
        summary = (f"  Software:  {sw}   |   Modus: {mode} Trading   |   Port: {port}\n"
                   f"  Host:  {self._host.get()}")
        sf = ctk.CTkFrame(self._content, fg_color=("#0f172a", "#0f172a"), corner_radius=6)
        sf.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(sf, text=summary, font=ctk.CTkFont(family="Courier", size=11),
                     text_color="#38bdf8", justify="left").pack(padx=12, pady=8)

        ctk.CTkLabel(self._content,
                     text=f"Account-Nummer  ({prefix}xxxxxxx):",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(4, 2))
        e = ctk.CTkEntry(self._content, textvariable=self._account,
                         width=200, font=ctk.CTkFont(size=13),
                         placeholder_text=f"{prefix}1234567")
        e.pack(anchor="w")
        e.focus()

        ctk.CTkLabel(self._content,
                     text=f"In TWS/{sw} findest du sie oben rechts neben deinem Namen.",
                     text_color="#64748b", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(6, 0))

        self._err_lbl = ctk.CTkLabel(self._content, text="",
                                     text_color="#f87171", font=ctk.CTkFont(size=12))
        self._err_lbl.pack(anchor="w", pady=(4, 0))

    # ── Navigation ────────────────────────────────────────────────────────────
    def _back(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _next(self):
        if self._step == 3:
            self._finish()
        else:
            self._step += 1
            self._show_step()

    def _finish(self):
        acct = self._account.get().strip()
        if not acct:
            self._err_lbl.configure(text="⚠  Bitte Account-Nummer eingeben.")
            return

        sw, mode = self._software.get(), self._mode.get()
        self._cfg["ib_account"] = acct
        self._cfg["ib_host"]    = self._host.get().strip() or "127.0.0.1"
        self._cfg["ib_port"]    = self._PORTS[(sw, mode)]
        save_config(self._cfg)

        self._done()
        self.destroy()


class BotLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Bull Put Spread Bot  v{VERSION}")
        self.geometry("960x740")
        self.minsize(820, 620)

        self.cfg           = load_config()
        self._stop_event   = None
        self._bot_thread   = None
        self._queue        = queue_module.Queue()
        self._running      = False
        self._start_time   = None   # für Uptime-Counter
        self._pulse_state  = False

        self.configure(fg_color=C["bg"])
        self._set_icon()
        self._build_ui()
        self._poll_queue()

        # Erststart-Wizard wenn noch keine Account-Nummer gesetzt
        if not self.cfg.get("ib_account", "").strip():
            self.after(200, self._show_wizard)
        else:
            # Check for updates silently in background
            threading.Thread(target=self._check_for_updates, daemon=True).start()

        # Changelog nach Update anzeigen (nur einmal pro Version)
        self.after(600, self._maybe_show_changelog)

    def _set_icon(self):
        try:
            from PIL import Image, ImageTk
            path = os.path.join(_BASE, "icons", "icon.png")
            img  = Image.open(path).resize((256, 256), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.wm_iconphoto(True, photo)
            self._icon_ref = photo          # prevent GC
            if sys.platform == "darwin":
                try:
                    import AppKit  # type: ignore[import-untyped]
                    ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(path)
                    AppKit.NSApp.setApplicationIconImage_(ns_img)
                except Exception:
                    pass
        except Exception:
            pass

    def _show_wizard(self):
        SetupWizard(self, self.cfg, on_done=self._wizard_done)

    def _wizard_done(self):
        """Wird aufgerufen wenn Wizard abgeschlossen — Config neu laden + Update prüfen."""
        self.cfg = load_config()
        # Settings-Felder aktualisieren
        for key, widget in getattr(self, "_fields", {}).items():
            if isinstance(widget, ctk.BooleanVar):
                widget.set(bool(self.cfg.get(key, True)))
            elif not isinstance(widget, ctk.CTkOptionMenu):
                widget.delete(0, "end")
                widget.insert(0, str(self.cfg.get(key, "")))
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _maybe_show_changelog(self):
        """Zeigt Changelog einmal nach Update — respektiert 'nicht mehr anzeigen'."""
        prefs = _load_prefs()
        if prefs.get("skip_changelog"):
            return
        last = prefs.get("last_shown_version")
        if last is None:
            # Erstinstallation — Version still setzen, kein Dialog
            prefs["last_shown_version"] = VERSION
            _save_prefs(prefs)
            return
        if last == VERSION:
            return  # Schon für diese Version angezeigt
        changes = CHANGELOG.get(VERSION)
        if not changes:
            # Keine Einträge → Version trotzdem markieren
            prefs["last_shown_version"] = VERSION
            _save_prefs(prefs)
            return
        self._show_changelog(VERSION, changes)

    def _show_changelog(self, version: str, changes: list):
        def on_done(skip_future: bool):
            prefs = _load_prefs()
            prefs["last_shown_version"] = VERSION
            if skip_future:
                prefs["skip_changelog"] = True
            _save_prefs(prefs)
        ChangelogDialog(self, version, changes, on_done)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Accent-Linie (ganz oben) ──────────────────────────────────────────
        ctk.CTkFrame(self, height=3, corner_radius=0,
                     fg_color=C["accent"]).pack(fill="x")

        # ── Update-Banner (versteckt bis Update gefunden) ─────────────────────
        self._update_bar = ctk.CTkFrame(self, height=0, corner_radius=0,
                                        fg_color=("#0c2340", "#0c2340"))
        self._update_bar.pack(fill="x")
        self._update_bar.pack_propagate(False)

        # ── Haupt-Layout: Sidebar links, Content rechts ───────────────────────
        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.pack(fill="both", expand=True)

        # ── SIDEBAR ───────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(main, width=200, corner_radius=0,
                          fg_color=C["header"])
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Logo
        logo = ctk.CTkFrame(sb, fg_color="transparent", height=82)
        logo.pack(fill="x", pady=(0, 4))
        logo.pack_propagate(False)

        # Icon: echtes icon.png laden (Fallback: Text-Symbol)
        _icon_lbl_kwargs: dict = {"text": "⬡",
                                  "font": ctk.CTkFont(size=26),
                                  "text_color": C["accent"]}
        try:
            from PIL import Image
            _icon_path = os.path.join(_BASE, "icons", "icon.png")
            if not os.path.exists(_icon_path):
                _icon_path = os.path.join(_BUNDLE_BASE, "icons", "icon.png")
            if os.path.exists(_icon_path):
                _img = ctk.CTkImage(
                    light_image=Image.open(_icon_path),
                    dark_image=Image.open(_icon_path),
                    size=(38, 38))
                _icon_lbl_kwargs = {"text": "", "image": _img}
        except Exception:
            pass
        ctk.CTkLabel(logo, **_icon_lbl_kwargs).pack(side="left", padx=(12, 8), pady=20)

        ttl = ctk.CTkFrame(logo, fg_color="transparent")
        ttl.pack(side="left", pady=18)
        ctk.CTkLabel(ttl, text="BULL PUT",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(ttl, text="SPREAD BOT",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["accent"]).pack(anchor="w")

        ctk.CTkFrame(sb, height=1, corner_radius=0,
                     fg_color=C["border"]).pack(fill="x", padx=12, pady=(0, 8))

        # Bot-Status-Karte
        self._sb_status_card = ctk.CTkFrame(sb, fg_color=C["surface2"],
                                             corner_radius=10)
        self._sb_status_card.pack(fill="x", padx=12, pady=(0, 10))
        self._sb_bot_lbl = ctk.CTkLabel(
            self._sb_status_card,
            text="⏹  BOT GESTOPPT",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=C["red"])
        self._sb_bot_lbl.pack(pady=(8, 2))
        self._uptime_lbl = ctk.CTkLabel(
            self._sb_status_card, text="",
            font=ctk.CTkFont(family="Courier", size=10),
            text_color=C["muted"])
        self._uptime_lbl.pack(pady=(0, 8))

        # Broker-Status-Karte
        self._sb_broker_card = ctk.CTkFrame(sb, fg_color=C["surface2"],
                                             corner_radius=10)
        self._sb_broker_card.pack(fill="x", padx=12, pady=(0, 12))
        self._sb_broker_lbl = ctk.CTkLabel(
            self._sb_broker_card,
            text="⚫  Broker: —",
            font=ctk.CTkFont(size=11),
            text_color=C["muted"])
        self._sb_broker_lbl.pack(pady=(8, 2))
        self._sb_funds_lbl = ctk.CTkLabel(
            self._sb_broker_card, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["text"])
        self._sb_funds_lbl.pack(pady=(0, 8))

        ctk.CTkFrame(sb, height=1, corner_radius=0,
                     fg_color=C["border"]).pack(fill="x", padx=12, pady=(0, 8))

        # Navigation
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("  📊   Dashboard",  "dashboard"),
            ("  📁   Portfolio",  "history"),
            ("  ⚙️   Einstellungen", "settings"),
            ("  📖   IB-Setup",   "guide"),
        ]
        for label, key in nav_items:
            btn = ctk.CTkButton(
                sb, text=label, height=42, anchor="w",
                font=ctk.CTkFont(size=13),
                fg_color="transparent", hover_color=C["surface2"],
                text_color=C["muted"], corner_radius=8,
                command=lambda k=key: self._show_page(k))
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = btn

        # Version am Seitenleisten-Fuß
        ctk.CTkLabel(sb, text=f"v{VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color=C["border"]).pack(side="bottom", pady=10)

        # ── CONTENT-BEREICH ───────────────────────────────────────────────────
        content = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        content.pack(side="left", fill="both", expand=True)

        for key in ["dashboard", "history", "settings", "guide"]:
            f = ctk.CTkFrame(content, fg_color=C["surface"], corner_radius=0)
            self._pages[key] = f

        self._build_dashboard(self._pages["dashboard"])
        self._build_history(self._pages["history"])
        self._build_settings(self._pages["settings"])
        self._build_guide(self._pages["guide"])

        # Status-dot Compat (bleibt für interne Logik)
        self._status_dot = self._sb_bot_lbl

        self._show_page("dashboard")

    def _show_page(self, key: str):
        for k, frame in self._pages.items():
            frame.pack_forget()
        self._pages[key].pack(fill="both", expand=True)
        for k, btn in self._nav_btns.items():
            active = k == key
            btn.configure(
                fg_color=C["surface2"] if active else "transparent",
                text_color=C["accent"] if active else C["muted"],
                font=ctk.CTkFont(size=13, weight="bold" if active else "normal"))

    # ── Dashboard tab ────────────────────────────────────────────────────────

    def _build_dashboard(self, parent):
        parent.configure(fg_color=C["surface"])

        # ── Metric Cards ──────────────────────────────────────────────────────
        cards_row = ctk.CTkFrame(parent, fg_color="transparent")
        cards_row.pack(fill="x", padx=10, pady=(10, 6))

        def make_card(parent, title, icon, sub=False):
            card = ctk.CTkFrame(parent, fg_color=C["surface2"], corner_radius=10)
            card.pack(side="left", fill="both", expand=True, padx=4)
            ctk.CTkLabel(card, text=f"{icon}  {title}",
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            val_lbl = ctk.CTkLabel(card, text="—",
                                   font=ctk.CTkFont(size=16, weight="bold"),
                                   text_color=C["text"])
            val_lbl.pack(anchor="w", padx=10, pady=(2, 0 if sub else 8))
            if sub:
                sub_lbl = ctk.CTkLabel(card, text="",
                                       font=ctk.CTkFont(size=9),
                                       text_color=C["muted"])
                sub_lbl.pack(anchor="w", padx=10, pady=(0, 8))
                return val_lbl, sub_lbl
            return val_lbl

        self._card_broker  = make_card(cards_row, "BROKER",          "🔌")
        self._card_funds   = make_card(cards_row, "MARGIN GEBUNDEN", "💰")
        self._card_pos     = make_card(cards_row, "POSITIONEN",      "📋")
        self._card_pnl, self._card_pnl_sub = make_card(
            cards_row, "P&L GESAMT", "📈", sub=True)

        # ── Steuerleiste ──────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(parent, fg_color=C["surface2"], corner_radius=10)
        ctrl.pack(fill="x", padx=10, pady=(0, 6))

        btn_area = ctk.CTkFrame(ctrl, fg_color="transparent")
        btn_area.pack(side="left", padx=12, pady=10)

        self._start_btn = ctk.CTkButton(
            btn_area, text="▶  STARTEN", width=160, height=44,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"], hover_color="#009e78",
            text_color="#000000",
            corner_radius=8,
            command=self._start_bot)
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            btn_area, text="⏹  STOPPEN", width=140, height=44,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["surface"], hover_color=C["border"],
            text_color=C["red"], border_width=1, border_color=C["red"],
            corner_radius=8,
            state="disabled", command=self._stop_bot)
        self._stop_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_area, text="⌫  Log", width=80, height=44,
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"], hover_color=C["border"],
            text_color=C["muted"], corner_radius=8,
            command=self._clear_log).pack(side="left")

        # ── Log-Bereich ───────────────────────────────────────────────────────
        log_header = ctk.CTkFrame(parent, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(log_header, text="▸ LIVE LOG",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(side="left")
        self._log_count_lbl = ctk.CTkLabel(log_header, text="",
                     font=ctk.CTkFont(family="Courier", size=10),
                     text_color=C["muted"])
        self._log_count_lbl.pack(side="right")

        self._log = ctk.CTkTextbox(
            parent,
            font=ctk.CTkFont(family="Courier", size=12),
            state="disabled", wrap="word",
            fg_color=C["bg"],
            text_color="#7ca4c0",
            corner_radius=8,
            border_width=1,
            border_color=C["border"])
        self._log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Farb-Tags für den Log (via tkinter-Unterlage)
        tb = self._log._textbox
        tb.tag_configure("green",  foreground="#22c55e")
        tb.tag_configure("red",    foreground="#ef4444")
        tb.tag_configure("amber",  foreground="#f59e0b")
        tb.tag_configure("cyan",   foreground="#00c896")
        tb.tag_configure("blue",   foreground="#60a5fa")
        tb.tag_configure("dim",    foreground="#2d4a6b")
        tb.tag_configure("white",  foreground="#e2e8f0")
        self._log_lines = 0

    # ── History tab ──────────────────────────────────────────────────────────

    def _build_history(self, parent):
        import tkinter as tk
        parent.configure(fg_color=C["surface"])
        self._current_period = "Gesamt"
        self._period_btn_refs: dict[str, ctk.CTkButton] = {}

        # ── PanedWindow: alle drei Bereiche per Maus verschiebbar ────────────
        self._portfolio_paned = tk.PanedWindow(
            parent, orient=tk.VERTICAL,
            bg=C["border"], sashwidth=6, sashrelief="flat",
            sashpad=0, bd=0, showhandle=False)
        self._portfolio_paned.pack(fill="both", expand=True)

        # ── Pane 1: Offene Positionen ─────────────────────────────────────────
        pane_pos = tk.Frame(self._portfolio_paned, bg=C["bg"])
        self._portfolio_paned.add(pane_pos, minsize=80)

        pos_bar = ctk.CTkFrame(pane_pos, fg_color=C["surface2"], corner_radius=8)
        pos_bar.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(pos_bar, text="  OFFENE POSITIONEN",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=6, pady=6)
        self._pos_time_lbl = ctk.CTkLabel(pos_bar, text="",
                                           font=ctk.CTkFont(size=10),
                                           text_color=C["muted"])
        self._pos_time_lbl.pack(side="right", padx=10)

        pos_cols = ctk.CTkFrame(pane_pos, fg_color=C["header"], corner_radius=0)
        pos_cols.pack(fill="x", padx=10, pady=(2, 0))
        for col, w in [("Symbol", 70), ("Expiry", 90), ("DTE", 45),
                       ("Short", 65), ("Long", 65),
                       ("Credit", 70), ("TP-Ziel", 70), ("Akt. P&L", 80), ("Status", 80)]:
            ctk.CTkLabel(pos_cols, text=col, width=w,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["muted"]).pack(side="left", padx=3, pady=4)

        self._pos_scroll = ctk.CTkScrollableFrame(
            pane_pos, fg_color=C["bg"], corner_radius=0,
            border_width=1, border_color=C["border"])
        self._pos_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # ── Pane 2: Performance + Chart ───────────────────────────────────────
        pane_chart = tk.Frame(self._portfolio_paned, bg=C["bg"])
        self._portfolio_paned.add(pane_chart, minsize=100)

        perf = ctk.CTkFrame(pane_chart, fg_color=C["surface2"], corner_radius=8)
        perf.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        period_row = ctk.CTkFrame(perf, fg_color="transparent")
        period_row.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(period_row, text="Zeitraum:",
                     font=ctk.CTkFont(size=11),
                     text_color=C["muted"]).pack(side="left", padx=(0, 8))

        for label in ["1W", "1M", "3M", "6M", "Gesamt"]:
            active = label == "Gesamt"
            btn = ctk.CTkButton(
                period_row, text=label, width=46, height=26,
                fg_color=C["accent"] if active else C["surface"],
                hover_color="#009e78" if active else C["border"],
                text_color="#000000" if active else C["text"],
                font=ctk.CTkFont(size=11),
                command=lambda l=label: self._set_period(l))
            btn.pack(side="left", padx=2)
            self._period_btn_refs[label] = btn

        ctk.CTkButton(period_row, text="↻", width=30, height=26,
                      fg_color=C["surface"], hover_color=C["border"],
                      text_color=C["muted"],
                      command=self._refresh_history).pack(side="right", padx=4)

        stats_row = ctk.CTkFrame(perf, fg_color="transparent")
        stats_row.pack(fill="x", padx=10, pady=(0, 4))
        self._lbl_total    = ctk.CTkLabel(stats_row, text="Gesamt: —",
                                           font=ctk.CTkFont(size=13, weight="bold"),
                                           text_color=C["text"])
        self._lbl_total.pack(side="left", padx=(0, 18))
        self._lbl_trades   = ctk.CTkLabel(stats_row, text="0 Trades",
                                           font=ctk.CTkFont(size=11),
                                           text_color=C["muted"])
        self._lbl_trades.pack(side="left", padx=(0, 18))
        self._lbl_winrate  = ctk.CTkLabel(stats_row, text="Win: —",
                                           font=ctk.CTkFont(size=11),
                                           text_color=C["muted"])
        self._lbl_winrate.pack(side="left", padx=(0, 18))
        self._lbl_avg      = ctk.CTkLabel(stats_row, text="⌀ P&L: —",
                                           font=ctk.CTkFont(size=11),
                                           text_color=C["muted"])
        self._lbl_avg.pack(side="left")

        self._chart_canvas = tk.Canvas(perf, bg=C["bg"], highlightthickness=0)
        self._chart_canvas.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self._chart_canvas.bind("<Configure>", lambda e: self._draw_chart(
            getattr(self, '_last_chart_trades', [])))

        # ── Pane 3: Trade-Tabelle ─────────────────────────────────────────────
        pane_hist = tk.Frame(self._portfolio_paned, bg=C["bg"])
        self._portfolio_paned.add(pane_hist, minsize=60)

        hist_hdr = ctk.CTkFrame(pane_hist, fg_color=C["surface2"], corner_radius=0)
        hist_hdr.pack(fill="x", padx=10, pady=(0, 0))
        for col, w in [("Datum", 130), ("Symbol", 70), ("Expiry", 90),
                       ("Short", 65), ("Long", 65),
                       ("Credit", 70), ("Exit", 70), ("P&L", 75), ("Status", 70)]:
            ctk.CTkLabel(hist_hdr, text=col, width=w,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["accent"]).pack(side="left", padx=3, pady=6)

        self._history_scroll = ctk.CTkScrollableFrame(
            pane_hist, fg_color=C["bg"], corner_radius=0,
            border_width=1, border_color=C["border"])
        self._history_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Initiale Sash-Positionen: Positionen 22%, Chart 43%, Tabelle 35%
        def _init_sash():
            h = self._portfolio_paned.winfo_height()
            if h > 50:
                self._portfolio_paned.sash_place(0, 0, int(h * 0.22))
                self._portfolio_paned.sash_place(1, 0, int(h * 0.65))
            else:
                self.after(100, _init_sash)
        self.after(300, _init_sash)

        self._refresh_history()
        self._refresh_positions()
        self._auto_refresh_history()

    # ── Hilfsmethode: Trades nach Zeitraum filtern ────────────────────────────

    def _filter_trades_by_period(self, trades: list) -> list:
        if self._current_period == "Gesamt":
            return trades
        days = {"1W": 7, "1M": 30, "3M": 90, "6M": 180}.get(self._current_period, 0)
        cutoff = datetime.now() - timedelta(days=days)
        result = []
        for t in trades:
            try:
                closed = datetime.strptime(t.get("closed_at", ""), "%Y-%m-%d %H:%M")
                if closed >= cutoff:
                    result.append(t)
            except Exception:
                pass
        return result

    def _set_period(self, period: str):
        self._current_period = period
        for label, btn in self._period_btn_refs.items():
            active = label == period
            btn.configure(
                fg_color=C["accent"] if active else C["surface"],
                hover_color="#009e78" if active else C["border"],
                text_color="#000000" if active else C["text"])
        self._refresh_history()

    # ── P&L-Chart auf Canvas zeichnen ─────────────────────────────────────────

    def _draw_chart(self, trades: list):
        import tkinter as tk
        self._last_chart_trades = trades
        c = self._chart_canvas
        c.update_idletasks()
        w = c.winfo_width() or 500
        h = c.winfo_height() or 95
        c.delete("all")

        if not trades:
            c.create_text(w // 2, h // 2, text="Keine Trades im Zeitraum",
                          fill=C["dim"], font=("Courier", 10))
            return

        sorted_t = sorted(trades, key=lambda t: t.get("closed_at", ""))
        cumulative, running = [], 0.0
        for t in sorted_t:
            running += t.get("pnl", 0)
            cumulative.append(running)

        if len(cumulative) < 1:
            return

        pad = 28
        cw, ch = w - 2 * pad, h - 16
        max_abs = max(abs(v) for v in cumulative) or 1
        zero_y = pad // 2 + ch * max_abs / (2 * max_abs)

        def to_xy(i, val):
            x = pad + (i / max(len(cumulative) - 1, 1)) * cw
            y = (h - pad // 2) - ((val + max_abs) / (2 * max_abs)) * ch
            return x, y

        # Nulllinie
        c.create_line(pad, zero_y, w - pad, zero_y,
                      fill=C["border"], width=1, dash=(4, 4))

        # Linie + Füllfläche
        pts = [to_xy(i, v) for i, v in enumerate(cumulative)]
        if len(pts) >= 2:
            flat = [coord for p in pts for coord in p]
            c.create_line(flat, fill=C["accent"], width=2, smooth=True)

        # Punkte
        for i, (x, y) in enumerate(pts):
            col = "#22c55e" if cumulative[i] >= 0 else "#ef4444"
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=col, outline="")

        # Endwert-Label
        final = cumulative[-1]
        sign = "+" if final >= 0 else ""
        col = "#4ade80" if final >= 0 else "#ef4444"
        c.create_text(w - pad + 2, pts[-1][1],
                      text=f"{sign}${final:,.0f}",
                      fill=col, font=("Courier", 9), anchor="w")

        # Gesamt seit Anfang (alle Trades, nicht nur Filter)
        history_file = os.path.join(_BASE, "trade_history.json")
        try:
            with open(history_file) as f:
                all_trades = json.load(f)
            total_all = sum(t.get("pnl", 0) for t in all_trades)
            sign_all = "+" if total_all >= 0 else ""
            c.create_text(pad, 8,
                          text=f"Gesamt seit Start: {sign_all}${total_all:,.0f}",
                          fill=C["muted"], font=("Courier", 9), anchor="w")
        except Exception:
            pass

    # ── Live-Positionen aktualisieren ─────────────────────────────────────────

    def _refresh_positions(self):
        for w in self._pos_scroll.winfo_children():
            w.destroy()

        pos_file = os.path.join(_BASE, "positions.json")
        positions, updated = [], ""
        if os.path.exists(pos_file):
            try:
                with open(pos_file) as f:
                    data = json.load(f)
                positions = data.get("positions", [])
                updated   = data.get("updated", "")
            except Exception:
                pass

        if updated:
            self._pos_time_lbl.configure(text=f"Stand: {updated}  ")

        # ── Metric-Karten aus positions.json befüllen ─────────────────────────
        open_pos = [p for p in positions if p.get("status") != "done"]
        self._card_pos.configure(
            text=str(len(open_pos)) if open_pos else "0",
            text_color=C["accent"] if open_pos else C["muted"])

        margin_used = sum(
            max(0, (p.get("short_strike", 0) - p.get("long_strike", 0)
                    - p.get("entry_per_share", 0))) * 100
            for p in open_pos)
        if open_pos:
            self._card_funds.configure(
                text=f"${margin_used:,.0f}",
                text_color=C["amber"])
        else:
            self._card_funds.configure(text="$0", text_color=C["muted"])

        # Unrealized P&L aus positions.json (vom Bot in monitor_exits berechnet)
        upnl_vals = [p.get("unrealized_pnl") for p in open_pos if p.get("unrealized_pnl") is not None]
        self._unrealized_pnl  = sum(upnl_vals)
        self._has_unrealized  = len(upnl_vals) > 0

        def lbl(parent, text, width, color=C["text"]):
            ctk.CTkLabel(parent, text=text, width=width,
                         font=ctk.CTkFont(size=11), text_color=color,
                         anchor="w").pack(side="left", padx=3, pady=4)

        if not positions:
            ctk.CTkLabel(self._pos_scroll,
                         text="  Keine offenen Positionen.",
                         text_color=C["dim"],
                         font=ctk.CTkFont(size=12)).pack(pady=16)
            return

        for p in positions:
            status = p.get("status", "open")
            row_col = "#0d2416" if status == "open" else "#1a1a08"
            row = ctk.CTkFrame(self._pos_scroll, fg_color=row_col, corner_radius=5)
            row.pack(fill="x", padx=4, pady=2)
            lbl(row, p.get("symbol", "–"), 70, C["accent"])
            lbl(row, p.get("expiry", "–"), 90)
            dte = p.get("dte", 0)
            dte_col = "#ef4444" if dte <= 7 else ("#f59e0b" if dte <= 21 else C["text"])
            lbl(row, f"{dte}d", 45, dte_col)
            lbl(row, f"${p.get('short_strike', 0):.0f}", 65)
            lbl(row, f"${p.get('long_strike', 0):.0f}", 65)
            lbl(row, f"${p.get('entry_per_share', 0)*100:.0f}", 70, "#4ade80")
            lbl(row, f"${p.get('tp_target', 0)*100:.0f}", 70, "#60a5fa")
            upnl = p.get("unrealized_pnl")
            if upnl is not None:
                upnl_col = "#4ade80" if upnl >= 0 else "#ef4444"
                upnl_txt = f"{'+'if upnl>=0 else ''}${upnl:,.0f}"
            else:
                upnl_col, upnl_txt = C["dim"], "—"
            lbl(row, upnl_txt, 80, upnl_col)
            status_col = "#4ade80" if status == "open" else "#f59e0b"
            status_txt = "Aktiv" if status == "open" else "Schließt"
            lbl(row, status_txt, 80, status_col)

    # ── Trade-History aktualisieren ───────────────────────────────────────────

    def _refresh_history(self):
        for w in self._history_scroll.winfo_children():
            w.destroy()

        history_file = os.path.join(_BASE, "trade_history.json")
        all_trades = []
        if os.path.exists(history_file):
            try:
                with open(history_file) as f:
                    all_trades = json.load(f)
            except Exception:
                pass

        trades = self._filter_trades_by_period(all_trades)

        # Stats aktualisieren
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        avg_pnl = (total_pnl / len(trades)) if trades else 0
        pnl_col = "#4ade80" if total_pnl >= 0 else "#ef4444"
        sign = "+" if total_pnl >= 0 else ""

        self._lbl_total.configure(
            text=f"Gesamt: {sign}${total_pnl:,.0f}", text_color=pnl_col)
        self._lbl_trades.configure(text=f"{len(trades)} Trades")
        self._lbl_winrate.configure(
            text=f"Win: {win_rate:.0f}%" if trades else "Win: —")
        self._lbl_avg.configure(
            text=f"⌀ ${avg_pnl:+.0f}" if trades else "⌀ P&L: —")

        self._draw_chart(trades)

        # P&L-Card: Realisiert (history.json) + Unrealisiert (positions.json)
        total_real   = sum(t.get("pnl", 0) for t in all_trades)
        unrealized   = getattr(self, '_unrealized_pnl', 0.0)
        has_unreal   = getattr(self, '_has_unrealized', False)
        total_combined = total_real + unrealized

        sign_c = "+" if total_combined >= 0 else ""
        col_c  = "#4ade80" if total_combined >= 0 else "#ef4444"
        self._card_pnl.configure(
            text=f"{sign_c}${total_combined:,.0f}",
            text_color=col_c)

        if has_unreal:
            sign_r = "+" if total_real >= 0 else ""
            sign_u = "+" if unrealized >= 0 else ""
            self._card_pnl_sub.configure(
                text=f"Real: {sign_r}${total_real:,.0f}  |  Offen: {sign_u}${unrealized:,.0f}",
                text_color=C["muted"])
        else:
            sign_r = "+" if total_real >= 0 else ""
            self._card_pnl_sub.configure(
                text=f"Real: {sign_r}${total_real:,.0f}  |  Offen: —",
                text_color=C["muted"])

        if not trades:
            ctk.CTkLabel(self._history_scroll,
                         text="Keine abgeschlossenen Trades im gewählten Zeitraum.",
                         text_color=C["dim"],
                         font=ctk.CTkFont(size=12)).pack(pady=24)
            return

        def lbl(parent, text, width, color=C["text"]):
            ctk.CTkLabel(parent, text=text, width=width,
                         font=ctk.CTkFont(size=11), text_color=color,
                         anchor="w").pack(side="left", padx=3, pady=5)

        for t in reversed(trades):
            pnl = t.get("pnl", 0)
            row_col = "#0d2b1a" if pnl > 0 else ("#2b0d0d" if pnl < 0 else C["surface2"])
            row = ctk.CTkFrame(self._history_scroll, fg_color=row_col, corner_radius=5)
            row.pack(fill="x", padx=4, pady=2)
            lbl(row, t.get("closed_at", "–"), 130)
            lbl(row, t.get("symbol", "–"), 70, C["accent"])
            lbl(row, t.get("expiry", "–"), 90)
            lbl(row, f"${t.get('short_strike', 0):.0f}", 65)
            lbl(row, f"${t.get('long_strike', 0):.0f}", 65)
            lbl(row, f"${t.get('entry_per_share', 0):.2f}", 70, "#4ade80")
            lbl(row, f"${t.get('exit_per_share', 0):.2f}", 70, "#f87171")
            pnl_str = f"{'+'if pnl>=0 else ''}${pnl:,.0f}"
            lbl(row, pnl_str, 75, "#4ade80" if pnl >= 0 else "#ef4444")
            status = t.get("status", "–")
            lbl(row, status, 70, "#4ade80" if status == "done" else "#f59e0b")

    # ── Auto-Refresh alle 15s ─────────────────────────────────────────────────

    def _auto_refresh_history(self):
        try:
            self._refresh_positions()
            self._refresh_history()
        except Exception:
            pass
        self.after(15000, self._auto_refresh_history)

    # ── Settings tab ─────────────────────────────────────────────────────────

    def _build_settings(self, parent):
        parent.configure(fg_color=C["surface"])

        # ── Sicherer-Modus Header ─────────────────────────────────────────────
        self._safe_mode_var = ctk.BooleanVar(value=True)   # default: gesperrt
        self._input_widgets: list = []

        safe_bar = ctk.CTkFrame(parent, fg_color=C["surface2"],
                                corner_radius=0, height=44)
        safe_bar.pack(fill="x")
        safe_bar.pack_propagate(False)

        self._safe_mode_lbl = ctk.CTkLabel(
            safe_bar,
            text="🔒  Sicherer Modus — Einstellungen gesperrt",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["amber"])
        self._safe_mode_lbl.pack(side="left", padx=14)

        ctk.CTkCheckBox(safe_bar, text="Sicherer Modus",
                        variable=self._safe_mode_var,
                        font=ctk.CTkFont(size=11),
                        text_color=C["muted"],
                        fg_color=C["amber"], hover_color="#b45309",
                        checkmark_color="#000000",
                        command=self._apply_safe_mode).pack(side="right", padx=16)

        # ── Scroll-Bereich ────────────────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(parent, fg_color=C["surface"])
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        scroll.columnconfigure(0, weight=0)
        scroll.columnconfigure(1, weight=0)
        scroll.columnconfigure(2, weight=1)
        self._settings_scroll = scroll   # ref für scroll-binding

        self._fields = {}
        self._row = 0

        def section(title):
            if self._row > 0:
                ctk.CTkFrame(scroll, height=1, fg_color=C["border"]).grid(
                    row=self._row, column=0, columnspan=3,
                    sticky="ew", padx=4, pady=(14, 0))
                self._row += 1
            lbl = ctk.CTkLabel(scroll, text=f"  {title}",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["accent"], anchor="w",
                         fg_color=C["surface2"], corner_radius=4)
            lbl.grid(row=self._row, column=0, columnspan=3,
                     sticky="ew", pady=(10, 6), padx=0, ipady=4)
            self._row += 1

        def field(label, key, width=130, tip=""):
            ctk.CTkLabel(scroll, text=label, anchor="w",
                         font=ctk.CTkFont(size=12),
                         text_color=C["text"]).grid(
                row=self._row, column=0, sticky="w", padx=(10, 16), pady=3)
            e = ctk.CTkEntry(scroll, width=width,
                             font=ctk.CTkFont(family="Courier", size=12),
                             fg_color=C["bg"], border_color=C["border"],
                             text_color=C["text"])
            e.insert(0, str(self.cfg.get(key, "")))
            e.grid(row=self._row, column=1, sticky="w", pady=3)
            if tip:
                ctk.CTkLabel(scroll, text=tip, text_color=C["muted"],
                             font=ctk.CTkFont(size=11), anchor="w").grid(
                    row=self._row, column=2, sticky="w", padx=10)
            self._fields[key] = e
            self._input_widgets.append(e)
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
            self._input_widgets.append(m)
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
            self._input_widgets.append(sw)
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

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.grid(row=self._row, column=0, columnspan=3,
                     sticky="w", padx=6, pady=(20, 4))
        self._row += 1

        self._save_btn = ctk.CTkButton(
            btn_row, text="  SPEICHERN  ", height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"], hover_color="#009e78",
            text_color="#000000", corner_radius=8,
            command=self._save_settings)
        self._save_btn.pack(side="left", padx=(0, 8))
        self._input_widgets.append(self._save_btn)

        self._reset_btn = ctk.CTkButton(
            btn_row, text="↩  Standardwerte", height=42,
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"], hover_color=C["border"],
            text_color=C["muted"], corner_radius=8,
            command=self._reset_to_defaults)
        self._reset_btn.pack(side="left")
        self._input_widgets.append(self._reset_btn)

        self._save_lbl = ctk.CTkLabel(scroll, text="",
                                      font=ctk.CTkFont(size=12))
        self._save_lbl.grid(row=self._row, column=0, columnspan=3,
                            sticky="w", padx=6)

        # Initialen Zustand (gesperrt) anwenden und Scroll-Events binden
        self.after(50, self._apply_safe_mode)
        self.after(100, self._bind_settings_scroll)

    def _bind_settings_scroll(self):
        """Bindet Mausrad-Events an alle Kind-Widgets der Settings-ScrollFrame (macOS fix)."""
        try:
            canvas = self._settings_scroll._parent_canvas

            def _on_scroll(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

            def _bind_recursive(w):
                w.bind("<MouseWheel>", _on_scroll, add="+")
                for child in w.winfo_children():
                    _bind_recursive(child)

            _bind_recursive(self._settings_scroll)
        except Exception:
            pass

    # ── Guide tab ─────────────────────────────────────────────────────────────

    def _build_guide(self, parent):
        parent.configure(fg_color=C["surface"])
        box = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(family="Courier", size=12),
            wrap="word", state="normal",
            fg_color=C["bg"], text_color="#7ca4c0",
            corner_radius=8, border_width=1, border_color=C["border"])
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", IB_SETUP_TEXT)
        box.configure(state="disabled")

    # ── Auto-Updater ──────────────────────────────────────────────────────────

    def _update_bar_set(self, text: str, color: str, progress: float = -1):
        """Zeigt Text im Update-Banner. progress 0–1 zeigt Fortschrittsbalken."""
        for w in self._update_bar.winfo_children():
            w.destroy()
        self._update_bar.configure(height=36)
        ctk.CTkLabel(
            self._update_bar, text=text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=color,
        ).pack(side="left", padx=14, pady=6)
        if 0 <= progress <= 1:
            pb = ctk.CTkProgressBar(self._update_bar, width=180, height=8,
                                    progress_color=color,
                                    fg_color=C["surface2"])
            pb.set(progress)
            pb.pack(side="left", padx=(0, 12), pady=14)

    def _update_bar_hide(self):
        """Blendet den Update-Banner aus."""
        for w in self._update_bar.winfo_children():
            w.destroy()
        self._update_bar.configure(height=0)

    def _check_for_updates(self):
        """Hintergrund-Thread: prüft GitHub auf neue Version."""
        if "DEIN_USERNAME" in UPDATE_BASE_URL:
            return
        try:
            self.after(0, lambda: self._update_bar_set(
                "  🔄  Prüfe auf Updates...", "#7dd3fc"))

            req = urllib.request.Request(
                f"{UPDATE_BASE_URL}/version.txt",
                headers={"User-Agent": "BotLauncher"})
            with urllib.request.urlopen(req, timeout=8, context=_ssl_context()) as r:
                remote = r.read().decode().strip()

            if remote == VERSION:
                self.after(0, lambda: self._update_bar_set(
                    f"  ✅  v{VERSION} — Aktuell", "#4ade80"))
                self.after(4000, lambda: self.after(0, self._update_bar_hide))
                return

            # Update gefunden — auto-download oder Dialog?
            prefs = _load_prefs()
            if prefs.get("auto_update"):
                self._download_update(remote)   # bereits im BG-Thread
            else:
                self.after(0, lambda r=remote: self._show_update_dialog(r))

        except Exception as e:
            err_str = str(e)
            self.after(0, lambda: self._update_bar_set(
                f"  ❌  Update-Prüfung fehlgeschlagen: {err_str}", "#f87171"))
            self.after(10000, lambda: self.after(0, self._update_bar_hide))

    def _show_update_dialog(self, remote: str):
        """Zeigt Update-Dialog (Main-Thread). Startet Download wenn bestätigt."""
        self._update_bar_hide()

        def on_result(do_update: bool, always_auto: bool):
            if always_auto:
                prefs = _load_prefs()
                prefs["auto_update"] = True
                _save_prefs(prefs)
            if do_update:
                threading.Thread(
                    target=self._download_update, args=(remote,), daemon=True).start()

        UpdateDialog(self, VERSION, remote, on_result)

    def _download_update(self, remote: str):
        """Lädt Update-Dateien herunter (Hintergrund-Thread)."""
        errors = []
        total = len(UPDATE_FILES)
        for idx, filename in enumerate(UPDATE_FILES):
            prog = idx / total
            self.after(0, lambda t=f"  ⬇️  Update v{remote}  ({filename})", p=prog:
                       self._update_bar_set(t, "#7dd3fc", progress=p))
            try:
                r2 = urllib.request.Request(
                    f"{UPDATE_BASE_URL}/{filename}",
                    headers={"User-Agent": "BotLauncher"})
                with urllib.request.urlopen(r2, timeout=15, context=_ssl_context()) as resp:
                    content = resp.read()
                dest = os.path.join(_BASE, filename)
                if os.path.exists(dest):
                    shutil.copy2(dest, dest + ".bak")
                with open(dest, "wb") as f:
                    f.write(content)
                if sys.platform == "darwin":
                    try:
                        subprocess.run(
                            ["xattr", "-d", "com.apple.quarantine", dest],
                            capture_output=True, check=False)
                    except Exception:
                        pass
            except Exception as e:
                errors.append(f"{filename}: {e}")

        if errors:
            err_msg = errors[0]
            self.after(0, lambda: self._update_bar_set(
                f"  ❌  Download fehlgeschlagen: {err_msg}", "#f87171"))
            self.after(10000, lambda: self.after(0, self._update_bar_hide))
        else:
            self.after(0, lambda: self._update_bar_set(
                f"  ✅  Update v{remote} installiert — startet neu...",
                "#4ade80", progress=1.0))
            self.after(2500, lambda: self.after(0, self._restart_app))

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

    def _apply_safe_mode(self):
        """Sperrt oder entsperrt alle Einstellungsfelder."""
        locked = self._safe_mode_var.get()
        state  = "disabled" if locked else "normal"
        for w in self._input_widgets:
            try:
                w.configure(state=state)
                # CTkEntry explizit ausgrauen (customtkinter zeigt sonst weißen Text)
                if isinstance(w, ctk.CTkEntry):
                    w.configure(text_color=C["muted"] if locked else C["text"],
                                border_color=C["border"] if locked else C["border"])
            except Exception:
                pass
        if locked:
            self._safe_mode_lbl.configure(
                text="🔒  Sicherer Modus — Einstellungen gesperrt",
                text_color=C["amber"])
        else:
            self._safe_mode_lbl.configure(
                text="🔓  Einstellungen bearbeitbar",
                text_color=C["green"])
        # Scroll-Bindings nach Zustandswechsel erneuern
        self.after(50, self._bind_settings_scroll)

    def _reset_to_defaults(self):
        """Füllt alle Einstellungsfelder mit Standardwerten (ohne Speichern)."""
        _port_options = [
            "7497  (TWS Paper Trading)",
            "7496  (TWS Live Trading)",
            "4002  (IB Gateway Paper)",
            "4001  (IB Gateway Live)",
        ]
        for key, widget in self._fields.items():
            val = DEFAULT_CONFIG.get(key)
            if val is None:
                continue
            if isinstance(widget, ctk.BooleanVar):
                widget.set(bool(val))
            elif isinstance(widget, ctk.CTkOptionMenu):
                default = next(
                    (o for o in _port_options if o.startswith(str(val))),
                    _port_options[0])
                widget.set(default)
            else:
                widget.delete(0, "end")
                widget.insert(0, str(val))
        self._save_lbl.configure(
            text="↩  Standardwerte geladen — klicke SPEICHERN zum Übernehmen",
            text_color=C["amber"])
        self.after(4000, lambda: self._save_lbl.configure(text=""))

    def _check_tws(self) -> bool:
        """Prüft ob TWS / IB Gateway auf dem konfigurierten Port erreichbar ist."""
        host = self.cfg.get("ib_host", "127.0.0.1")
        port = int(self.cfg.get("ib_port", 7497))
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def _start_bot(self):
        if self._running:
            return
        if not self.cfg.get("ib_account", "").strip():
            self._log_append(
                "⚠  Bitte zuerst die Account-Nummer in den Einstellungen eintragen!\n"
                "   (Tab 'Einstellungen' → Account-Nummer → Speichern)\n\n")
            return
        port = self.cfg.get("ib_port", 7497)
        host = self.cfg.get("ib_host", "127.0.0.1")
        if not self._check_tws():
            self._log_append(
                f"⚠  TWS / IB Gateway nicht gefunden auf {host}:{port}\n"
                f"   → Bitte TWS starten, einloggen und API aktivieren.\n"
                f"   → Dann Bot erneut starten.\n\n")
            return
        save_config(self.cfg)
        self._running     = True
        self._start_time  = datetime.now()
        self._status_dot.configure(text="⬤  BOT LÄUFT", text_color=C["green"])
        self._sb_broker_lbl.configure(text="🟡  Broker: Verbinde...",
                                       text_color=C["amber"])
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(
            state="normal", text_color=C["red"],
            border_color=C["red"])
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Bot wird gestartet...\n")
        self._stop_event = threading.Event()
        self._bot_thread = threading.Thread(target=self._run_bot_thread, daemon=True)
        self._bot_thread.start()
        self._pulse()
        self._tick_uptime()

    def _run_bot_thread(self):
        try:
            # Priorität: AppSupport (heruntergeladen) → Bundle (eingebaut) → Import
            bot_file = os.path.join(_BASE, "bot.py")
            if not os.path.exists(bot_file) and _BASE != _BUNDLE_BASE:
                bot_file = os.path.join(_BUNDLE_BASE, "bot.py")
            if os.path.exists(bot_file):
                import importlib.util
                spec = importlib.util.spec_from_file_location("bot", bot_file)
                _bot = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_bot)
            else:
                import bot as _bot
            _bot._log_queue = self._queue
            asyncio.run(_bot.run_bot(self._stop_event))
        except Exception as e:
            self._queue.put(f"❌  Bot-Fehler: {e}\n")
        finally:
            self._queue.put(None)

    def _stop_bot(self):
        if not self._running or self._stop_event is None:
            return
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Stoppe Bot...\n")
        self._stop_event.set()

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._on_bot_stopped()
                else:
                    self._log_append(item)
                    self._parse_status(item)
        except queue_module.Empty:
            pass
        self.after(100, self._poll_queue)

    def _parse_status(self, text: str):
        """Live-Status aus Log-Meldungen extrahieren und Karten aktualisieren."""
        import re
        # Broker-Verbindung
        tl = text.lower()
        if any(k in tl for k in ("verbunden", "connected", "ib-verbindung hergestellt")):
            self._sb_broker_lbl.configure(text="🟢  Broker: Verbunden",
                                           text_color=C["green"])
            self._card_broker.configure(text="Verbunden", text_color=C["green"])
        elif any(k in tl for k in ("getrennt", "disconnect", "timeout auf port",
                                   "connection refused")):
            self._sb_broker_lbl.configure(text="🔴  Broker: Getrennt",
                                           text_color=C["red"])
            self._card_broker.configure(text="Getrennt", text_color=C["red"])
        # Verfügbare Mittel → nur Sidebar-Label (Karten werden aus positions.json befüllt)
        m = re.search(r'Verfügbare Mittel:\s*\$([\d,]+)', text)
        if m:
            self._sb_funds_lbl.configure(text=f"${m.group(1)}")

    def _pulse(self):
        if not self._running:
            return
        self._pulse_state = not self._pulse_state
        color = C["green2"] if self._pulse_state else C["green"]
        self._status_dot.configure(text_color=color)
        self.after(700, self._pulse)

    def _tick_uptime(self):
        if not self._running or self._start_time is None:
            self._uptime_lbl.configure(text="")
            return
        delta = datetime.now() - self._start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s   = divmod(rem, 60)
        self._uptime_lbl.configure(text=f"⏱ {h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._tick_uptime)

    def _on_bot_stopped(self):
        self._running     = False
        self._start_time  = None
        self._stop_event  = None
        self._bot_thread  = None
        self._status_dot.configure(text="⏹  BOT GESTOPPT", text_color=C["red"])
        self._sb_broker_lbl.configure(text="⚫  Broker: —", text_color=C["muted"])
        self._sb_funds_lbl.configure(text="")
        self._card_broker.configure(text="—", text_color=C["muted"])
        self._uptime_lbl.configure(text="")
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._log_append(f"[{datetime.now():%H:%M:%S}]  Bot gestoppt.\n")

    # Log-Zeile analysieren und passende Farbe wählen
    _LOG_TAGS = [
        (["✅", "Bracket-Order", "Fill", "geschlossen", "TRADE"], "green"),
        (["❌", "FEHLER", "fehlgeschlagen", "KRITISCHER"], "red"),
        (["⚠️", "⚠", "BLOCKIERT", "Timeout", "übersprungen"], "amber"),
        (["🔔", "TRIGGER", "ZYKLUS", "═"], "cyan"),
        (["🚀", "Trade:", "Score"], "blue"),
        (["─", "Scan abgeschlossen", "Pause"], "dim"),
    ]

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        tb = self._log._textbox
        tag = None
        for keywords, t in self._LOG_TAGS:
            if any(kw in text for kw in keywords):
                tag = t
                break
        if tag:
            tb.insert("end", text, tag)
        else:
            tb.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")
        self._log_lines += text.count("\n")
        if self._log_lines > 0:
            self._log_count_lbl.configure(text=f"{self._log_lines} Zeilen")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._log_lines = 0
        self._log_count_lbl.configure(text="")

    def _restart_app(self):
        """Startet die App neu — lädt dabei ggf. die neue launcher.py."""
        if self._running:
            self._stop_bot()
        try:
            import subprocess
            subprocess.Popen([sys.executable] + [a for a in sys.argv if a != '--bootstrap'])
        except Exception:
            pass
        self.destroy()

    def on_closing(self):
        if self._running:
            dlg = ctk.CTkToplevel(self)
            dlg.title("Bot aktiv")
            dlg.geometry("380x140")
            dlg.resizable(False, False)
            dlg.configure(fg_color=C["surface"])
            dlg.grab_set()
            dlg.lift()
            ctk.CTkLabel(
                dlg,
                text="⚠️  Der Bot läuft noch.\nWirklich beenden?",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=C["amber"],
            ).pack(pady=(24, 12))
            btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
            btn_frame.pack()
            def _confirm():
                dlg.destroy()
                self._stop_bot()
                if self._bot_thread and self._bot_thread.is_alive():
                    self._bot_thread.join(timeout=5)
                self.destroy()
            ctk.CTkButton(btn_frame, text="Ja, beenden", width=140, height=34,
                          fg_color="#dc2626", hover_color="#b91c1c",
                          command=_confirm).pack(side="left", padx=8)
            ctk.CTkButton(btn_frame, text="Abbrechen", width=140, height=34,
                          fg_color=C["surface2"], hover_color=C["header"],
                          command=dlg.destroy).pack(side="left", padx=8)
        else:
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
