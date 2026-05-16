#!/usr/bin/env python3
"""
Backtest — Bull Put Spread Bot (vereinfacht)
============================================
Simuliert die Bot-Strategie auf historischen Kursdaten.

Einschränkungen (ehrlich):
  • IV = 20-Tage-Rolling-HV × 1.3  (Volatility-Risk-Premium-Faktor)
    → echte IV liegt im Schnitt 25–40% über realized HV
  • Options-Preise via Black-Scholes (kein echtes Bid/Ask)
  • Slippage 82 % des theoretischen Credits (= yfinance-Bid-Faktor aus bot.py)
  • Expiry = Entry + 52 Kalendertage (Mittelwert DTE 45–60)
  • Keine Earnings-Checks / Makro-Events
  • Kein IB-Combo-Pricing, keine Delta-Validierung

Nutzung:
  python3 backtest.py [JJJJ-MM-TT] [JJJJ-MM-TT]
  python3 backtest.py 2023-01-01 2024-12-31
"""

import math
import sys
import os
import csv
from datetime import datetime, timedelta, date
from collections import defaultdict

# ── Parameter (identisch zu bot.py) ──────────────────────────────────────────
WATCHLIST = [
    'AAPL','MSFT','NVDA','GOOGL','AMZN','META','CSCO','IBM','DELL','AMAT',
    'AMD','AVGO','QCOM','MU','TSM','INTC','TXN','LRCX','KLAC','MRVL','ON','ARM',
    'CRM','ORCL','NOW','ADBE','PLTR','WDAY','SNOW','PANW','CRWD','FTNT','DDOG','APP',
    'TSLA','NFLX','UBER','SHOP','LYFT','PINS','DASH','RBLX',
    'COIN','PYPL','V','MA','AFRM','SOFI',
    'JPM','GS','MS','BAC','WFC','C','AXP','SCHW','BLK','BX','USB',
    'LLY','JNJ','UNH','ABBV','PFE','MRK','BMY','AMGN','MDT','ABT','CVS','GILD','VRTX',
    'XOM','CVX','COP','EOG','SLB','OXY','MPC','VLO',
    'WMT','COST','TGT','HD','LOW','NKE','SBUX','MCD','CMG','DG','LULU',
    'CAT','DE','HON','GE','LMT','RTX','BA','NOC','EMR','MMM',
    'T','VZ','TMUS',
    'NEE','AMT','PLD','DUK',
    'LIN','NEM','FCX','AA',
    'KO','PEP','PM','MO',
    'ABNB','BKNG','MAR',
]

SECTOR_MAP = {
    'AAPL':'Tech','MSFT':'Tech','GOOGL':'Tech','AMZN':'Tech','META':'Tech',
    'CSCO':'Tech','IBM':'Tech','DELL':'Tech','AMAT':'Tech',
    'NVDA':'Halbleiter','AMD':'Halbleiter','AVGO':'Halbleiter','QCOM':'Halbleiter',
    'MU':'Halbleiter','TSM':'Halbleiter','INTC':'Halbleiter','TXN':'Halbleiter',
    'LRCX':'Halbleiter','KLAC':'Halbleiter','MRVL':'Halbleiter','ON':'Halbleiter','ARM':'Halbleiter',
    'CRM':'Software','ORCL':'Software','NOW':'Software','ADBE':'Software','PLTR':'Software',
    'WDAY':'Software','SNOW':'Software','PANW':'Software','CRWD':'Software',
    'FTNT':'Software','DDOG':'Software','APP':'Software',
    'TSLA':'ConsumerTech','NFLX':'ConsumerTech','UBER':'ConsumerTech','SHOP':'ConsumerTech',
    'LYFT':'ConsumerTech','PINS':'ConsumerTech','DASH':'ConsumerTech','RBLX':'ConsumerTech',
    'COIN':'Fintech','PYPL':'Fintech','V':'Fintech','MA':'Fintech','AFRM':'Fintech','SOFI':'Fintech',
    'JPM':'Banken','GS':'Banken','MS':'Banken','BAC':'Banken','WFC':'Banken','C':'Banken',
    'AXP':'Banken','SCHW':'Banken','BLK':'Banken','BX':'Banken','USB':'Banken',
    'LLY':'Healthcare','JNJ':'Healthcare','UNH':'Healthcare','ABBV':'Healthcare',
    'PFE':'Healthcare','MRK':'Healthcare','BMY':'Healthcare','AMGN':'Healthcare',
    'MDT':'Healthcare','ABT':'Healthcare','CVS':'Healthcare','GILD':'Healthcare','VRTX':'Healthcare',
    'XOM':'Energie','CVX':'Energie','COP':'Energie','EOG':'Energie',
    'SLB':'Energie','OXY':'Energie','MPC':'Energie','VLO':'Energie',
    'WMT':'Retail','COST':'Retail','TGT':'Retail','HD':'Retail','LOW':'Retail',
    'NKE':'Retail','SBUX':'Retail','MCD':'Retail','CMG':'Retail','DG':'Retail','LULU':'Retail',
    'CAT':'Industrie','DE':'Industrie','HON':'Industrie','GE':'Industrie','LMT':'Industrie',
    'RTX':'Industrie','BA':'Industrie','NOC':'Industrie','EMR':'Industrie','MMM':'Industrie',
    'T':'Telecom','VZ':'Telecom','TMUS':'Telecom',
    'NEE':'Versorger','AMT':'Versorger','PLD':'Versorger','DUK':'Versorger',
    'LIN':'Rohstoffe','NEM':'Rohstoffe','FCX':'Rohstoffe','AA':'Rohstoffe',
    'KO':'Food','PEP':'Food','PM':'Food','MO':'Food',
    'ABNB':'Travel','BKNG':'Travel','MAR':'Travel',
}

