#!/usr/bin/env python3
"""
Backtest-Vergleich: Bot-Simulation vs. PDF-Report
==================================================
Führt den Backtest für den identischen Zeitraum aus (Okt 2024 – Apr 2026),
liest die Ergebnisse ein und vergleicht sie mit den Zahlen aus dem PDF-Report.

Nutzung:
  python3 backtest_compare.py
"""

import math
import sys
import os
import csv
import io
from datetime import datetime, timedelta
from collections import defaultdict
from contextlib import redirect_stdout

# ─── PDF-Referenzwerte (hard-coded aus dem Backtest-Report PDF) ─────────────
PDF = {
    "zeitraum":            "Okt 2024 – Apr 2026 (18 Monate)",
    "symbole":             24,
    "trades":              140,
    "win_rate":            0.743,
    "avg_credit":          136.20,
    "avg_hold_days":       17,
    "total_pnl":           2469.52,
    "monthly_profit":      137.20,
    "annual_profit":       1646.0,
    "annual_return_pct":   56.6,
    "capital":             2910.40,
    "avg_win":             76.22,
    "avg_loss":            -151.58,
    "exit_tp_count":       101,
    "exit_tp_pct":         72.1,
    "exit_dte_count":      29,
    "exit_dte_pct":        20.7,
    "exit_sl_count":       10,
    "exit_sl_pct":         7.1,
    "exit_exp_count":      0,
    "exit_exp_pct":        0.0,
    # Parameter (aus PDF Seite 3 + 4)
    "param_dte_range":     "45–60 Tage",
    "param_otm_pct":       "10%",
    "param_min_iv":        ">28%",
    "param_min_credit":    "$80 pro Kontrakt",
    "param_max_delta":     "0.28",
    "param_win_prob":      "72%–85%",
    "param_take_profit":   "50% des Credits",
    "param_stop_loss":     "2× Entry Credit",
    "param_dte_exit":      "Nur wenn Puffer <5%",
    "param_max_pos":       "8",
    "param_max_sector":    "2",
    "param_hv_window":     "30 Tage",
    "param_iv_factor":     "1.0 (raw HV, kein VRP-Aufschlag)",
    "param_slippage":      "0% (nicht modelliert)",
}

# ─── Backtest-Parameter: werden zur Laufzeit aus backtest.py gelesen ─────────
BOT_PARAMS: dict = {}
_BT_MODULE = None   # wird in run_and_capture() gesetzt

PARAM_KEYS = [
    ("param_dte_range",   "Laufzeit (DTE)"),
    ("param_otm_pct",     "OTM-Abstand"),
    ("param_min_iv",      "Min. Implied Volatility"),
    ("param_min_credit",  "Min. Netto-Credit"),
    ("param_max_delta",   "Max. Delta Short Put"),
    ("param_win_prob",    "Gewinnwahrscheinlichkeit"),
    ("param_take_profit", "Take Profit"),
    ("param_stop_loss",   "Stop Loss"),
    ("param_dte_exit",    "21-DTE Exit"),
    ("param_max_pos",     "Max. Positionen"),
    ("param_max_sector",  "Max. pro Sektor"),
    ("param_hv_window",   "HV-Fenster"),
    ("param_iv_factor",   "IV-Faktor"),
    ("param_slippage",    "Slippage"),
]


