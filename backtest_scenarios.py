#!/usr/bin/env python3
"""
Szenario-Vergleich: Take-Profit & 21-DTE-Exit Varianten
========================================================
Testet 4 Konfigurationen gegen den Baseline-Backtest:
  A) Baseline        — TP 50%, 21-DTE aktiv
  B) TP 70%          — TP 70%, 21-DTE aktiv
  C) Kein DTE-Exit   — TP 50%, 21-DTE deaktiviert
  D) Nur TP 70%      — TP 70%, 21-DTE aktiv  (Alias B, für Klarheit)

Nutzung:  python3 backtest_scenarios.py
"""

import math, sys, os, io, importlib.util
from datetime import datetime, timedelta
from collections import defaultdict
from contextlib import redirect_stdout

START = "2024-10-01"
END   = "2026-04-20"

# ─── Backtest-Modul laden ────────────────────────────────────────────────────
bt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest.py")
spec    = importlib.util.spec_from_file_location("backtest_mod", bt_path)
bt      = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


# ─── Szenarien ───────────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "name":          "D  TP 70%",
        "desc":          "TP 70%  |  kein DTE-Exit",
        "take_profit":   0.70,
        "dte_exit_on":   False,
    },
    {
        "name":          "E  TP 80%",
        "desc":          "TP 80%  |  kein DTE-Exit",
        "take_profit":   0.80,
        "dte_exit_on":   False,
    },
    {
        "name":          "F  TP 90%",
        "desc":          "TP 90%  |  kein DTE-Exit",
        "take_profit":   0.90,
        "dte_exit_on":   False,
    },
]


# ─── Modifizierter Backtest-Loop ─────────────────────────────────────────────
def run_scenario(sym_data, all_dates, start_dt, end_dt, take_profit_pct, dte_exit_on):
    """Läuft den Backtest mit überschriebenen TP- und DTE-Exit-Parametern."""
    open_positions = {}
    sector_counts  = defaultdict(int)
    trades         = []
    daily_pnl      = {}

    for day in all_dates:
        day_pnl  = 0.0
        to_close = []

        for sym, pos in list(open_positions.items()):
            sig       = pos["sig"]
            short_s   = sig["short_strike"]
            long_s    = sig["long_strike"]
            credit_ps = sig["credit_ps"]
            iv        = sig["iv"]
            expiry_dt = pos["expiry_date"]

            day_entry = sym_data[sym].get(day)
            if day_entry is None:
                continue
            price    = day_entry[0]
            dte_left = max(0, (expiry_dt - day).days)
            sv       = bt.spread_value(price, short_s, long_s, iv, dte_left)

            tp_thr = credit_ps * (1 - take_profit_pct)   # ← szenario-spezifisch
            sl_thr = credit_ps * bt.STOP_LOSS_MULT

            if dte_left <= 0:
                reason = "EXPIRY"
            elif sv <= tp_thr:
                reason = "TAKE_PROFIT"
            elif sv >= sl_thr:
                reason = "STOP_LOSS"
            elif (dte_exit_on                              # ← szenario-spezifisch
                  and dte_left <= bt.DTE_EXIT
                  and (price - short_s) / price < bt.BUFFER_MIN_PCT):
                reason = "DTE_EXIT"
            else:
                reason = None

            if reason:
                to_close.append((sym, pos, (credit_ps - sv) * 100, reason))

        for sym, pos, pnl, reason in to_close:
            sec = bt.SECTOR_MAP.get(sym, "?")
            sector_counts[sec] = max(0, sector_counts[sec] - 1)
            del open_positions[sym]
            day_pnl += pnl
            trades.append({
                "symbol":      sym,
                "entry_date":  pos["entry_date"].isoformat(),
                "exit_date":   day.isoformat(),
                "dte_held":    (day - pos["entry_date"]).days,
                "credit":      round(pos["sig"]["credit"], 2),
                "pnl":         round(pnl, 2),
                "exit_reason": reason,
            })

        daily_pnl[day] = round(day_pnl, 2)

        slots = bt.MAX_POSITIONS - len(open_positions)
        if slots <= 0:
            continue

        candidates = []
        for sym in bt.WATCHLIST:
            if sym in open_positions or sym not in sym_data:
                continue
            day_entry = sym_data[sym].get(day)
            if day_entry is None:
                continue
            price, iv = day_entry
            sig = bt.evaluate_signal(price, iv)
            if sig is None:
                continue
            sec = bt.SECTOR_MAP.get(sym, "?")
            if sector_counts[sec] >= bt.MAX_PER_SECTOR:
                continue
            candidates.append((sym, sig, sec))

        candidates.sort(key=lambda x: x[1]["score"], reverse=True)
        for sym, sig, sec in candidates:
            if len(open_positions) >= bt.MAX_POSITIONS or sym in open_positions:
                break
            expiry_dt = day + timedelta(days=bt.FIXED_DTE)
            open_positions[sym] = {"entry_date": day, "expiry_date": expiry_dt, "sig": sig}
            sector_counts[sec] += 1

    # Forced Close am Ende
    last_day = all_dates[-1] if all_dates else end_dt
    for sym, pos in list(open_positions.items()):
        sig       = pos["sig"]
        day_entry = sym_data[sym].get(last_day)
        price     = day_entry[0] if day_entry else sig["entry_price"]
        dte_left  = max(0, (pos["expiry_date"] - last_day).days)
        sv        = bt.spread_value(price, sig["short_strike"], sig["long_strike"], sig["iv"], dte_left)
        pnl       = (sig["credit_ps"] - sv) * 100
        trades.append({
            "symbol":      sym,
            "entry_date":  pos["entry_date"].isoformat(),
            "exit_date":   last_day.isoformat(),
            "dte_held":    (last_day - pos["entry_date"]).days,
            "credit":      round(sig["credit"], 2),
            "pnl":         round(pnl, 2),
            "exit_reason": "END_OF_BACKTEST",
        })

    return trades, daily_pnl