# Bot-Parameter (PDF-konform)
ABSTAND_Y          = 0.10
MIN_VOLA           = 0.28   # PDF: >28%
MIN_VOLA_SOFT      = 0.35   # Soft-Penalty Zone: 28–35%
IV_SOFT_PENALTY    = 0.10
SPREAD_MAX_PCT     = 0.025
SPREAD_MIN         = 5
MIN_CREDIT_PERCENT = 0.18
MIN_CREDIT_ABS     = 80.0   # PDF: $80 pro Kontrakt
MIN_RISK_REWARD    = 0.22   # PDF: >0.22
MAX_PROBABILITY    = 0.85
MAX_LOSS_PROB      = 0.20
MIN_EV_RATIO       = 0.005
ENTRY_THRESHOLD    = 0.70   # PDF-konform (war 0.60)
TAKE_PROFIT_PCT    = 0.70   # Szenario D: 70% (war 0.50)
STOP_LOSS_MULT     = 2.0
DTE_EXIT           = 0      # deaktiviert (war 21) — Positionen laufen natürlich aus
BUFFER_MIN_PCT     = 0.05
MAX_POSITIONS      = 8
MAX_PER_SECTOR     = 2

# Backtest-spezifisch
HV_WINDOW       = 20     # Tage Rolling-HV (20d reaktiver, 30d=PDF-Methodik)
IV_VRP_FACTOR   = 1.30   # Volatility-Risk-Premium: IV ≈ HV × 1.30
SLIPPAGE        = 0.82   # yfinance-Bid-Faktor (realistische Simulation)
FIXED_DTE       = 52     # Mittelpunkt DTE 45–60


# ── Black-Scholes ─────────────────────────────────────────────────────────────
def _ncdf(x):
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989423 * math.exp(-x * x / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
    return (1 - p) if x > 0 else p

def _bs_put(S, K, T, sigma, r=0.045):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0.0)
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return max(0.0, K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1))
    except Exception:
        return max(K - S, 0.0)

def _bs_prob_otm(S, K, T, sigma, r=0.045):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return max(0.0, min(1.0, _ncdf(d2)))
    except Exception:
        return 1.0 if S > K else 0.0

def _round_strike(strike, price):
    if price >= 500: inc = 10.0
    elif price >= 200: inc = 5.0
    elif price >= 50: inc = 2.5
    else: inc = 1.0
    return round(strike / inc) * inc

def _score(prob_otm, rr, credit, breite, liq_score, iv_pen, earn_pen):
    credit_pct  = credit / (breite * 100) if breite > 0 else 0.0
    rr_norm     = min(rr / MIN_RISK_REWARD, 1.0)
    credit_norm = min(credit_pct / MIN_CREDIT_PERCENT, 1.0)
    return min(1.0, max(0.0,
        0.35 * prob_otm + 0.30 * rr_norm + 0.25 * credit_norm
        + 0.10 * liq_score - iv_pen - earn_pen
    ))