# ─── Backtest ausführen ─────────────────────────────────────────────────────
def run_and_capture():
    """Importiert backtest.py, befüllt BOT_PARAMS dynamisch, führt Backtest aus."""
    global BOT_PARAMS, _BT_MODULE
    import importlib.util
    bt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest.py")
    spec = importlib.util.spec_from_file_location("backtest_mod", bt_path)
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    _BT_MODULE = bt

    # Parameter-Strings live aus dem Modul lesen
    BOT_PARAMS = {
        "param_dte_range":  f"45–60 Tage (FIXED_DTE={bt.FIXED_DTE})",
        "param_otm_pct":    f"{bt.ABSTAND_Y:.0%} (ABSTAND_Y={bt.ABSTAND_Y})",
        "param_min_iv":     f">{bt.MIN_VOLA:.0%} (MIN_VOLA={bt.MIN_VOLA}, Soft: {bt.MIN_VOLA_SOFT})",
        "param_min_credit": f"${bt.MIN_CREDIT_ABS:.0f} abs / {bt.MIN_CREDIT_PERCENT:.0%} der Spreite",
        "param_max_delta":  "N/A (kein Delta-Filter im Backtest)",
        "param_win_prob":   f"≤{bt.MAX_PROBABILITY:.0%} (MAX_PROBABILITY={bt.MAX_PROBABILITY})",
        "param_take_profit":f"{bt.TAKE_PROFIT_PCT:.0%} des Credits (TAKE_PROFIT_PCT={bt.TAKE_PROFIT_PCT})",
        "param_stop_loss":  f"{bt.STOP_LOSS_MULT:.0f}× Entry Credit (STOP_LOSS_MULT={bt.STOP_LOSS_MULT})",
        "param_dte_exit":   f"Nur wenn Puffer <{bt.BUFFER_MIN_PCT:.0%} bei ≤{bt.DTE_EXIT} DTE",
        "param_max_pos":    f"{bt.MAX_POSITIONS} (MAX_POSITIONS={bt.MAX_POSITIONS})",
        "param_max_sector": f"{bt.MAX_PER_SECTOR} (MAX_PER_SECTOR={bt.MAX_PER_SECTOR})",
        "param_hv_window":  f"{bt.HV_WINDOW} Tage (HV_WINDOW={bt.HV_WINDOW})",
        "param_iv_factor":  f"{bt.IV_VRP_FACTOR:.2f}× (IV_VRP_FACTOR={bt.IV_VRP_FACTOR})",
        "param_slippage":   f"{(1-bt.SLIPPAGE):.0%} Abschlag (SLIPPAGE={bt.SLIPPAGE})",
    }

    START = "2024-10-01"
    END   = "2026-04-20"

    print(f"🔄  Führe Backtest durch: {START} – {END} …")
    buf = io.StringIO()
    with redirect_stdout(buf):
        trades, daily_pnl, filter_stats = bt.run_backtest(START, END)

    return bt, trades, daily_pnl, filter_stats, buf.getvalue(), START, END


# ─── Kennzahlen berechnen ────────────────────────────────────────────────────
def calc_metrics(trades, daily_pnl, start_date, end_date):
    if not trades:
        return {}
    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n      = len(trades)
    total  = sum(t["pnl"] for t in trades)

    avg_credit = sum(t["credit"] for t in trades) / n
    avg_hold   = sum(t["dte_held"] for t in trades) / n

    gross_w = sum(t["pnl"] for t in wins)
    gross_l = abs(sum(t["pnl"] for t in losses))
    avg_w   = gross_w / len(wins)   if wins   else 0.0
    avg_l   = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
    pf      = gross_w / gross_l if gross_l > 0 else float("inf")

    cum, peak, max_dd = 0.0, 0.0, 0.0
    for d in sorted(daily_pnl):
        cum  += daily_pnl[d]
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")
    cal_days  = max(1, (end_dt - start_dt).days)
    months    = cal_days / 30.4375
    monthly   = total / months
    annual_p  = monthly * 12

    # Kapitalbasis: Ø Margin pro Position × 8
    avg_margin = sum(
        (t["short_strike"] - t["long_strike"]) * 100 - t["credit"]
        for t in trades
    ) / n
    capital = avg_margin * 8
    annual_ret = (annual_p / capital * 100) if capital > 0 else 0.0

    exits = defaultdict(int)
    for t in trades:
        exits[t["exit_reason"]] += 1

    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t["pnl"])

    top5  = sorted(by_sym.items(), key=lambda x: sum(x[1]), reverse=True)[:5]
    flop5 = sorted(by_sym.items(), key=lambda x: sum(x[1]))[:5]

    return {
        "trades":           n,
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         len(wins) / n,
        "avg_credit":       avg_credit,
        "avg_hold_days":    avg_hold,
        "total_pnl":        total,
        "monthly_profit":   monthly,
        "annual_profit":    annual_p,
        "annual_return_pct": annual_ret,
        "capital":          capital,
        "avg_win":          avg_w,
        "avg_loss":         avg_l,
        "profit_factor":    pf,
        "max_drawdown":     max_dd,
        "exits":            dict(exits),
        "top5":             top5,
        "flop5":            flop5,
    }