# ─── Kennzahlen ──────────────────────────────────────────────────────────────
def metrics(trades, daily_pnl):
    if not trades:
        return {}
    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n      = len(trades)
    total  = sum(t["pnl"] for t in trades)
    avg_w  = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_l  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
    gw     = sum(t["pnl"] for t in wins)
    gl     = abs(sum(t["pnl"] for t in losses))

    cum, peak, max_dd = 0.0, 0.0, 0.0
    for d in sorted(daily_pnl):
        cum  += daily_pnl[d]
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    months   = max(1, (datetime.strptime(END, "%Y-%m-%d") - datetime.strptime(START, "%Y-%m-%d")).days / 30.4375)
    monthly  = total / months
    avg_margin = sum((t["credit"] / 0.18) - t["credit"] / 100 for t in trades) / n
    capital  = avg_margin * bt.MAX_POSITIONS
    ann_ret  = (monthly * 12 / capital * 100) if capital > 0 else 0.0

    exits = defaultdict(int)
    for t in trades:
        exits[t["exit_reason"]] += 1

    return {
        "n":         n,
        "wr":        len(wins) / n,
        "total":     total,
        "monthly":   monthly,
        "ann_ret":   ann_ret,
        "avg_w":     avg_w,
        "avg_l":     avg_l,
        "pf":        gw / gl if gl > 0 else float("inf"),
        "max_dd":    max_dd,
        "avg_hold":  sum(t["dte_held"] for t in trades) / n,
        "exits":     dict(exits),
        "capital":   capital,
    }