# ── Daten laden ───────────────────────────────────────────────────────────────
def load_data(start_date: str, end_date: str):
    """Lädt historische Kurse und berechnet HV×VRP als IV-Proxy."""
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("❌  pip install yfinance pandas")
        sys.exit(1)

    fetch_from = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=60)).strftime('%Y-%m-%d')
    print(f"📥 Lade Kursdaten für {len(WATCHLIST)} Symbole ({start_date} – {end_date}) ...")
    raw = yf.download(WATCHLIST, start=fetch_from, end=end_date, auto_adjust=True, progress=False)
    if raw.empty:
        print("❌ Keine Daten"); sys.exit(1)

    close = raw['Close'] if 'Close' in raw.columns else raw.xs('Close', axis=1, level=0)

    sym_data = {}  # sym → {date: (price, iv)}
    ok = 0
    for sym in WATCHLIST:
        if sym not in close.columns:
            continue
        s = close[sym].dropna()
        if len(s) < HV_WINDOW + 5:
            continue
        # Rolling-HV annualisiert
        log_ret = s.pct_change().apply(lambda x: math.log1p(max(x, -0.99)))
        hv = log_ret.rolling(HV_WINDOW).std() * math.sqrt(252)
        # Kombinieren: date → (price, iv)
        d = {}
        for ts, price in s.items():
            dt = ts.date() if hasattr(ts, 'date') else ts
            hv_val = float(hv.get(ts, float('nan')))
            if math.isnan(hv_val) or hv_val <= 0:
                continue
            iv = hv_val * IV_VRP_FACTOR
            d[dt] = (float(price), iv)
        if d:
            sym_data[sym] = d
            ok += 1

    print(f"✅ {ok}/{len(WATCHLIST)} Symbole geladen\n")
    return sym_data


# ── Signal-Bewertung ──────────────────────────────────────────────────────────
def evaluate_signal(price, iv):
    """
    Berechnet Strike, Credit und alle Hard-Gates.
    Gibt signal-dict zurück oder None.
    """
    if iv < MIN_VOLA or price <= 0:
        return None

    T = FIXED_DTE / 365
    short_strike = _round_strike(price * (1 - ABSTAND_Y), price)
    if short_strike <= 0:
        return None

    praemie_short = _bs_put(price, short_strike, T, iv)
    spread_max  = max(SPREAD_MIN, round(price * SPREAD_MAX_PCT / 5) * 5)
    breite_ziel = max(SPREAD_MIN, min(math.ceil((praemie_short * 4) / 5) * 5, spread_max))
    long_strike = _round_strike(short_strike - breite_ziel, price)
    if long_strike <= 0 or long_strike >= short_strike:
        long_strike = short_strike - SPREAD_MIN
    breite = short_strike - long_strike
    if breite <= 0:
        return None

    praemie_long = _bs_put(price, long_strike, T, iv)
    raw_net      = praemie_short - praemie_long
    credit_ps    = max(raw_net * SLIPPAGE, 0.0)
    credit       = credit_ps * 100

    if credit_ps <= 0 or breite <= credit_ps:
        return None

    max_risk      = (breite - credit_ps) * 100
    rr            = credit_ps / (breite - credit_ps)
    prob_otm      = _bs_prob_otm(price, short_strike, T, iv)
    prob_max_loss = 1.0 - _bs_prob_otm(price, long_strike, T, iv)
    ev            = (prob_otm * credit) - (prob_max_loss * max_risk)
    ev_ratio      = ev / credit if credit > 0 else 0.0

    # Hard-Gates (identisch zu build_bull_put_spread)
    if prob_otm      > MAX_PROBABILITY:   return None
    if prob_max_loss > MAX_LOSS_PROB:     return None
    if ev_ratio      < MIN_EV_RATIO:      return None
    if credit < max(breite * 100 * MIN_CREDIT_PERCENT, MIN_CREDIT_ABS): return None
    if rr < MIN_RISK_REWARD:              return None

    iv_pen = IV_SOFT_PENALTY if iv < MIN_VOLA_SOFT else 0.0
    sc = _score(prob_otm, rr, credit, breite, 0.5, iv_pen, 0.0)
    if sc < ENTRY_THRESHOLD:
        return None

    return {
        'short_strike': short_strike,
        'long_strike':  long_strike,
        'breite':       breite,
        'credit_ps':    credit_ps,
        'credit':       credit,
        'max_risk':     max_risk,
        'rr':           rr,
        'prob_otm':     prob_otm,
        'prob_max_loss':prob_max_loss,
        'ev':           ev,
        'ev_ratio':     ev_ratio,
        'score':        sc,
        'iv':           iv,
        'entry_price':  price,
    }