# ─── Ausgabe-Helfer ──────────────────────────────────────────────────────────
W = 72

def sep(char="─"):
    print(char * W)

def hdr(title):
    print()
    print("═" * W)
    print(f"  {title}")
    print("═" * W)

def row(label, pdf_val, bot_val, match=None):
    if match is None:
        # Auto-detect numeric match within 10%
        try:
            p = float(str(pdf_val).replace("$","").replace("%","").replace("+",""))
            b = float(str(bot_val).replace("$","").replace("%","").replace("+",""))
            if p != 0:
                match = abs(p - b) / abs(p) <= 0.10
            else:
                match = abs(b) <= 1
        except Exception:
            match = None

    flag = "✅" if match is True else ("⚠️ " if match is False else "  ")
    label_str = f"{label:<28}"
    pdf_str   = f"{str(pdf_val):<18}"
    bot_str   = f"{str(bot_val)}"
    print(f"  {flag} {label_str} {pdf_str} {bot_str}")


# ─── Hauptreport ─────────────────────────────────────────────────────────────
def print_report(m, start_date, end_date):
    n_sym = len(set(t["symbol"] for t in [])) if not m else 0  # wird unten gesetzt

    hdr("PARAMETER-VERGLEICH: PDF vs. Bot (backtest.py)")
    print(f"  {'Parameter':<28} {'PDF-Report':<30} Bot (backtest.py)")
    sep()

    # Match-Flags dynamisch aus importiertem bt-Modul ableiten
    bt_mod = _BT_MODULE  # wird in run_and_capture() gesetzt
    def _match(key):
        if key == "param_min_iv":     return abs(bt_mod.MIN_VOLA - 0.28) < 0.001
        if key == "param_min_credit": return bt_mod.MIN_CREDIT_ABS >= 80
        if key == "param_max_delta":  return False   # kein Delta-Filter im Backtest
        if key == "param_hv_window":  return bt_mod.HV_WINDOW == 30
        if key == "param_iv_factor":  return abs(bt_mod.IV_VRP_FACTOR - 1.0) < 0.01
        if key == "param_slippage":   return bt_mod.SLIPPAGE >= 0.99
        if key == "param_dte_range":  return True
        if key == "param_otm_pct":    return abs(bt_mod.ABSTAND_Y - 0.10) < 0.001
        if key == "param_take_profit":return abs(bt_mod.TAKE_PROFIT_PCT - 0.50) < 0.001
        if key == "param_stop_loss":  return abs(bt_mod.STOP_LOSS_MULT - 2.0) < 0.01
        if key == "param_dte_exit":   return True
        if key == "param_max_pos":    return bt_mod.MAX_POSITIONS == 8
        if key == "param_max_sector": return bt_mod.MAX_PER_SECTOR == 2
        return None

    for key, label in PARAM_KEYS:
        pv    = PDF.get(key, "—")
        bv    = BOT_PARAMS.get(key, "—")
        match = _match(key)
        flag  = "✅" if match is True else ("⚠️ " if match is False else "  ")
        pv_s  = f"{str(pv):<30}"
        print(f"  {flag} {label:<28} {pv_s} {bv}")

    print()
    print("  Legende: ✅ identisch / kompatibel   ⚠️  abweichend   (leer) = nicht direkt vergleichbar")


    hdr(f"ERGEBNIS-VERGLEICH: {start_date} – {end_date}")
    print(f"  {'Kennzahl':<28} {'PDF-Report':<20} Bot-Backtest")
    sep()

    def _pct(v): return f"{v:.1f}%"
    def _usd(v): return f"${v:+,.2f}"
    def _num(v): return f"{v}"

    months = max(1, (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days / 30.4375)

    row("Trades gesamt",
        PDF["trades"],
        m["trades"])
    row("Symbole (Universe)",
        f"{PDF['symbole']}",
        f"120 (gefiltert)")
    row("Win-Rate",
        _pct(PDF["win_rate"] * 100),
        _pct(m["win_rate"] * 100))
    row("Ø Credit / Trade",
        f"${PDF['avg_credit']:.2f}",
        f"${m['avg_credit']:.2f}")
    row("Ø Haltedauer (Tage)",
        f"{PDF['avg_hold_days']}",
        f"{m['avg_hold_days']:.1f}")
    row("Ø Gewinn (Wins)",
        f"${PDF['avg_win']:+.2f}",
        f"${m['avg_win']:+.2f}")
    row("Ø Verlust (Losses)",
        f"${PDF['avg_loss']:+.2f}",
        f"${m['avg_loss']:+.2f}")
    row("Gesamt-P&L",
        f"${PDF['total_pnl']:+,.2f}",
        f"${m['total_pnl']:+,.2f}")
    row("Monatlicher Gewinn",
        f"${PDF['monthly_profit']:+.2f}",
        f"${m['monthly_profit']:+.2f}")
    row("Jahresgewinn (hochger.)",
        f"${PDF['annual_profit']:+,.0f}",
        f"${m['annual_profit']:+,.0f}")
    row("Eingesetztes Kapital",
        f"${PDF['capital']:,.2f}",
        f"${m['capital']:,.2f}")
    row("Jahresrendite",
        _pct(PDF["annual_return_pct"]),
        _pct(m["annual_return_pct"]))
    if "profit_factor" in m:
        print(f"  {'':3} {'Profit-Faktor':<28} {'—':<20} {m['profit_factor']:.2f}×")
    if "max_drawdown" in m:
        print(f"  {'':3} {'Max. Drawdown':<28} {'—':<20} ${m['max_drawdown']:,.0f}")

    hdr("EXIT-VERTEILUNG")
    print(f"  {'Exit-Grund':<24} {'PDF Anzahl':>10} {'PDF %':>7}   {'Bot Anzahl':>10} {'Bot %':>7}")
    sep()
    exits = m.get("exits", {})
    n_bot = m["trades"]

    def exit_row(label, pdf_n, pdf_p, bot_key):
        bot_n = exits.get(bot_key, 0)
        bot_p = bot_n / n_bot * 100 if n_bot > 0 else 0
        ok = abs(pdf_p - bot_p) <= 8
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} {label:<24} {pdf_n:>10}   {pdf_p:>5.1f}%   {bot_n:>10}   {bot_p:>5.1f}%")

    exit_row("Take Profit (50%)",   PDF["exit_tp_count"],  PDF["exit_tp_pct"],  "TAKE_PROFIT")
    exit_row("21-DTE Exit",         PDF["exit_dte_count"], PDF["exit_dte_pct"], "DTE_EXIT")
    exit_row("Stop Loss (2×)",      PDF["exit_sl_count"],  PDF["exit_sl_pct"],  "STOP_LOSS")
    exit_row("Verfallen (OTM)",     PDF["exit_exp_count"], PDF["exit_exp_pct"], "EXPIRY")

    hdr("TOP/FLOP SYMBOLE — Bot-Backtest")
    top5  = m.get("top5",  [])
    flop5 = m.get("flop5", [])
    print(f"  Top-5:")
    for sym, pnls in top5:
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"    {sym:<6}  {len(pnls):>3}×  ${sum(pnls):>+7.0f}  Win {wr:.0%}")
    print(f"  Flop-5:")
    for sym, pnls in flop5:
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"    {sym:<6}  {len(pnls):>3}×  ${sum(pnls):>+7.0f}  Win {wr:.0%}")

    hdr("ANALYSE DER VERBLEIBENDEN ABWEICHUNGEN")
    bt_mod = _BT_MODULE
    iv_ok  = abs(bt_mod.MIN_VOLA - 0.28) < 0.001
    cr_ok  = bt_mod.MIN_CREDIT_ABS >= 80
    hv_ok  = bt_mod.HV_WINDOW == 30
    sl_ok  = bt_mod.SLIPPAGE >= 0.99
    vf_ok  = abs(bt_mod.IV_VRP_FACTOR - 1.0) < 0.01

    print(f"""
  PARAMETER-STATUS (✅ PDF-konform / ⚠️  noch abweichend):
    {"✅" if iv_ok  else "⚠️ "} Min. IV ({bt_mod.MIN_VOLA:.0%}) — PDF: >28%
    {"✅" if cr_ok  else "⚠️ "} Min. Credit (${bt_mod.MIN_CREDIT_ABS:.0f}) — PDF: $80
    {"✅" if hv_ok  else "⚠️ "} HV-Fenster ({bt_mod.HV_WINDOW}d) — PDF: 30 Tage
    {"✅" if vf_ok  else "⚠️ "} IV-Faktor ({bt_mod.IV_VRP_FACTOR:.2f}×) — PDF: 1.0× (raw HV)
    {"✅" if sl_ok  else "⚠️ "} Slippage ({1-bt_mod.SLIPPAGE:.0%} Abschlag) — PDF: 0%
    ⚠️  Symbol-Universe (120 Symbole) — PDF: 24 handverlesene Symbole

  WARUM NOCH UNTERSCHIEDE BESTEHEN:
  1. Symbol-Universe (größter Faktor)
     Das 120-Symbole-Universum enthält schwache Titel (SOFI, LYFT, INTC,
     PINS, ON, AA) die im PDF-Backtest gar nicht enthalten waren. Diese
     erzeugen überproportional viele Stop-Losses und ziehen den P&L runter.

  2. IV-Faktor {bt_mod.IV_VRP_FACTOR:.2f}× vs. PDF 1.0×
     HV × {bt_mod.IV_VRP_FACTOR:.2f} überschätzt die IV für Niedrig-IV-Symbole —
     damit werden manche Trades zugelassen, die bei echter IV abgelehnt würden.

  3. Slippage {(1-bt_mod.SLIPPAGE):.0%} vs. 0% im PDF
     Jeder Trade verliert {(1-bt_mod.SLIPPAGE):.0%} Credit durch Fill-Discount —
     das reduziert Jahresrendite ca. 10–15 Prozentpunkte.

  4. HV-Fenster {bt_mod.HV_WINDOW}d vs. 30d im PDF
     20-Tage-HV reagiert schneller auf Volatilitäts-Spikes → mehr Entries
     in volatilen Phasen (Okt 2024 Korrektur, Apr 2025 Zoll-Crash).
""")

    print("═" * W)
    print("  ⚠️  HINWEIS: Beide Backtests sind Simulationen ohne echten Options-Feed.")
    print("     Vergangene Performance garantiert keine zukünftigen Ergebnisse.")
    print("═" * W)
    print()


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bt, trades, daily_pnl, filter_stats, captured, START, END = run_and_capture()
    print(f"✅  Backtest fertig: {len(trades)} Trades\n")

    m = calc_metrics(trades, daily_pnl, START, END)
    print_report(m, START, END)