# ─── Report ──────────────────────────────────────────────────────────────────
def print_comparison(results):
    W = 74
    print(f"\n{'═'*W}")
    print(f"  SZENARIO-VERGLEICH  |  {START} – {END}")
    print(f"{'═'*W}")

    # Header
    hdr = f"  {'Kennzahl':<26}"
    for sc in results:
        hdr += f"  {sc['scenario']['name']:<18}"
    print(hdr)
    print(f"  {'':26}" + "".join(f"  {sc['scenario']['desc']:<18}" for sc in results))
    print("─" * W)

    def row(label, fn, highlight="max"):
        vals = [fn(sc["m"]) for sc in results]
        best = max(vals) if highlight == "max" else min(vals)
        line = f"  {label:<26}"
        for v in vals:
            cell = fn.__doc__ % v if fn.__doc__ else str(v)
            mark = " ◀" if abs(v - best) < 0.001 and len(results) > 1 else "  "
            line += f"  {cell:<16}{mark}"
        print(line)

    # Gesamt P&L
    vals = [sc["m"]["total"] for sc in results]
    best = max(vals)
    line = f"  {'Gesamt P&L':<26}"
    for sc in results:
        v = sc["m"]["total"]
        cell = f"${v:+,.0f}"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Jahresrendite
    vals = [sc["m"]["ann_ret"] for sc in results]
    best = max(vals)
    line = f"  {'Jahresrendite':<26}"
    for sc in results:
        v = sc["m"]["ann_ret"]
        cell = f"{v:+.1f}%"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Monatlicher Gewinn
    vals = [sc["m"]["monthly"] for sc in results]
    best = max(vals)
    line = f"  {'Monatl. Gewinn':<26}"
    for sc in results:
        v = sc["m"]["monthly"]
        cell = f"${v:+.0f}"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Win-Rate
    vals = [sc["m"]["wr"] for sc in results]
    best = max(vals)
    line = f"  {'Win-Rate':<26}"
    for sc in results:
        v = sc["m"]["wr"]
        cell = f"{v:.1%}"
        mark = " ◀" if abs(v - best) < 0.0005 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Trades gesamt
    line = f"  {'Trades gesamt':<26}"
    for sc in results:
        line += f"  {sc['m']['n']:<18}"
    print(line)

    # Ø Haltedauer
    line = f"  {'Ø Haltedauer (Tage)':<26}"
    for sc in results:
        line += f"  {sc['m']['avg_hold']:<18.1f}"
    print(line)

    # Ø Gewinn (Wins)
    vals = [sc["m"]["avg_w"] for sc in results]
    best = max(vals)
    line = f"  {'Ø Gewinn/Win-Trade':<26}"
    for sc in results:
        v = sc["m"]["avg_w"]
        cell = f"${v:+.2f}"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Ø Verlust (Losses)
    vals = [sc["m"]["avg_l"] for sc in results]
    best = max(vals)  # am wenigsten negativ = best
    line = f"  {'Ø Verlust/Loss-Trade':<26}"
    for sc in results:
        v = sc["m"]["avg_l"]
        cell = f"${v:+.2f}"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Profit-Faktor
    vals = [sc["m"]["pf"] for sc in results]
    best = max(v for v in vals if v != float("inf"))
    line = f"  {'Profit-Faktor':<26}"
    for sc in results:
        v = sc["m"]["pf"]
        cell = f"{v:.2f}×" if v != float("inf") else "∞"
        mark = " ◀" if v != float("inf") and abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    # Max Drawdown (weniger ist besser → min highlight)
    vals = [sc["m"]["max_dd"] for sc in results]
    best = min(vals)
    line = f"  {'Max. Drawdown':<26}"
    for sc in results:
        v = sc["m"]["max_dd"]
        cell = f"${v:,.0f}"
        mark = " ◀" if abs(v - best) < 0.01 else "  "
        line += f"  {cell:<16}{mark}"
    print(line)

    print("─" * W)

    # Exit-Verteilung
    print(f"\n  EXIT-VERTEILUNG")
    print("─" * W)
    all_reasons = sorted({r for sc in results for r in sc["m"]["exits"]})
    for reason in all_reasons:
        line = f"  {reason:<26}"
        for sc in results:
            n   = sc["m"]["n"]
            cnt = sc["m"]["exits"].get(reason, 0)
            pct = cnt / n * 100 if n > 0 else 0
            line += f"  {cnt:>3}× ({pct:>4.1f}%)       "
        print(line)

    print(f"\n{'═'*W}")
    print(f"  ◀ = bester Wert in dieser Zeile")

    # Fazit
    print(f"\n{'═'*W}")
    print(f"  FAZIT")
    print(f"{'═'*W}")

    totals     = [(sc["scenario"]["name"].strip(), sc["m"]["total"], sc["m"]["wr"], sc["m"]["pf"]) for sc in results]
    best_total = max(totals, key=lambda x: x[1])
    base_total = totals[0][1]
    base_name  = totals[0][0]

    for name, total, wr, pf in totals:
        diff   = total - base_total
        sign   = "+" if diff >= 0 else ""
        marker = " ← BESTE VARIANTE" if total == best_total[1] else ""
        pf_str = f"{pf:.2f}×" if pf != float("inf") else "∞"
        print(f"  {name:<24}  P&L ${total:>+7,.0f}  (vs {base_name}: {sign}${diff:,.0f})  WR {wr:.1%}  PF {pf_str}{marker}")

    print()
    print("  INTERPRETATION:")
    for name, total, wr, pf in totals[1:]:
        diff = total - base_total
        if diff > 0:
            print(f"  ✅  {name}: +${diff:,.0f} mehr als {base_name} — lohnt sich.")
        else:
            print(f"  ⚠️   {name}: ${diff:,.0f} schlechter als {base_name}.")

    print(f"\n  ⚠️  Simulation ohne echten Options-Feed — nur Orientierungswerte.")
    print(f"{'═'*W}\n")


# ─── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Kursdaten einmalig laden
    print(f"📥  Lade Kursdaten einmalig für alle Szenarien …")
    buf = io.StringIO()
    with redirect_stdout(buf):
        sym_data = bt.load_data(START, END)

    start_dt = datetime.strptime(START, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(END,   "%Y-%m-%d").date()
    all_dates_set = set()
    for d in sym_data.values():
        all_dates_set |= set(d.keys())
    all_dates = sorted(d for d in all_dates_set if start_dt <= d <= end_dt)
    print(f"✅  {len(sym_data)} Symbole geladen | {len(all_dates)} Handelstage\n")

    results = []
    for sc in SCENARIOS:
        print(f"  🔁  Szenario {sc['name']} — {sc['desc']} …", end=" ", flush=True)
        trades, daily_pnl = run_scenario(
            sym_data, all_dates, start_dt, end_dt,
            take_profit_pct = sc["take_profit"],
            dte_exit_on     = sc["dte_exit_on"],
        )
        m = metrics(trades, daily_pnl)
        results.append({"scenario": sc, "trades": trades, "m": m})
        print(f"{m['n']} Trades | P&L ${m['total']:+,.0f} | WR {m['wr']:.1%}")

    print_comparison(results)