# ── Spread-Wert an einem Tag berechnen ───────────────────────────────────────
def spread_value(price, short_s, long_s, iv, dte_left):
    T = max(dte_left / 365, 0.0)
    if T <= 0:
        return max(0.0, short_s - price) - max(0.0, long_s - price)
    return max(0.0, _bs_put(price, short_s, T, iv) - _bs_put(price, long_s, T, iv))


# ── Haupt-Backtest ────────────────────────────────────────────────────────────
def run_backtest(start_date: str, end_date: str):
    sym_data = load_data(start_date, end_date)

    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt   = datetime.strptime(end_date,   '%Y-%m-%d').date()

    # Alle Handelstage aus dem Universum ermitteln
    all_dates_set = set()
    for d in sym_data.values():
        all_dates_set |= set(d.keys())
    all_dates = sorted(d for d in all_dates_set if start_dt <= d <= end_dt)

    print(f"🔁 Simuliere {len(all_dates)} Handelstage ({start_date} – {end_date}) ...")
    print(f"   Universum: {len(sym_data)} Symbole | VRP-Faktor: {IV_VRP_FACTOR}× | "
          f"Slippage: {SLIPPAGE:.0%} | MAX_POS: {MAX_POSITIONS}\n")

    open_positions: dict = {}       # sym → {entry_date, expiry_date, sig}
    sector_counts: dict  = defaultdict(int)
    trades: list         = []
    daily_pnl: dict      = {}
    filter_stats         = defaultdict(int)  # warum geblockt?

    for day in all_dates:
        day_pnl = 0.0

        # ── 1. Exits prüfen ───────────────────────────────────────────────────
        to_close = []
        for sym, pos in list(open_positions.items()):
            sig       = pos['sig']
            short_s   = sig['short_strike']
            long_s    = sig['long_strike']
            credit_ps = sig['credit_ps']
            iv        = sig['iv']
            expiry_dt = pos['expiry_date']
            entry_dt  = pos['entry_date']

            # Tagespreis holen
            day_entry = sym_data[sym].get(day)
            if day_entry is None:
                continue
            price     = day_entry[0]
            dte_left  = max(0, (expiry_dt - day).days)
            sv        = spread_value(price, short_s, long_s, iv, dte_left)

            tp_thr = credit_ps * (1 - TAKE_PROFIT_PCT)
            sl_thr = credit_ps * STOP_LOSS_MULT

            if dte_left <= 0:
                reason = 'EXPIRY'
            elif sv <= tp_thr:
                reason = 'TAKE_PROFIT'
            elif sv >= sl_thr:
                reason = 'STOP_LOSS'
            elif dte_left <= DTE_EXIT and (price - short_s) / price < BUFFER_MIN_PCT:
                reason = 'DTE_EXIT'
            else:
                reason = None

            if reason:
                pnl = (credit_ps - sv) * 100
                to_close.append((sym, pos, pnl, reason))

        for sym, pos, pnl, reason in to_close:
            sec = SECTOR_MAP.get(sym, '?')
            sector_counts[sec] = max(0, sector_counts[sec] - 1)
            del open_positions[sym]
            day_pnl += pnl
            dte_held = (day - pos['entry_date']).days
            trades.append({
                'symbol':       sym,
                'sector':       sec,
                'entry_date':   pos['entry_date'].isoformat(),
                'exit_date':    day.isoformat(),
                'dte_held':     dte_held,
                'short_strike': pos['sig']['short_strike'],
                'long_strike':  pos['sig']['long_strike'],
                'iv':           round(pos['sig']['iv'], 4),
                'credit':       round(pos['sig']['credit'], 2),
                'pnl':          round(pnl, 2),
                'exit_reason':  reason,
                'score':        round(pos['sig']['score'], 3),
                'prob_otm':     round(pos['sig']['prob_otm'], 3),
                'rr':           round(pos['sig']['rr'], 3),
            })

        daily_pnl[day] = round(day_pnl, 2)

        # ── 2. Neue Signale suchen ────────────────────────────────────────────
        slots = MAX_POSITIONS - len(open_positions)
        if slots <= 0:
            continue

        candidates = []
        for sym in WATCHLIST:
            if sym in open_positions:
                continue
            if sym not in sym_data:
                continue
            day_entry = sym_data[sym].get(day)
            if day_entry is None:
                continue
            price, iv = day_entry

            sig = evaluate_signal(price, iv)
            if sig is None:
                filter_stats['signal_fail'] += 1
                continue

            sec = SECTOR_MAP.get(sym, '?')
            if sector_counts[sec] >= MAX_PER_SECTOR:
                filter_stats['sector_limit'] += 1
                continue

            candidates.append((sym, sig, sec))

        # Beste nach Score auswählen
        candidates.sort(key=lambda x: x[1]['score'], reverse=True)
        for sym, sig, sec in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            if sym in open_positions:
                continue
            expiry_dt = day + timedelta(days=FIXED_DTE)
            open_positions[sym] = {
                'entry_date':  day,
                'expiry_date': expiry_dt,
                'sig':         sig,
            }
            sector_counts[sec] += 1

    # ── Noch offene Positionen: Forced Close am letzten Handelstag ───────────
    last_day = all_dates[-1] if all_dates else end_dt
    for sym, pos in list(open_positions.items()):
        sig       = pos['sig']
        day_entry = sym_data[sym].get(last_day)
        price     = day_entry[0] if day_entry else sig['entry_price']
        dte_left  = max(0, (pos['expiry_date'] - last_day).days)
        sv        = spread_value(price, sig['short_strike'], sig['long_strike'], sig['iv'], dte_left)
        pnl       = (sig['credit_ps'] - sv) * 100
        sec       = SECTOR_MAP.get(sym, '?')
        trades.append({
            'symbol':       sym,
            'sector':       sec,
            'entry_date':   pos['entry_date'].isoformat(),
            'exit_date':    last_day.isoformat(),
            'dte_held':     (last_day - pos['entry_date']).days,
            'short_strike': sig['short_strike'],
            'long_strike':  sig['long_strike'],
            'iv':           round(sig['iv'], 4),
            'credit':       round(sig['credit'], 2),
            'pnl':          round(pnl, 2),
            'exit_reason':  'END_OF_BACKTEST',
            'score':        round(sig['score'], 3),
            'prob_otm':     round(sig['prob_otm'], 3),
            'rr':           round(sig['rr'], 3),
        })

    return trades, daily_pnl, filter_stats


