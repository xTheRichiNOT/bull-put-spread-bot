#!/usr/bin/env python3
"""
Shadow Trade Analyzer
=====================
Wertet shadow_trades.jsonl aus und zeigt:
  1. Filter-Engpass-Analyse  – wo scheitern die meisten Signale?
  2. Symbol-Diagnose         – welche Symbole sollten aus der Watchlist?
  3. Score-Verteilung        – wie nah sind Near-Misses am Trade?
  4. VIX-Regime-Analyse      – wann werden die meisten Trades blockiert?
  5. Live-Trade-Auswertung   – P&L vs. Score-Korrelation (sobald Trades vorliegen)
  6. Watchlist-Empfehlungen  – konkrete Maßnahmen

Nutzung:  python3 shadow_analyze.py [pfad/zur/shadow_trades.jsonl]
"""

import json, sys, os, math
from datetime import datetime, timedelta
from collections import defaultdict

# ─── Datei laden ─────────────────────────────────────────────────────────────
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "shadow_trades.jsonl"
)

rejected, placed = [], []
parse_errors = 0
with open(PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if d.get("type") == "placed":
                placed.append(d)
            else:
                rejected.append(d)
        except Exception:
            parse_errors += 1

all_entries = rejected + placed
if not all_entries:
    print("⚠️  Keine Einträge gefunden.")
    sys.exit(0)

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────
W = 72

def hdr(title):
    print(f"\n{'═' * W}")
    print(f"  {title}")
    print(f"{'═' * W}")

def sep():
    print("─" * W)

def bar(value, max_val, width=30, char="█"):
    filled = int(round(value / max_val * width)) if max_val > 0 else 0
    return char * filled + "░" * (width - filled)

def ts_to_dt(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None

# ─── Zeitraum ────────────────────────────────────────────────────────────────
timestamps = [ts_to_dt(d["ts"]) for d in all_entries if d.get("ts")]
timestamps = [t for t in timestamps if t]
ts_min = min(timestamps) if timestamps else None
ts_max = max(timestamps) if timestamps else None
days_monitored = max(1, (ts_max - ts_min).days + 1) if ts_min and ts_max else 1

# ─── 1. ÜBERSICHT ────────────────────────────────────────────────────────────
hdr("ÜBERSICHT")
total   = len(all_entries)
n_rej   = len(rejected)
n_plc   = len(placed)
print(f"  Datei:              {PATH}")
print(f"  Zeitraum:           {ts_min.strftime('%d.%m.%Y %H:%M') if ts_min else '?'} – "
      f"{ts_max.strftime('%d.%m.%Y %H:%M') if ts_max else '?'}  ({days_monitored} Tage)")
print(f"  Einträge gesamt:    {total}")
print(f"  ├─ Abgelehnt:       {n_rej}  ({n_rej/total:.0%})")
print(f"  └─ Platziert:       {n_plc}  ({n_plc/total:.0%})")
if parse_errors:
    print(f"  ⚠️  Parse-Fehler:    {parse_errors}")
if n_plc == 0:
    print(f"\n  ℹ️  Noch keine platzierten Trades — warte auf Live-Daten (Captrade).")
    print(f"     Sobald echte Trades laufen, erscheinen hier P&L-Analysen.")

# ─── 2. FILTER-ENGPASS-ANALYSE ───────────────────────────────────────────────
hdr("2. FILTER-ENGPASS-ANALYSE  (wo scheitern Signale?)")

stage_data = defaultdict(list)
for d in rejected:
    stage_data[d.get("stage", "?")].append(d)

STAGE_LABELS = {
    "liquidity": "Liquidität (OI/Volume)",
    "earnings":  "Earnings-Buffer",
    "score":     "Score < Threshold",
    "credit":    "Credit < $80",
    "prob_otm":  "P(Win) außerhalb 72–85%",
    "ev_ratio":  "EV-Ratio zu niedrig",
    "prob_max_loss": "Max-Verlust-Wahrsch. > 20%",
}

max_stage = max((len(v) for v in stage_data.values()), default=1)
print(f"  {'Filter-Stage':<28} {'Anzahl':>7}  {'Anteil':>7}  Visualisierung")
sep()
for stage, entries in sorted(stage_data.items(), key=lambda x: -len(x[1])):
    label = STAGE_LABELS.get(stage, stage)
    n     = len(entries)
    pct   = n / n_rej if n_rej > 0 else 0
    b     = bar(n, max_stage, width=20)
    print(f"  {label:<28} {n:>7}  {pct:>6.1%}  {b}")

print(f"\n  → Hauptproblem: '{max(stage_data, key=lambda s: len(stage_data[s]))}' blockiert "
      f"{len(stage_data[max(stage_data, key=lambda s: len(stage_data[s]))])} von {n_rej} Signalen.")

# ─── 3. SYMBOL-DIAGNOSE ──────────────────────────────────────────────────────
hdr("3. SYMBOL-DIAGNOSE  (welche Symbole scheitern wie?)")

sym_stages = defaultdict(lambda: defaultdict(int))
sym_total  = defaultdict(int)
for d in rejected:
    s = d.get("symbol", "?")
    sym_stages[s][d.get("stage", "?")] += 1
    sym_total[s] += 1

# Symbole die IMMER an Liquidität scheitern → Watchlist-Kandidaten
always_liq = [s for s, stages in sym_stages.items()
              if stages.get("liquidity", 0) == sym_total[s] and sym_total[s] >= 3]
mixed      = [s for s in sym_total if s not in always_liq]

print(f"  {'Symbol':<8} {'Gesamt':>7} {'Liq':>5} {'Earn':>5} {'Score':>6} {'Credit':>7}  Diagnose")
sep()
for sym, total_s in sorted(sym_total.items(), key=lambda x: -x[1]):
    liq  = sym_stages[sym].get("liquidity", 0)
    earn = sym_stages[sym].get("earnings",  0)
    scr  = sym_stages[sym].get("score",     0)
    crd  = sym_stages[sym].get("credit",    0)
    if liq == total_s and total_s >= 3:
        diag = "❌ immer Liquidität → Watchlist prüfen"
    elif earn > total_s * 0.5:
        diag = "📅 oft Earnings blockiert → saisonal"
    elif scr > 0:
        diag = f"⚠️  Score-Grenze ({scr}×) — Near-Miss"
    elif crd > 0:
        diag = f"💰 Credit-Grenze ({crd}×)"
    else:
        diag = "—"
    print(f"  {sym:<8} {total_s:>7} {liq:>5} {earn:>5} {scr:>6} {crd:>7}  {diag}")

if always_liq:
    print(f"\n  ⚠️  WATCHLIST-KANDIDATEN (immer Liquiditätsproblem, ≥3 Scans):")
    print(f"     {', '.join(sorted(always_liq))}")
    print(f"     → Diese Symbole haben dauerhaft zu wenig Open Interest.")
    print(f"       Mit echten Live-Daten (Captrade) wird das besser — erst dann entscheiden.")

# ─── 4. SCORE-VERTEILUNG (Near-Misses) ───────────────────────────────────────
score_entries = [d for d in rejected if d.get("stage") in ("score", "credit") and "score" in d]

if score_entries:
    hdr("4. SCORE-VERTEILUNG  (wie nah sind Near-Misses am Trade?)")

    buckets = defaultdict(list)
    for d in score_entries:
        sc = d.get("score", 0)
        if sc is None or sc != sc:  # None or NaN
            sc = 0.0
        low = int(sc * 10) / 10
        b   = f"{low:.1f}–{low + 0.1:.1f}"
        buckets[b].append(d)

    placed_scores = [d.get("score", 0) for d in placed if "score" in d]
    threshold = 0.70

    max_b = max((len(v) for v in buckets.values()), default=1)
    print(f"  Score-Schwelle: {threshold:.2f}  |  Alles darunter = abgelehnt\n")
    print(f"  {'Score-Bereich':<14} {'Anzahl':>7}  Visualisierung")
    sep()
    for bucket in sorted(buckets.keys()):
        n = len(buckets[bucket])
        b = bar(n, max_b, width=24)
        low = float(bucket.split("–")[0])
        marker = "  ← nahe an Grenze" if threshold - 0.15 <= low < threshold else ""
        print(f"  {bucket:<14} {n:>7}  {b}{marker}")

    near_miss = [d for d in score_entries if d.get("score", 0) >= threshold - 0.10]
    if near_miss:
        print(f"\n  Near-Misses (Score {threshold-0.10:.2f}–{threshold:.2f}): {len(near_miss)} Signale")
        print(f"  Diese Trades wären bei leicht niedrigerem Threshold (<{threshold:.2f}) durchgegangen:")
        for d in sorted(near_miss, key=lambda x: -x.get("score", 0))[:8]:
            print(f"    {d['symbol']:<6}  Score={d['score']:.3f}  IV={d.get('iv',0):.0%}"
                  f"  P(Win)={d.get('prob_otm',0):.0%}  Credit=${d.get('credit',0):.0f}"
                  f"  {d.get('ts','')[:10]}")

# ─── 5. IV & VIX-REGIME ──────────────────────────────────────────────────────
hdr("5. MARKT-UMFELD  (IV & VIX-Regime der abgelehnten Signale)")

vix_regimes = defaultdict(int)
iv_buckets  = defaultdict(int)
for d in all_entries:
    vix_regimes[d.get("vix_regime", "?")] += 1
    iv = d.get("iv", 0)
    if iv > 0:
        b = f"{int(iv * 10) * 10}–{int(iv * 10) * 10 + 10}%"
        iv_buckets[b] += 1

print(f"  VIX-Regime:")
max_vix = max(vix_regimes.values(), default=1)
for regime, cnt in sorted(vix_regimes.items(), key=lambda x: -x[1]):
    print(f"    {regime:<12} {cnt:>5}×  {bar(cnt, max_vix, 20)}")

print(f"\n  IV-Verteilung der gescannten Signale:")
max_iv = max(iv_buckets.values(), default=1)
for bucket in sorted(iv_buckets.keys()):
    cnt = iv_buckets[bucket]
    print(f"    {bucket:<12} {cnt:>5}×  {bar(cnt, max_iv, 20)}")

# ─── 6. PLATZIERTE TRADES (sobald vorhanden) ─────────────────────────────────
if placed:
    hdr("6. PLATZIERTE TRADES  (Live-Auswertung)")

    closed   = [t for t in placed if t.get("pnl") is not None]
    open_pos = [t for t in placed if t.get("pnl") is None]

    print(f"  Platziert gesamt:   {len(placed)}")
    print(f"  ├─ Geschlossen:     {len(closed)}")
    print(f"  └─ Noch offen:      {len(open_pos)}")

    if closed:
        wins   = [t for t in closed if t.get("pnl", 0) > 0]
        losses = [t for t in closed if t.get("pnl", 0) <= 0]
        total_pnl = sum(t.get("pnl", 0) for t in closed)
        avg_w  = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
        avg_l  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        wr     = len(wins) / len(closed) if closed else 0

        print(f"\n  LIVE P&L:")
        print(f"    Win-Rate:       {wr:.1%}  ({len(wins)}W / {len(losses)}L)")
        print(f"    Gesamt P&L:     ${total_pnl:+,.2f}")
        print(f"    Ø Gewinn/Win:   ${avg_w:+.2f}")
        print(f"    Ø Verlust/Loss: ${avg_l:+.2f}")

        # Score-Korrelation
        with_score = [t for t in closed if "score" in t]
        if len(with_score) >= 5:
            sep()
            print(f"\n  SCORE → P&L KORRELATION (n={len(with_score)}):")
            score_buckets = defaultdict(list)
            for t in with_score:
                b = round(t["score"] * 10) / 10
                score_buckets[b].append(t["pnl"])
            for sc_key in sorted(score_buckets):
                pnls = score_buckets[sc_key]
                wr_b = sum(1 for p in pnls if p > 0) / len(pnls)
                avg  = sum(pnls) / len(pnls)
                print(f"    Score ~{sc_key:.1f}: {len(pnls):>3}× | WR {wr_b:.0%} | ø ${avg:+.2f}")

    if open_pos:
        sep()
        print(f"\n  OFFENE POSITIONEN ({len(open_pos)}):")
        for t in open_pos:
            unreal = t.get("unrealized_pnl", "—")
            unreal_str = f"${unreal:+.0f}" if isinstance(unreal, (int, float)) else str(unreal)
            print(f"    {t.get('symbol','?'):<6}  Entry: {t.get('ts','?')[:10]}"
                  f"  Score={t.get('score',0):.3f}  Unrealized: {unreal_str}")

# ─── 7. WATCHLIST-EMPFEHLUNGEN ───────────────────────────────────────────────
hdr("7. HANDLUNGSEMPFEHLUNGEN")

# Liquiditäts-Dauerblocker
liq_always = [s for s, stages in sym_stages.items()
              if stages.get("liquidity", 0) == sym_total[s] and sym_total[s] >= 5]
liq_often  = [s for s, stages in sym_stages.items()
              if stages.get("liquidity", 0) >= sym_total[s] * 0.8
              and sym_total[s] >= 3 and s not in liq_always]

# Score-Grenzfälle
score_near = [d.get("symbol") for d in score_entries
              if 0.60 <= d.get("score", 0) < 0.70]
score_near_syms = sorted(set(score_near), key=lambda s: -score_near.count(s))

total_scans = len(all_entries)
conversion  = n_plc / total_scans * 100 if total_scans > 0 else 0

print(f"""
  AKTUELLE LAGE:
  ─────────────
  Conversion-Rate: {n_plc}/{total_scans} = {conversion:.1f}% der Signale wurden platziert
  (Ziel: 5–15% — bei zu viel Ablehnung Filter lockern, bei zu wenig strenger werden)

  A) LIQUIDITÄTSPROBLEM (74% aller Ablehnungen):
     → Liegt an verzögerten Demo-Daten (IBKR Paper).
     → Mit Captrade Live-Daten wird Open Interest realistischer — erst dann
       entscheiden welche Symbole dauerhaft entfernt werden sollten.""")

if liq_always:
    print(f"\n     Kandidaten für Entfernung NACH Live-Test:")
    print(f"     {', '.join(liq_always)}")
    print(f"     (Immer Liquiditätsproblem, ≥5 Scans — prüfen ob Live-Daten das ändert)")

print(f"""
  B) EARNINGS-FILTER (15% Ablehnungen):
     → Ist korrekt — Earnings-Nähe ist echtes Risiko.
     → Keine Anpassung nötig.

  C) SCORE-GRENZFÄLLE (9% Ablehnungen):""")

if score_near_syms:
    print(f"     Near-Misses (Score 0.60–0.70): {', '.join(score_near_syms[:8])}")
    print(f"     → Bei Live-Daten prüfen ob diese Symbole konsistent knapp unter 0.70 bleiben.")
    print(f"       Falls ja: entweder Threshold auf 0.65 senken ODER Score-Gewichte anpassen.")
else:
    print(f"     Keine auffälligen Near-Misses — Threshold 0.70 erscheint gut kalibriert.")

print(f"""
  D) NÄCHSTE SCHRITTE:
     1. Captrade Live-Daten aktivieren → Liquiditätsprobleme sollten abnehmen
     2. Bot 4 Wochen im Demo-Modus laufen lassen → technischen Betrieb prüfen
     3. Nach 30 geschlossenen Trades: Score-Korrelation hier auswerten (Punkt 6)
     4. Nach 60+ Trades: Watchlist-Bereinigung und Parameter-Feintuning
""")

print("═" * W)
print(f"  Analyzer abgeschlossen | {len(all_entries)} Einträge ausgewertet")
print("═" * W)