# ── Ausgabe ───────────────────────────────────────────────────────────────────
def print_results(trades, daily_pnl, filter_stats, start_date, end_date):
    if not trades:
        print("⚠️  Keine Trades — Filter zu restriktiv oder Zeitraum zu kurz.")
        n_sig = filter_stats.get('signal_fail', 0)
        n_sec = filter_stats.get('sector_limit', 0)
        print(f"   Signal-Fails: {n_sig}  |  Sektor-Limit: {n_sec}")
        return

    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    n      = len(trades)
    total  = sum(t['pnl'] for t in trades)
    avg    = total / n
    gross_w = sum(t['pnl'] for t in wins)
    gross_l = abs(sum(t['pnl'] for t in losses))
    avg_w  = gross_w / len(wins)   if wins   else 0.0
    avg_l  = sum(t['pnl'] for t in losses) / len(losses) if losses else 0.0
    pf     = gross_w / gross_l if gross_l > 0 else float('inf')
    wr     = len(wins) / n

    # Drawdown (kumulativ über sortierte Tage)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for d in sorted(daily_pnl):
        cum += daily_pnl[d]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # Trades/Tag
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt   = datetime.strptime(end_date,   '%Y-%m-%d')
    cal_days = max(1, (end_dt - start_dt).days)
    trading_days = cal_days * 5 / 7
    trades_per_day = n / trading_days

    # ø DTE gehalten
    avg_dte = sum(t['dte_held'] for t in trades) / n

    # Exit-Gründe
    exits = defaultdict(list)
    for t in trades:
        exits[t['exit_reason']].append(t['pnl'])

    # Sektor
    by_sec = defaultdict(list)
    for t in trades:
        by_sec[t['sector']].append(t['pnl'])

    # Symbol
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t['symbol']].append(t['pnl'])

    S = '─' * 66
    print(f"\n{'═'*66}")
    print(f"  BACKTEST  {start_date} – {end_date}")
    print(f"{'═'*66}")
    print(f"  Trades gesamt:        {n:>5}")
    print(f"  ø Trades/Tag:         {trades_per_day:>5.2f}")
    print(f"  ø Haltedauer:         {avg_dte:>5.1f} Tage")
    print(f"  Win-Rate:             {wr:>5.1%}  ({len(wins)}W / {len(losses)}L)")
    print(f"  Gesamt-P&L:          ${total:>+8.0f}")
    print(f"  ø P&L/Trade:         ${avg:>+7.2f}")
    print(f"  ø Gewinn (Wins):      ${avg_w:>+7.2f}")
    print(f"  ø Verlust (Losses):   ${avg_l:>+7.2f}")
    print(f"  Profit-Faktor:        {pf:>5.2f}×  (Bruttogewinn/Bruttoverlust)")
    print(f"  Max Drawdown:        ${max_dd:>8.0f}")

    print(f"\n{S}")
    print(f"  Exit-Gründe:")
    for reason, pnls in sorted(exits.items(), key=lambda x: -len(x[1])):
        pct  = len(pnls) / n
        ap   = sum(pnls) / len(pnls)
        wr_r = sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"    {reason:<22} {len(pnls):>4}× ({pct:.0%})  ø ${ap:>+7.2f}  Win {wr_r:.0%}")

    print(f"\n{S}")
    print(f"  Sektor-Performance:")
    for sec, pnls in sorted(by_sec.items(), key=lambda x: -sum(x[1])):
        wr_s = sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"    {sec:<14} {len(pnls):>4}×  Win {wr_s:.0%}  Σ ${sum(pnls):>+7.0f}  ø ${sum(pnls)/len(pnls):>+6.2f}")

    print(f"\n{S}")
    sym_sorted = sorted(by_sym.items(), key=lambda x: sum(x[1]), reverse=True)
    n5 = min(5, len(sym_sorted))
    print(f"  Top-{n5} Symbole (P&L gesamt):")
    for sym, pnls in sym_sorted[:n5]:
        wr_s = sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"    {sym:<6}  {len(pnls):>3}×  ${sum(pnls):>+7.0f}  Win {wr_s:.0%}  ø ${sum(pnls)/len(pnls):>+6.2f}")
    if len(sym_sorted) > 5:
        print(f"  Flop-{n5} Symbole (P&L gesamt):")
        for sym, pnls in sym_sorted[-n5:]:
            wr_s = sum(1 for p in pnls if p > 0) / len(pnls)
            print(f"    {sym:<6}  {len(pnls):>3}×  ${sum(pnls):>+7.0f}  Win {wr_s:.0%}  ø ${sum(pnls)/len(pnls):>+6.2f}")

    print(f"\n{'═'*66}")
    print(f"  ⚠️  VEREINFACHTER BACKTEST — nur Orientierungswerte!")
    print(f"     IV = HV×{IV_VRP_FACTOR}  |  Slippage {SLIPPAGE:.0%}  |  kein echter Options-Feed")
    print(f"     Keine Earnings/Makro-Events  |  Expiry = Entry + {FIXED_DTE} Tage")
    print(f"{'═'*66}\n")

    # CSV
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest_trades.csv')
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    print(f"  📄 Trade-Log → {out_path}")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    args       = sys.argv[1:]
    start_date = args[0] if len(args) >= 1 else '2023-01-01'
    end_date   = args[1] if len(args) >= 2 else datetime.now().strftime('%Y-%m-%d')

    print(f"🔬 Bull-Put-Spread Backtest  |  {start_date} – {end_date}")
    print(f"   IV = HV×{IV_VRP_FACTOR} | Slippage {SLIPPAGE:.0%} | TP {TAKE_PROFIT_PCT:.0%} | "
          f"SL {STOP_LOSS_MULT:.0f}× | DTE {FIXED_DTE}\n")

    trades, daily_pnl, filter_stats = run_backtest(start_date, end_date)
    print_results(trades, daily_pnl, filter_stats, start_date, end_date)
