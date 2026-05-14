import math
import asyncio
import os
import sys
import json
import queue
import random
import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Writable base dir: Application Support (frozen) or next to bot.py (dev)
if getattr(sys, 'frozen', False):
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
    _BASE = os.path.dirname(os.path.abspath(__file__))

# Load .env file automatically (no extra dependencies needed)
_env_path = os.path.join(_BASE, '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Config laden (config.json) ───────────────────────────────────────────────
import json as _json
_cfg_path = os.path.join(_BASE, 'config.json')
_cfg_defaults = {
    "ib_host": "127.0.0.1", "ib_port": 7497, "ib_account": "",
    "min_vola": 0.28, "abstand_y": 0.10, "min_credit": 70,
    "min_risk_reward": 0.20, "max_delta": 0.28, "max_positions": 8,
    "max_per_sector": 2, "scan_intervall": 60, "auto_trade": True,
    "take_profit_pct": 0.50, "stop_loss_mult": 2.0, "dte_exit": 21,
    "min_available_funds": 2000,
}
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path) as _f:
            _cfg = {**_cfg_defaults, **_json.load(_f)}
    except Exception:
        _cfg = dict(_cfg_defaults)
else:
    _cfg = dict(_cfg_defaults)
# ────────────────────────────────────────────────────────────────────────────

# ── Logging: Terminal + trades.log ──────────────────────────────────────────
_log_path = os.path.join(_BASE, 'trades.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(_log_path, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
# ib_insync produziert massenhaft position/updatePortfolio Logs — nur Fehler zeigen
logging.getLogger('ib_insync').setLevel(logging.ERROR)
_log_queue: queue.Queue = queue.Queue()

def log(msg: str):
    logging.info(msg)
    try:
        _log_queue.put_nowait(msg + '\n')
    except Exception:
        pass
# ────────────────────────────────────────────────────────────────────────────

MIN_AVAILABLE_FUNDS = int(_cfg['min_available_funds'])

# eventkit (ib_insync dependency) calls get_event_loop() at import time.
# Python 3.10+ no longer auto-creates a loop, so we must set one first.
asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *

# --- STRATEGIE-VARIABLEN ---
WATCHLIST        = [
    # Mega-Cap Tech (10)
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'CSCO', 'IBM', 'DELL', 'AMAT',
    # Halbleiter (12)
    'AMD', 'AVGO', 'QCOM', 'MU', 'TSM', 'INTC', 'TXN', 'LRCX', 'KLAC', 'MRVL', 'ON', 'ARM',
    # Software & Cloud (12)
    'CRM', 'ORCL', 'NOW', 'ADBE', 'PLTR', 'WDAY', 'SNOW', 'PANW', 'CRWD', 'FTNT', 'DDOG', 'APP',
    # Consumer Tech / EV (8)
    'TSLA', 'NFLX', 'UBER', 'SHOP', 'LYFT', 'PINS', 'DASH', 'RBLX',
    # Fintech & Krypto (7)
    'COIN', 'PYPL', 'V', 'MA', 'SQ', 'AFRM', 'SOFI',
    # Banken & Finanzen (11)
    'JPM', 'GS', 'MS', 'BAC', 'WFC', 'C', 'AXP', 'SCHW', 'BLK', 'BX', 'USB',
    # Pharma / Healthcare (13)
    'LLY', 'JNJ', 'UNH', 'ABBV', 'PFE', 'MRK', 'BMY', 'AMGN', 'MDT', 'ABT', 'CVS', 'GILD', 'VRTX',
    # Energie (8)
    'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY', 'MPC', 'VLO',
    # Retail & Consumer (11)
    'WMT', 'COST', 'TGT', 'HD', 'LOW', 'NKE', 'SBUX', 'MCD', 'CMG', 'DG', 'LULU',
    # Industrie & Aerospace (10)
    'CAT', 'DE', 'HON', 'GE', 'LMT', 'RTX', 'BA', 'NOC', 'EMR', 'MMM',
    # Telecom (3)
    'T', 'VZ', 'TMUS',
    # Versorger & REITs (4)
    'NEE', 'AMT', 'PLD', 'DUK',
    # Rohstoffe & Materialien (4)
    'LIN', 'NEM', 'FCX', 'AA',
    # Food & Beverages (4)
    'KO', 'PEP', 'PM', 'MO',
    # Travel & Leisure (3)
    'ABNB', 'BKNG', 'MAR',
]  # gesamt: 120
MIN_VOLA         = float(_cfg['min_vola'])
MIN_IV_SPIKE     = 0.05
ABSTAND_Y        = float(_cfg['abstand_y'])
SPREAD_MAX_PCT   = 0.025
SPREAD_MIN       = 5
MIN_CREDIT       = int(_cfg['min_credit'])
MIN_RISK_REWARD  = float(_cfg['min_risk_reward'])
MAX_DELTA        = float(_cfg['max_delta'])
MIN_PROBABILITY  = 0.72
MAX_PROBABILITY  = 0.85
MAX_LOSS_PROB    = 0.20
MIN_EV_RATIO     = 0.005
RATIO_TOLERANCE  = 0.20
MIN_DTE          = 45
MAX_DTE          = 60
SCAN_INTERVALL   = int(_cfg['scan_intervall'])
MAX_POSITIONS    = int(_cfg['max_positions'])
MAX_PER_SECTOR   = int(_cfg['max_per_sector'])
AUTO_TRADE       = bool(_cfg['auto_trade'])

# Sektor-Zuordnung für Diversifikations-Check
SECTOR_MAP = {
    # Tech
    'AAPL': 'Tech',    'MSFT': 'Tech',    'GOOGL': 'Tech',  'AMZN': 'Tech',
    'META': 'Tech',    'CSCO': 'Tech',    'IBM': 'Tech',    'DELL': 'Tech',
    'AMAT': 'Tech',
    # Halbleiter
    'NVDA': 'Halbleiter','AMD': 'Halbleiter', 'AVGO': 'Halbleiter', 'QCOM': 'Halbleiter',
    'MU': 'Halbleiter',  'TSM': 'Halbleiter', 'INTC': 'Halbleiter',
    'TXN': 'Halbleiter', 'LRCX': 'Halbleiter','KLAC': 'Halbleiter',
    'MRVL': 'Halbleiter','ON': 'Halbleiter',  'ARM': 'Halbleiter',
    # Software
    'CRM': 'Software',  'ORCL': 'Software', 'NOW': 'Software',  'ADBE': 'Software',
    'PLTR': 'Software', 'WDAY': 'Software', 'SNOW': 'Software', 'PANW': 'Software',
    'CRWD': 'Software', 'FTNT': 'Software', 'DDOG': 'Software', 'APP': 'Software',
    # ConsumerTech
    'TSLA': 'ConsumerTech', 'NFLX': 'ConsumerTech', 'UBER': 'ConsumerTech',
    'SHOP': 'ConsumerTech', 'LYFT': 'ConsumerTech', 'PINS': 'ConsumerTech',
    'DASH': 'ConsumerTech', 'RBLX': 'ConsumerTech',
    # Fintech
    'COIN': 'Fintech', 'PYPL': 'Fintech', 'V': 'Fintech',  'MA': 'Fintech',
    'SQ': 'Fintech',   'AFRM': 'Fintech', 'SOFI': 'Fintech',
    # Banken
    'JPM': 'Banken', 'GS': 'Banken',   'MS': 'Banken',  'BAC': 'Banken',
    'WFC': 'Banken', 'C': 'Banken',    'AXP': 'Banken', 'SCHW': 'Banken',
    'BLK': 'Banken', 'BX': 'Banken',   'USB': 'Banken',
    # Healthcare
    'LLY': 'Healthcare', 'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'ABBV': 'Healthcare',
    'PFE': 'Healthcare', 'MRK': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare',
    'MDT': 'Healthcare', 'ABT': 'Healthcare', 'CVS': 'Healthcare', 'GILD': 'Healthcare',
    'VRTX': 'Healthcare',
    # Energie
    'XOM': 'Energie', 'CVX': 'Energie', 'COP': 'Energie', 'EOG': 'Energie',
    'SLB': 'Energie', 'OXY': 'Energie', 'MPC': 'Energie', 'VLO': 'Energie',
    # Retail
    'WMT': 'Retail', 'COST': 'Retail', 'TGT': 'Retail', 'HD': 'Retail',
    'LOW': 'Retail',  'NKE': 'Retail',  'SBUX': 'Retail','MCD': 'Retail',
    'CMG': 'Retail',  'DG': 'Retail',   'LULU': 'Retail',
    # Industrie
    'CAT': 'Industrie', 'DE': 'Industrie',  'HON': 'Industrie', 'GE': 'Industrie',
    'LMT': 'Industrie', 'RTX': 'Industrie', 'BA': 'Industrie',  'NOC': 'Industrie',
    'EMR': 'Industrie', 'MMM': 'Industrie',
    # Telecom
    'T': 'Telecom', 'VZ': 'Telecom', 'TMUS': 'Telecom',
    # Versorger
    'NEE': 'Versorger', 'AMT': 'Versorger', 'PLD': 'Versorger', 'DUK': 'Versorger',
    # Rohstoffe
    'LIN': 'Rohstoffe', 'NEM': 'Rohstoffe', 'FCX': 'Rohstoffe', 'AA': 'Rohstoffe',
    # Food
    'KO': 'Food', 'PEP': 'Food', 'PM': 'Food', 'MO': 'Food',
    # Travel
    'ABNB': 'Travel', 'BKNG': 'Travel', 'MAR': 'Travel',
}

# --- EXIT-MANAGEMENT ---
TAKE_PROFIT_PCT       = float(_cfg['take_profit_pct'])
STOP_LOSS_MULT        = float(_cfg['stop_loss_mult'])
BREAKEVEN_TRIGGER_PCT = 0.25
DTE_EXIT              = int(_cfg['dte_exit'])
BUFFER_MIN_PCT        = 0.05
# -----------------------

# Schlüsselwörter für Gewinnwarnung in News-Headlines
WARNING_KEYWORDS = [
    'profit warning', 'earnings warning', 'guidance cut', 'lowers guidance',
    'below expectations', 'misses estimates', 'lowers forecast', 'revenue warning',
    'downgrade', 'cuts outlook', 'weak outlook', 'disappoints',
    'gewinnwarnung', 'umsatzwarnung', 'gewinneinbruch', 'prognose gesenkt',
]
# ---------------------------

def _now_et() -> datetime:
    """Aktuelle Zeit in America/New_York — mit Fallback auf UTC-4 (EDT) falls tzdata fehlt."""
    try:
        return datetime.now(ZoneInfo('America/New_York'))
    except Exception:
        from datetime import timezone
        edt = timezone(timedelta(hours=-4))
        return datetime.now(edt)

def is_market_open() -> bool:
    """NYSE offen: Mo–Fr 09:30–16:00 ET (15:30–22:00 MEZ/15:30–22:00 MESZ)."""
    now_et = _now_et()
    if now_et.weekday() >= 5:
        return False
    open_t  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now_et < close_t

def seconds_until_market_open() -> tuple:
    """Gibt (Sekunden, nächste Öffnungszeit ET) bis zur nächsten NYSE-Öffnung zurück."""
    now_et = _now_et()
    days_ahead = 0
    while True:
        check = (now_et + timedelta(days=days_ahead)).replace(
            hour=9, minute=30, second=0, microsecond=0)
        if check.weekday() < 5 and check > now_et:
            break
        days_ahead += 1
    secs = max(60, int((check - now_et).total_seconds()))
    return secs, check

# Speichert IV vom letzten Scan pro Symbol — für Spike-Erkennung
_iv_memory: dict = {}
# Speichert aktive Bot-Trades für Exit-Monitoring
_bot_trades: dict = {}

_STATE_FILE     = os.path.join(_BASE, '.bot_state.json')
_HISTORY_FILE   = os.path.join(_BASE, 'trade_history.json')
_POSITIONS_FILE = os.path.join(_BASE, 'positions.json')

def _write_positions_file():
    """Schreibt offene Positionen für den Launcher (Live-Anzeige im Historie-Tab)."""
    try:
        positions = []
        for sym, info in _bot_trades.items():
            if info.get('status') in ('done', 'failed'):
                continue
            try:
                exp_date = datetime.strptime(info.get('expiry_yf', ''), '%Y-%m-%d')
                dte = max(0, (exp_date.date() - datetime.now().date()).days)
            except Exception:
                dte = 0
            entry = info.get('entry_per_share', 0.0)
            positions.append({
                'symbol':          sym,
                'expiry':          info.get('expiry_yf', ''),
                'dte':             dte,
                'short_strike':    info.get('short_strike', 0),
                'long_strike':     info.get('long_strike', 0),
                'entry_per_share': round(entry, 2),
                'tp_target':       round(entry * 0.5, 2),
                'status':          info.get('status', 'open'),
                'opened_at':       info.get('opened_at', ''),
                'unrealized_pnl':  info.get('unrealized_pnl'),  # None wenn noch nicht berechnet
            })
        with open(_POSITIONS_FILE, 'w') as f:
            json.dump({
                'updated': datetime.now().strftime('%H:%M:%S'),
                'positions': positions,
            }, f, indent=2)
    except Exception:
        pass

def _append_history(symbol: str, info: dict, exit_per_share: float = 0.0):
    """Hängt einen abgeschlossenen Trade an trade_history.json an."""
    try:
        history = []
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE) as f:
                history = json.load(f)
        entry = info.get('entry_per_share', 0.0)
        pnl   = round((entry - exit_per_share) * 100, 2)
        history.append({
            'symbol':          symbol,
            'expiry':          info.get('expiry_yf', ''),
            'short_strike':    info.get('short_strike', 0),
            'long_strike':     info.get('long_strike', 0),
            'entry_per_share': round(entry, 2),
            'exit_per_share':  round(exit_per_share, 2),
            'pnl':             pnl,
            'status':          info.get('status', 'done'),
            'closed_at':       datetime.now().strftime('%Y-%m-%d %H:%M'),
        })
        with open(_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

def _load_state():
    """Lädt aktive Spread-Positionen vom letzten Lauf — verhindert Duplikate nach Neustart.
    Gecancelte/failed Einträge werden NICHT geladen: sie würden Symbole dauerhaft sperren."""
    if not os.path.exists(_STATE_FILE):
        return
    try:
        import json
        with open(_STATE_FILE) as f:
            data = json.load(f)
        loaded = 0
        for sym, info in data.items():
            # Nur echte aktive Positionen laden (haben short_conid gesetzt)
            if info.get('status') in ('open', 'closing') and info.get('short_conid') and sym not in _bot_trades:
                _bot_trades[sym] = info
                loaded += 1
        if loaded:
            log(f"   {loaded} aktive Spread-Position(en) aus State-File geladen")
    except Exception:
        pass

def _save_state():
    """Schreibt aktive Spread-Positionen auf Disk (nur open/closing mit short_conid)."""
    try:
        import json
        data = {sym: info
                for sym, info in _bot_trades.items()
                if info.get('status') in ('open', 'closing') and info.get('short_conid')}
        with open(_STATE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

def _cancel_order_by_id(ib, order_id: int, symbol: str, label: str):
    """Storniert eine offene IBKR-Order anhand ihrer ID."""
    if not order_id:
        return
    try:
        for t in ib.openTrades():
            if t.order.orderId == order_id:
                ib.cancelOrder(t.order)
                log(f"  🗑  [{symbol}] {label}-Order #{order_id} storniert")
                return
    except Exception as e:
        log(f"  ⚠️  [{symbol}] Konnte {label}-Order #{order_id} nicht stornieren: {e}")

def _on_order_status(trade):
    """IBKR Event-Handler: aktualisiert _bot_trades wenn Order gecancelt oder gefüllt wird."""
    sym = trade.contract.symbol
    if sym not in _bot_trades:
        return
    status = trade.orderStatus.status
    if status in ('Cancelled', 'ApiCancelled', 'Inactive'):
        _bot_trades[sym]['status'] = 'cancelled'
        log(f"  ⚠️  [{sym}] Order gecancelt — Symbol für diese Session gesperrt")
        _save_state()
    elif status == 'Filled':
        if _bot_trades[sym].get('status') == 'closing':
            exit_fill = abs(trade.orderStatus.avgFillPrice or 0)
            _bot_trades[sym]['status'] = 'done'
            _append_history(sym, _bot_trades[sym], exit_per_share=exit_fill)
            log(f"  ✅ [{sym}] Exit-Order gefüllt — Position geschlossen")
        else:
            _bot_trades[sym]['status'] = 'open'
            fill = trade.orderStatus.avgFillPrice
            if fill and fill > 0:
                _bot_trades[sym]['entry_per_share'] = abs(fill)
                log(f"  📋 [{sym}] Entry-Fill: ${abs(fill):.2f}/Share")
        _save_state()

def _bs_put(S, K, T, sigma, r=0.045):
    """Black-Scholes put price — fallback wenn kein echtes Bid verfügbar."""
    if T <= 0:
        return max(K - S, 0.0)
    def ncdf(x):
        t = 1.0 / (1.0 + 0.2316419 * abs(x))
        d = 0.3989423 * math.exp(-x * x / 2)
        p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
        return (1 - p) if x > 0 else p
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)

def _bs_prob_otm(S, K, T, sigma, r=0.045):
    """Wahrscheinlichkeit, dass Put OTM verfällt = N(d2) = Gewinnwahrscheinlichkeit für Short Put."""
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    t = 1.0 / (1.0 + 0.2316419 * abs(d2))
    p = 0.3989423 * math.exp(-d2 * d2 / 2) * t * (
        0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
    return (1 - p) if d2 > 0 else p

async def get_market_data(symbol):
    """Hole Kurs und ATM-IV via yfinance."""
    def _fetch():
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        # fast_info kann bei manchen yfinance-Versionen mit _dividends-Bug crashen
        try:
            price = ticker.fast_info['last_price']
        except Exception:
            hist = ticker.history(period='1d')
            price = float(hist['Close'].iloc[-1]) if not hist.empty else None
        if not price or price != price:
            return None, None
        expirations = ticker.options
        if not expirations:
            return price, None
        today = datetime.now()
        dte_map = [(e, (datetime.strptime(e, '%Y-%m-%d') - today).days) for e in expirations]
        valid = [e for e, d in dte_map if MIN_DTE <= d <= MAX_DTE]
        if not valid:
            # Fallback: Expiry am nächsten an MIN_DTE, mindestens 14 DTE (verhindert 0-IV Weeklies)
            candidates = [(e, d) for e, d in dte_map if d >= 14]
            expiry = min(candidates, key=lambda x: abs(x[1] - MIN_DTE))[0] if candidates else expirations[-1]
        else:
            expiry = valid[0]
        puts = ticker.option_chain(expiry).puts
        if puts.empty:
            return price, None
        atm_idx = (puts['strike'] - price).abs().idxmin()
        iv = puts.loc[atm_idx, 'impliedVolatility']
        return price, float(iv) if iv == iv else None
    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        log(f"   [{symbol}] ❌ yfinance Fehler: {e}")
        return None, None

async def check_news_trigger(symbol):
    """Sucht in yfinance-News nach Gewinnwarnung-Keywords.
    Gibt (True, headline) zurück wenn gefunden, sonst (False, None)."""
    def _fetch():
        import yfinance as yf
        news = yf.Ticker(symbol).news or []
        for item in news:
            title = (item.get('content', {}).get('title') or item.get('title') or '').lower()
            for kw in WARNING_KEYWORDS:
                if kw in title:
                    return True, title
        return False, None
    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        return False, None

async def fetch_signal(symbol, preis, iv):
    """
    Berechnet den Bull-Put-Spread für ein Symbol.
    Gibt ein Signal-Dict zurück oder None wenn kein handelbares Setup gefunden.
    """
    def _fetch_chain():
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        today = datetime.now()
        dte_map = [(e, (datetime.strptime(e, '%Y-%m-%d') - today).days)
                   for e in ticker.options]
        valid = [e for e, d in dte_map if MIN_DTE <= d <= MAX_DTE]
        if not valid:
            # Fallback: Expiry am nächsten an MIN_DTE, mindestens 21 DTE
            candidates = [(e, d) for e, d in dte_map if d >= 21]
            if not candidates:
                return None, None, None
            expiry_str = min(candidates, key=lambda x: abs(x[1] - MIN_DTE))[0]
        else:
            expiry_str = valid[0]
        puts = ticker.option_chain(expiry_str).puts
        dte = (datetime.strptime(expiry_str, '%Y-%m-%d') - today).days
        return expiry_str, puts, dte

    try:
        expiry_yf, puts, dte = await asyncio.to_thread(_fetch_chain)
        if puts is None or puts.empty:
            return None

        # Short Strike: nächster echter Strike ~OTM unter Kurs
        target = preis * (1 - ABSTAND_Y)
        otm_puts = puts[puts['strike'] <= preis]
        if otm_puts.empty:
            otm_puts = puts
        short_row = otm_puts.loc[(otm_puts['strike'] - target).abs().idxmin()]
        short_strike = float(short_row['strike'])

        # Prämie: Short-Bid für Spread-Breiten-Berechnung
        bid = float(short_row['bid'])
        if bid > 0 and bid == bid:
            praemie = bid
            praemie_quelle = "yfinance (Bid)"
        else:
            T = max(dte / 365, 0.001)
            praemie = _bs_put(preis, short_strike, T, iv)
            praemie_quelle = "Black-Scholes (geschätzt)"

        # Long Strike
        spread_max  = max(SPREAD_MIN, round(preis * SPREAD_MAX_PCT / 5) * 5)  # skaliert mit Kurs
        breite_ziel = max(SPREAD_MIN, min(math.ceil((praemie * 4) / 5) * 5, spread_max))
        candidates = sorted(puts[puts['strike'] < short_strike]['strike'].tolist())
        if candidates:
            long_target = short_strike - breite_ziel
            long_strike = float(min(candidates, key=lambda s: abs(s - long_target)))
        else:
            long_strike = short_strike - breite_ziel
        breite = short_strike - long_strike

        # Netto-Credit: Short Bid - Long Ask (realistischer als nur Short Bid)
        if praemie_quelle == "yfinance (Bid)":
            long_rows = puts[puts['strike'] == long_strike]
            if not long_rows.empty:
                long_ask_yf = float(long_rows.iloc[0]['ask'])
                if long_ask_yf > 0 and long_ask_yf == long_ask_yf:
                    praemie = max(bid - long_ask_yf, 0.01)
                    praemie_quelle = "yfinance (Net Bid-Ask)"

        credit    = praemie * 100
        max_risk  = (breite - praemie) * 100
        rr        = praemie / (breite - praemie) if breite > praemie else 0.0
        T         = max(dte / 365, 0.001)
        prob_otm      = _bs_prob_otm(preis, short_strike, T, iv)
        prob_max_loss = 1.0 - _bs_prob_otm(preis, long_strike, T, iv)

        # Erwartungswert: (P_Gewinn × Credit) − (P_MaxVerlust × MaxRisk)
        # Vereinfachung nach dem Modell des Nutzers — ignoriert Teilzonen (Breakeven-Bereich)
        ev       = (prob_otm * credit) - (prob_max_loss * max_risk)
        ev_ratio = ev / credit if credit > 0 else 0.0

        # Score = EV-Ratio × IV-Stärke: kombiniert statistischen Vorteil und Prämienqualität
        score    = ev_ratio * (iv / MIN_VOLA)

        return {
            'symbol':        symbol,
            'preis':         preis,
            'iv':            iv,
            'dte':           dte,
            'expiry_ib':     expiry_yf.replace('-', ''),
            'short_strike':  short_strike,
            'long_strike':   long_strike,
            'breite':        breite,
            'praemie':       praemie,
            'praemie_quelle': praemie_quelle,
            'credit':        credit,
            'max_risk':      max_risk,
            'risk_reward':   rr,
            'prob_otm':      prob_otm,
            'prob_max_loss': prob_max_loss,
            'ev':            ev,
            'ev_ratio':      ev_ratio,
            'score':         score,
        }
    except Exception as e:
        log(f"   [{symbol}] ❌ fetch_signal Fehler: {e}")
        return None

def count_bot_orders():
    """Zählt aktive Spread-Orders des Bots — ignoriert reine Aktien-Positionen."""
    return sum(1 for info in _bot_trades.values()
               if info.get('status') in ('open', 'closing')
               and info.get('short_conid'))

async def has_open_position(ib, symbol):
    try:
        return any(p.contract.symbol == symbol for p in ib.positions())
    except Exception:
        return False

def already_traded(symbol):
    """Prüft ob dieser Bot in dieser Session bereits eine Order für das Symbol platziert hat.
    Blockiert auch 'placing' (läuft gerade) und 'cancelled'/'failed' (nicht nochmal versuchen)."""
    return symbol in _bot_trades and _bot_trades[symbol].get('status') in ('open', 'closing', 'placing', 'cancelled', 'failed', 'done')

async def get_spread_value(symbol, expiry_yf, short_strike, long_strike, ib=None):
    """Aktueller Marktwert des Spreads (= Debit um ihn zurückzukaufen).
    Bevorzugt IBKR modelGreeks; Fallback auf yfinance."""
    # Primär: IBKR modelGreeks (kein Echtzeit-Abo nötig)
    if ib is not None:
        try:
            expiry_ib = expiry_yf.replace('-', '')
            s_contract = Option(symbol, expiry_ib, short_strike, 'P', 'SMART')
            l_contract = Option(symbol, expiry_ib, long_strike,  'P', 'SMART')
            await ib.qualifyContractsAsync(s_contract, l_contract)
            t_s = ib.reqMktData(s_contract, '', False, False)
            t_l = ib.reqMktData(l_contract,  '', False, False)
            await asyncio.sleep(4)
            def _best_ask(t):
                if t.ask and t.ask > 0:      return t.ask
                if t.modelGreeks and t.modelGreeks.optPrice and t.modelGreeks.optPrice > 0:
                    return t.modelGreeks.optPrice
                return None
            def _best_bid(t):
                if t.bid and t.bid > 0:      return t.bid
                if t.modelGreeks and t.modelGreeks.optPrice and t.modelGreeks.optPrice > 0:
                    return t.modelGreeks.optPrice
                return None
            s_ask = _best_ask(t_s)
            l_bid = _best_bid(t_l)
            try: ib.cancelMktData(t_s)
            except Exception: pass
            try: ib.cancelMktData(t_l)
            except Exception: pass
            if s_ask and l_bid:
                return max(0.0, s_ask - l_bid)
        except Exception:
            pass
    # Fallback: yfinance
    def _fetch():
        import yfinance as yf
        puts = yf.Ticker(symbol).option_chain(expiry_yf).puts
        short_ask = puts[puts['strike'] == short_strike]['ask'].values
        long_bid  = puts[puts['strike'] == long_strike]['bid'].values
        if not len(short_ask) or not len(long_bid):
            return None
        return max(0.0, float(short_ask[0]) - float(long_bid[0]))
    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        return None

async def close_spread(ib, symbol, info, reason):
    """Storniert bestehende Bracket-Orders und platziert einen manuellen Exit (DTE-Exit)."""
    try:
        # Bestehende Bracket TP/SL stornieren damit keine doppelten Exit-Orders entstehen
        if ib is not None:
            _cancel_order_by_id(ib, info.get('tp_order_id', 0), symbol, 'TP')
            _cancel_order_by_id(ib, info.get('sl_order_id', 0), symbol, 'SL')

        bag = Bag(
            symbol=symbol, exchange='SMART', currency='USD',
            comboLegs=[
                ComboLeg(conId=info['short_conid'], ratio=1, action='BUY',  exchange='SMART'),
                ComboLeg(conId=info['long_conid'],  ratio=1, action='SELL', exchange='SMART'),
            ]
        )
        entry = info['entry_per_share']
        info['status'] = 'closing'

        # Weicher Exit: 60% des Entry-Credits als Limit — GTC wartet auf Füllung
        close_limit = round(entry * 0.60, 2)
        icon, label = '⏰', f'21-DTE-EXIT (soft) @ ${close_limit:.2f} GTC'
        order = LimitOrder('BUY', 1, close_limit, tif='GTC')

        order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        order.account = _cfg.get('ib_account', '')
        trade = ib.placeOrder(bag, order)
        log(f"  {icon} [{symbol}] EXIT {label} | Order ID: {trade.order.orderId}")
    except Exception as e:
        import traceback
        log(f"  ❌ [{symbol}] Exit-Fehler: {e}\n{traceback.format_exc()}")

async def monitor_exits(ib=None):
    """DTE-Exit und Breakeven-Update. TP/SL werden von IBKR-Bracket-Orders verwaltet."""
    if not _bot_trades:
        return
    for symbol, info in list(_bot_trades.items()):
        if info.get('status') != 'open':
            continue
        if not info.get('expiry_yf'):
            continue

        # 21-DTE-Exit: nur schließen wenn Kurs nah am Short Strike (Gamma-Gefahr)
        dte_remaining = (datetime.strptime(info['expiry_yf'], '%Y-%m-%d') - datetime.now()).days
        if dte_remaining <= DTE_EXIT:
            preis, _ = await get_market_data(symbol)
            if preis is not None and info.get('short_strike'):
                puffer = (preis - info['short_strike']) / preis
                if puffer < BUFFER_MIN_PCT:
                    log(f"  ⏰ [{symbol}] 21-DTE-Exit: Kurs ${preis:.2f} nur {puffer:.1%} über Short Strike "
                        f"${info['short_strike']:.0f} — soft close")
                    await close_spread(ib, symbol, info, 'DTE_EXIT')
                    continue
                else:
                    log(f"  ✅ [{symbol}] 21-DTE erreicht — Puffer {puffer:.1%} > {BUFFER_MIN_PCT:.0%} "
                        f"— tief OTM, verfallen lassen")

        # P&L abrufen für Logging und Breakeven-Management
        current = await get_spread_value(
            symbol, info['expiry_yf'], info['short_strike'], info['long_strike'], ib
        )
        if current is None:
            continue

        entry      = info['entry_per_share']
        pnl_share  = entry - current
        pnl_dollar = pnl_share * 100
        pnl_pct    = (pnl_share / entry * 100) if entry > 0 else 0

        # Breakeven: SL UND TP stornieren, dann neuen Breakeven-SL platzieren
        # (Error 201 vermeiden: IB erlaubt nicht 2 Closing-BUY-Orders gleichzeitig)
        if pnl_share >= entry * BREAKEVEN_TRIGGER_PCT and not info.get('at_breakeven'):
            info['at_breakeven'] = True
            _cancel_order_by_id(ib, info.get('sl_order_id', 0), symbol, 'SL')
            _cancel_order_by_id(ib, info.get('tp_order_id', 0), symbol, 'TP')
            await asyncio.sleep(0.5)   # kurz warten bis Cancel bei IB angekommen
            be_close = round(entry * 1.02, 2)  # entry + 2% Puffer für Slippage
            be_bag = Bag(
                symbol=symbol, exchange='SMART', currency='USD',
                comboLegs=[
                    ComboLeg(conId=info['short_conid'], ratio=1, action='BUY',  exchange='SMART'),
                    ComboLeg(conId=info['long_conid'],  ratio=1, action='SELL', exchange='SMART'),
                ]
            )
            be_order = LimitOrder('BUY', 1, be_close, tif='GTC')
            be_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
            be_order.account = _cfg.get('ib_account', '')
            be_trade = ib.placeOrder(be_bag, be_order)
            info['sl_order_id'] = be_trade.order.orderId
            _save_state()
            log(f"  🔒 [{symbol}] Breakeven-SL @ ${be_close:.2f} GTC gesetzt "
                f"(ID: {be_trade.order.orderId}) | P&L: +${pnl_dollar:.0f}")

        # Unrealized P&L in trade-Info speichern (für Launcher-Anzeige)
        info['unrealized_pnl'] = round(pnl_dollar, 2)

        # P&L Logging
        be_pct  = BREAKEVEN_TRIGGER_PCT * 100
        tp_pct  = TAKE_PROFIT_PCT * 100
        sl_pct  = STOP_LOSS_MULT  * 100
        arrow   = '📈' if pnl_pct >= 0 else '📉'
        be_flag = '  🔒 Breakeven aktiv' if info.get('at_breakeven') else f'  (BE bei +{be_pct:.0f}%)'
        log(f"  {arrow} [{symbol}] {pnl_pct:+.1f}% (${pnl_dollar:+.0f})"
            f"  |  TP: +{tp_pct:.0f}%  SL: -{sl_pct:.0f}%{be_flag}"
            f"  |  Entry ${entry*100:.0f} → jetzt ${current*100:.0f}")

async def place_order(ib, sig):
    """Platziert eine Combo-Order auf IB für ein gegebenes Signal-Dict."""
    try:
        sym = sig['symbol']

        # ── Schritt 1: IBKR-Liste zwingend aktualisieren vor jedem Check ────
        await ib.reqAllOpenOrdersAsync()
        await asyncio.sleep(0.5)  # kurz warten bis interne Liste befüllt ist

        # ── Schritt 2: Symbol-Check gegen live IBKR-Orders (nach Symbol, nicht ID) ─
        active_statuses = {'Submitted', 'PreSubmitted', 'PendingSubmit'}
        open_symbols = {
            t.contract.symbol
            for t in ib.openTrades()
            if t.orderStatus.status in active_statuses
        }
        if sym in open_symbols:
            log(f"  🚫 BLOCKIERT: Order für [{sym}] bereits im Markt — kein Duplikat")
            _bot_trades.setdefault(sym, {'status': 'open', 'entry_per_share': 0,
                                         'at_breakeven': False})
            _save_state()
            return

        # ── Schritt 3: Symbol-Check gegen offene Positionen ─────────────────
        pos_symbols = {
            p.contract.symbol
            for p in ib.positions()
            if p.position != 0
        }
        if sym in pos_symbols:
            log(f"  🚫 BLOCKIERT: Position für [{sym}] bereits im Konto — kein neuer Trade")
            _bot_trades.setdefault(sym, {'status': 'open', 'entry_per_share': 0,
                                         'at_breakeven': False})
            _save_state()
            return

        short_contract = Option(sym, sig['expiry_ib'], sig['short_strike'], 'P', 'SMART')
        long_contract  = Option(sym, sig['expiry_ib'], sig['long_strike'],  'P', 'SMART')

        await ib.qualifyContractsAsync(short_contract, long_contract)
        if not (short_contract.conId > 0 and long_contract.conId > 0):
            log(f"  ❌ [{sym}] Qualifizierung fehlgeschlagen — Order abgebrochen")
            return

        bag = Bag(
            symbol=sym, exchange='SMART', currency='USD',
            comboLegs=[
                ComboLeg(conId=short_contract.conId, ratio=1, action='SELL', exchange='SMART'),
                ComboLeg(conId=long_contract.conId,  ratio=1, action='BUY',  exchange='SMART'),
            ]
        )

        # Echtes IBKR-Netto-Bid berechnen: Short-Bid minus Long-Ask der einzelnen Legs
        # (reqMktData auf Bag erfordert Combo-Abo — Legs sind mit Standard-Options-Abo verfügbar)
        t_short = ib.reqMktData(short_contract, '', False, False)
        t_long  = ib.reqMktData(long_contract,  '', False, False)
        await asyncio.sleep(5)
        short_bid = t_short.bid if t_short.bid and t_short.bid > 0 else None
        long_ask  = t_long.ask  if t_long.ask  and t_long.ask  > 0 else None
        try:
            ib.cancelMktData(t_short)
        except Exception:
            pass
        try:
            ib.cancelMktData(t_long)
        except Exception:
            pass

        if short_bid is None or long_ask is None:
            # Fallback Stufe 1: bidGreeks/askGreeks optPrice
            def _greek_price(ticker, side):
                g = ticker.bidGreeks if side == 'bid' else ticker.askGreeks
                return g.optPrice if g and g.optPrice and g.optPrice > 0 else None

            sb_greek = _greek_price(t_short, 'bid')
            la_greek = _greek_price(t_long,  'ask')

            if sb_greek and la_greek:
                short_bid = sb_greek
                long_ask  = la_greek
                log(f"  ⚠️  [{sym}] Kein Bid/Ask — bidGreeks: Short ${short_bid:.2f}  Long ${long_ask:.2f}")
            else:
                # Fallback Stufe 2: modelGreeks optPrice (IBKR BS-Modell — genauer als Last)
                def _model_price(ticker):
                    g = ticker.modelGreeks
                    return g.optPrice if g and g.optPrice and g.optPrice > 0 else None

                sb_model = _model_price(t_short)
                la_model = _model_price(t_long)

                if sb_model and la_model:
                    short_bid = sb_model
                    long_ask  = la_model
                    log(f"  ⚠️  [{sym}] Kein Bid/Ask — modelGreeks: Short ${short_bid:.2f}  Long ${long_ask:.2f}")
                else:
                    # Fallback Stufe 3: letzter Handelspreis — kann veraltet sein, strenger Abschlag
                    short_last = t_short.last if t_short.last and t_short.last > 0 else None
                    long_last  = t_long.last  if t_long.last  and t_long.last  > 0 else None
                    if short_last and long_last:
                        short_bid = short_last
                        long_ask  = long_last
                        log(f"  ⚠️  [{sym}] Kein Bid/Ask, kein Greek — Last-Preis: Short ${short_last:.2f}  Long ${long_last:.2f}")
                    else:
                        log(f"  ✗ [{sym}] Keine Preisdaten verfügbar — Trade abgebrochen")
                        _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                        return

        ibkr_net = round(short_bid - long_ask, 2)
        has_real_bid = t_short.bid and t_short.bid > 0
        has_model    = not has_real_bid and (t_short.modelGreeks and t_short.modelGreeks.optPrice and t_short.modelGreeks.optPrice > 0)
        discount     = 0.75 if (has_real_bid or has_model) else 0.65
        limit_price  = round(max(ibkr_net * discount, 0.01), 2)
        quelle = "IBKR-Bid" if has_real_bid else ("modelGreeks" if has_model else "Last-Preis-Fallback")
        # Bei theoretischen Preisen (kein echtes Bid) strengeres R/R-Minimum:
        # modelGreeks kann bei illiquiden Options stark vom Markt abweichen (KLAC: 10× daneben)
        rr_minimum = MIN_RISK_REWARD if has_real_bid else MIN_RISK_REWARD * 1.5

        # Delta-Check: IBKR modelGreeks liefert das zuverlässigste Delta
        short_delta = None
        if t_short.modelGreeks and t_short.modelGreeks.delta is not None:
            short_delta = abs(t_short.modelGreeks.delta)
        delta_str = f"Δ={short_delta:.3f}" if short_delta is not None else "Δ=n/a"
        log(f"  📡 [{sym}] {quelle}: Short ${short_bid:.2f}  Long ${long_ask:.2f}  "
              f"Netto: ${ibkr_net:.2f} → Limit ×{discount}: ${limit_price:.2f}  {delta_str}")

        if short_delta is not None and short_delta > MAX_DELTA:
            log(f"  ✗ [{sym}] Delta {short_delta:.3f} > {MAX_DELTA} — Short-Put zu nah am Kurs, Trade abgebrochen")
            _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
            return

        # Beide Checks auf IBKR-Netto (Marktwert), nicht auf dem diskontierten Limit.
        market_rr     = ibkr_net / (sig['breite'] - ibkr_net) if sig['breite'] > ibkr_net else 0.0
        market_credit = ibkr_net * 100

        if market_rr < rr_minimum:
            log(f"  ✗ [{sym}] R/R {market_rr:.2f}x < {rr_minimum:.2f}x ({quelle}) — Trade abgebrochen")
            _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
            return
        if market_credit < MIN_CREDIT:
            log(f"  ✗ [{sym}] Credit ${market_credit:.0f} < ${MIN_CREDIT} (Markt ${ibkr_net:.2f}) — Trade abgebrochen")
            _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
            return

        expiry_yf = sig['expiry_ib'][:4] + '-' + sig['expiry_ib'][4:6] + '-' + sig['expiry_ib'][6:]

        # Registrieren VOR placeOrder — verhindert Duplikate auch wenn Placement danach wirft
        _bot_trades[sym] = {
            'entry_per_share': limit_price,
            'expiry_yf':       expiry_yf,
            'short_strike':    sig['short_strike'],
            'long_strike':     sig['long_strike'],
            'short_conid':     short_contract.conId,
            'long_conid':      long_contract.conId,
            'status':          'open',
            'at_breakeven':    False,
            'tp_order_id':     0,
            'sl_order_id':     0,
            'opened_at':       datetime.now().strftime('%Y-%m-%d %H:%M'),
        }

        # ── Bracket-Order: Entry + TP + SL, alle GTC ─────────────────────────
        # Preise
        tp_close = max(round(limit_price * (1 - TAKE_PROFIT_PCT), 2), 0.01)
        sl_close = round(limit_price * STOP_LOSS_MULT, 2)

        # Entry: negativer Preis = Credit empfangen (IBKR-Konvention für Combo-Spreads)
        # transmit=False → Order geht zu TWS aber wird noch nicht weitergeleitet
        entry_order = LimitOrder('BUY', 1, -limit_price, tif='GTC')
        entry_order.transmit = False
        entry_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        entry_order.account = _cfg.get('ib_account', '')
        entry_trade = ib.placeOrder(bag, entry_order)
        parent_id = entry_trade.order.orderId

        # Take-Profit: positiver Preis = Debit bezahlen zum Schließen
        # parentId verknüpft mit Entry — IBKR storniert SL automatisch wenn TP füllt
        tp_order = LimitOrder('BUY', 1, tp_close, tif='GTC')
        tp_order.parentId = parent_id
        tp_order.transmit = False
        tp_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        tp_order.account = _cfg.get('ib_account', '')
        tp_trade = ib.placeOrder(bag, tp_order)

        # Stop-Loss: transmit=True übermittelt alle drei Orders gleichzeitig an die Börse
        sl_order = LimitOrder('BUY', 1, sl_close, tif='GTC')
        sl_order.parentId = parent_id
        sl_order.transmit = True
        sl_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        sl_order.account = _cfg.get('ib_account', '')
        sl_trade = ib.placeOrder(bag, sl_order)

        # IDs für spätere Stornierung (DTE-Exit, Breakeven-Update) speichern
        _bot_trades[sym]['tp_order_id'] = tp_trade.order.orderId
        _bot_trades[sym]['sl_order_id'] = sl_trade.order.orderId
        _save_state()

        log(f"  ✅ [{sym}] Bracket-Order platziert (alle GTC)!")
        log(f"     Entry  #{parent_id}:  -${limit_price:.2f}  (Credit ${market_credit:.0f})  R/R: {market_rr:.2f}x")
        log(f"     TP     #{tp_trade.order.orderId}:  +${tp_close:.2f}  (+{TAKE_PROFIT_PCT:.0%} = +${tp_close*100:.0f})")
        log(f"     SL     #{sl_trade.order.orderId}:  +${sl_close:.2f}  (-{STOP_LOSS_MULT:.0%} = -${sl_close*100:.0f})")
    except Exception as e:
        import traceback
        log(f"  ❌ [{sym}] Order-Fehler: {e}\n{traceback.format_exc()}")

def print_ranking(signals, selected):
    """Zeigt eine Ranking-Tabelle aller Signale dieses Zyklus."""
    selected_symbols = {s['symbol'] for s in selected}
    log(f"\n{'─'*108}")
    log(f"  {'#':<3} {'Symbol':<6} {'IV':>6} {'Kurs':>8} {'Strike':>12} "
        f"{'Credit':>8} {'R/R':>6} {'P(Win)':>7} {'P(MaxL)':>8} {'EV':>7} {'Score':>7}  Status")
    log(f"{'─'*116}")
    for i, s in enumerate(signals, 1):
        status  = "→ TRADE" if s['symbol'] in selected_symbols else "  skip"
        triggers = ', '.join(s.get('triggers', []))
        log(f"  {i:<3} {s['symbol']:<6} {s['iv']:>6.1%} {s['preis']:>8.2f} "
            f"  {s['short_strike']:>5.0f}P/{s['long_strike']:>4.0f}P "
            f"  ${s['credit']:>6.2f}"
            f"  {s['risk_reward']:>5.2f}x  {s.get('prob_otm', 0):>6.1%}  {s.get('prob_max_loss', 0):>7.1%}"
            f"  {s.get('ev', 0):>+6.2f}$  {s['score']:>6.3f}  {status}")
        if triggers:
            log(f"       ↳ {triggers}")
    log(f"{'─'*108}")

async def run_bot(stop_event: threading.Event = None):
    ib = IB()
    log(f"🤖 Master-Bot startet... Verbinde zur IB (Port {_cfg.get('ib_port', 7497)})")

    try:
        client_id = random.randint(10, 999)
        await ib.connectAsync(
            _cfg.get('ib_host', '127.0.0.1'),
            int(_cfg.get('ib_port', 7497)),
            clientId=client_id,
        )
        log("✅ Verbunden mit IB (nur für Order-Placement)")

        # Verzögerte Marktdaten aktivieren (Typ 3) — kein Echtzeit-Abo nötig
        ib.reqMarketDataType(3)

        # Event-Handler: gecancelte Orders in Echtzeit tracken
        ib.orderStatusEvent += _on_order_status

        # Event-Handler: IBKR-Fehler prominent loggen (insb. Error 201)
        def _on_ib_error(reqId, errorCode, errorString, contract):
            if errorCode in (201, 202, 399, 10147):
                log(f"  ⚠️  IBKR Error {errorCode} (reqId={reqId}): {errorString}")
        ib.errorEvent += _on_ib_error

        # Gespeicherten State vom letzten Lauf laden (heute gecancelte Symbole sperren)
        _load_state()

        # Bestehende offene Options-Orders von IB laden — verhindert Duplikate nach Neustart
        open_orders = await ib.reqAllOpenOrdersAsync()
        pre_loaded  = 0
        for o in open_orders:
            sym = o.contract.symbol
            if sym in WATCHLIST and sym not in _bot_trades and o.contract.secType == 'OPT':
                _bot_trades[sym] = {'status': 'open', 'entry_per_share': o.order.lmtPrice,
                                    'at_breakeven': False}
                pre_loaded += 1

        # Bestehende Options-Positionen: Spread-Details aus IB rekonstruieren
        # Gruppiere PUT-Legs nach Symbol → short (qty<0) + long (qty>0) = Bull-Put-Spread
        put_by_sym: dict = {}
        for p in ib.positions():
            sym = p.contract.symbol
            if sym not in WATCHLIST or p.contract.secType != 'OPT':
                continue
            if p.contract.right not in ('P', 'PUT'):
                continue
            put_by_sym.setdefault(sym, []).append(p)

        for sym, legs in put_by_sym.items():
            if sym in _bot_trades:
                continue
            short_legs = [p for p in legs if p.position < 0]
            long_legs  = [p for p in legs if p.position > 0]
            entry: dict = {'status': 'open', 'at_breakeven': False, 'entry_per_share': 0}

            if short_legs:
                sl = max(short_legs, key=lambda x: x.contract.strike)
                entry['short_strike'] = sl.contract.strike
                entry['short_conid']  = sl.contract.conId
                raw = abs(sl.avgCost)
                # IB gibt avgCost per-Kontrakt (×100) zurück → pro Share umrechnen
                entry['entry_per_share'] = raw / 100 if raw > 10 else raw
                exp = sl.contract.lastTradeDateOrContractMonth
                try:
                    entry['expiry_yf'] = datetime.strptime(exp[:8], '%Y%m%d').strftime('%Y-%m-%d')
                except Exception:
                    entry['expiry_yf'] = exp

            if long_legs:
                ll = min(long_legs, key=lambda x: x.contract.strike)
                entry['long_strike'] = ll.contract.strike
                entry['long_conid']  = ll.contract.conId
                raw_paid = abs(ll.avgCost)
                paid = raw_paid / 100 if raw_paid > 10 else raw_paid
                entry['entry_per_share'] = max(0, entry.get('entry_per_share', 0) - paid)

            _bot_trades[sym] = entry
            pre_loaded += 1

        if pre_loaded:
            log(f"   {pre_loaded} bestehende Order(s)/Position(en) aus IB geladen — werden nicht dupliziert")
        log("")
    except TimeoutError:
        port = _cfg.get('ib_port', 7497)
        log(f"❌ Verbindung fehlgeschlagen (Timeout auf Port {port}).")
        log("   → TWS/IB Gateway läuft?")
        log("   → API aktiviert? (Edit → Global Configuration → API → Enable Socket Clients)")
        log("   → Port korrekt? Paper=7497, Live=7496, Gateway-Paper=4002, Gateway-Live=4001")
        ib.disconnect()
        return

    try:
        while not (stop_event and stop_event.is_set()):
            market_open = is_market_open()
            now_et = datetime.now(ZoneInfo('America/New_York'))
            log(f"\n{'═'*72}")
            log(f"  ZYKLUS  {datetime.now().strftime('%H:%M:%S')}"
                f"  (NYSE: {'🟢 OFFEN' if market_open else '🔴 GESCHLOSSEN'}"
                f"  ET {now_et.strftime('%H:%M')})")
            log(f"{'═'*72}")

            # ── Exit-Monitoring läuft immer — auch außerhalb der Handelszeiten ──
            await monitor_exits(ib)
            _write_positions_file()   # Immer schreiben (auch bei geschlossenem Markt)

            if not market_open:
                wait_sec, open_et = seconds_until_market_open()
                h, rem = divmod(wait_sec, 3600)
                m      = rem // 60
                log(f"  ⏸️  Außerhalb NYSE-Handelszeiten (09:30–16:00 ET) — kein Scan, kein Trade")
                log(f"  💤  Markt öffnet in {h}h {m}min  (ET {open_et.strftime('%a %H:%M')})  — Bot schläft")
                slept = 0
                while slept < wait_sec:
                    if stop_event and stop_event.is_set():
                        break
                    chunk = min(30, wait_sec - slept)
                    await asyncio.sleep(chunk)
                    slept += chunk
                continue

            # ── Phase 1: Alle Symbole parallel scannen ───────────────────────
            _sem = asyncio.Semaphore(10)  # max 10 gleichzeitige yfinance-Requests

            async def scan_symbol(symbol):
                async with _sem:
                    preis, iv = await get_market_data(symbol)
                if preis is None:
                    log(f"   [{symbol}] ⏳ Keine Preisdaten")
                    return None
                if iv is None:
                    log(f"   [{symbol}] ⏳ Kein IV — überspringe")
                    return None

                prev_iv    = _iv_memory.get(symbol)
                first_scan = prev_iv is None
                iv_spike   = not first_scan and (iv - prev_iv) >= MIN_IV_SPIKE
                _iv_memory[symbol] = iv

                async with _sem:
                    news_hit, headline = await check_news_trigger(symbol)

                if iv <= MIN_VOLA:
                    log(f"   [{symbol}] ✗  IV={iv:.1%} (unter {MIN_VOLA:.1%})")
                    return None

                if not first_scan and not iv_spike and not news_hit:
                    delta = f"Δ={iv - prev_iv:+.1%}"
                    log(f"   [{symbol}] –  IV={iv:.1%} stabil ({delta}, kein Spike ≥{MIN_IV_SPIKE:.0%}, keine News)")
                    return None

                trigger_reasons = []
                if first_scan:
                    trigger_reasons.append("Erster Scan")
                if iv_spike:
                    trigger_reasons.append(f"IV-Spike +{iv - prev_iv:.1%}")
                if news_hit:
                    trigger_reasons.append(f"News: \"{headline[:60]}\"")

                log(f"   [{symbol}] 🔔 TRIGGER: {' | '.join(trigger_reasons)} | IV={iv:.1%} ${preis:.2f}")

                async with _sem:
                    sig = await fetch_signal(symbol, preis, iv)
                if sig:
                    sig['triggers'] = trigger_reasons
                    return sig
                return None

            t0 = datetime.now()
            results   = await asyncio.gather(*[scan_symbol(s) for s in WATCHLIST])
            all_signals = [s for s in results if s is not None]
            elapsed = (datetime.now() - t0).seconds
            scanned = len([r for r in results if r is not None or r is None])
            log(f"\n   Scan abgeschlossen in {elapsed}s | {len(WATCHLIST)} Symbole gescannt | {len(all_signals)} Signale über IV-Filter")

            # ── Phase 2: Signale filtern und ranken ───────────────────────────
            qualified = [
                s for s in all_signals
                if s['praemie_quelle'] != "Black-Scholes (geschätzt)"
                and s['credit']                 >= MIN_CREDIT
                and s['risk_reward']            >= MIN_RISK_REWARD
                and MIN_PROBABILITY             <= s['prob_otm'] <= MAX_PROBABILITY
                and s.get('prob_max_loss', 1.0) <= MAX_LOSS_PROB
                and s.get('ev_ratio', 0)        >= MIN_EV_RATIO
            ]
            qualified.sort(key=lambda s: s['score'], reverse=True)

            # Alle qualifizierten Signale sind handelbar — sortiert nach R/R,
            # Slot-Limit begrenzt natürlich auf die besten N
            tradeable = qualified
            best_rr   = qualified[0]['risk_reward'] if qualified else None
            best_score = qualified[0]['score'] if qualified else None
            threshold = None

            all_signals.sort(key=lambda s: s['risk_reward'], reverse=True)

            # ── Phase 3: Entscheiden wie viele Trades möglich sind ────────────
            open_count   = count_bot_orders()
            slots        = MAX_POSITIONS - open_count
            selected     = []

            if AUTO_TRADE and slots > 0:
                # Sektor-Exposure nur aus echten Spread-Positionen zählen
                sector_counts: dict = {}
                for s, info in _bot_trades.items():
                    if info.get('status') in ('open', 'closing') and info.get('short_conid'):
                        sec = SECTOR_MAP.get(s, 'Unbekannt')
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1

                # Margin-Check: Available Funds vor jedem Trade-Zyklus prüfen
                try:
                    # USD-Einträge haben Vorrang — currency='' kann 0-Einträge liefern die echte Werte überschreiben
                    acct_usd = {v.tag: v.value for v in ib.accountValues() if v.currency == 'USD'}
                    acct_any = {v.tag: v.value for v in ib.accountValues() if v.currency in ('USD', '')}
                    raw = (acct_usd.get('AvailableFunds')
                           or acct_usd.get('AvailableFunds-S')
                           or acct_any.get('AvailableFunds')
                           or acct_any.get('AvailableFunds-S')
                           or acct_any.get('NetLiquidation')
                           or '0')
                    available = float(raw)
                    log(f"  💰 Verfügbare Mittel: ${available:,.0f}")
                    if available < MIN_AVAILABLE_FUNDS:
                        log(f"  ⛔ Margin-Stop: ${available:,.0f} < ${MIN_AVAILABLE_FUNDS:,} Minimum — kein neuer Trade")
                        tradeable = []
                except Exception:
                    pass

                for sig in tradeable:
                    if len(selected) >= slots:
                        break
                    if already_traded(sig['symbol']):
                        log(f"  ⏸️  [{sig['symbol']}] Bereits in dieser Session gehandelt — übersprungen")
                        continue
                    if await has_open_position(ib, sig['symbol']):
                        log(f"  ⏸️  [{sig['symbol']}] Position im Portfolio — übersprungen")
                        continue
                    sector = SECTOR_MAP.get(sig['symbol'], 'Unbekannt')
                    if sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
                        log(f"  ⏸️  [{sig['symbol']}] Sektor-Limit: {sector} bereits {sector_counts[sector]}/{MAX_PER_SECTOR} — übersprungen")
                        # IV-Memory löschen: nächsten Zyklus neu bewerten wenn Slot frei wird
                        _iv_memory.pop(sig['symbol'], None)
                        continue
                    selected.append(sig)
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

            # ── Ranking-Tabelle ausgeben ──────────────────────────────────────
            if all_signals:
                print_ranking(all_signals, selected)
                # Zeige warum Signale aus all_signals nicht in tradeable landeten
                blocked = [s for s in all_signals if s not in tradeable]
                for s in blocked:
                    reasons = []
                    if s['praemie_quelle'] == "Black-Scholes (geschätzt)":
                        reasons.append("kein echtes Bid (BS-Schätzung)")
                    if s['credit'] < MIN_CREDIT:
                        reasons.append(f"Credit ${s['credit']:.0f} < ${MIN_CREDIT}")
                    if s['risk_reward'] < MIN_RISK_REWARD:
                        reasons.append(f"R/R {s['risk_reward']:.2f}x < {MIN_RISK_REWARD:.2f}x")
                    if s.get('prob_otm', 0) < MIN_PROBABILITY:
                        reasons.append(f"P(Win) {s.get('prob_otm',0):.1%} < {MIN_PROBABILITY:.0%}")
                    if s.get('prob_otm', 0) > MAX_PROBABILITY:
                        reasons.append(f"P(Win) {s.get('prob_otm',0):.1%} > {MAX_PROBABILITY:.0%} (Prämie zu klein)")
                    if s.get('prob_max_loss', 1.0) > MAX_LOSS_PROB:
                        reasons.append(f"P(MaxVerlust) {s.get('prob_max_loss',1):.1%} > {MAX_LOSS_PROB:.0%}")
                    if s.get('ev_ratio', 0) < MIN_EV_RATIO:
                        reasons.append(f"EV {s.get('ev', 0):+.2f}$ negativer Erwartungswert")
                    log(f"  ✗ [{s['symbol']}] blockiert: {', '.join(reasons)}")
            else:
                log("\n  Keine Signale in diesem Zyklus.")

            if best_rr:
                log(f"  Bestes R/R: {best_rr:.2f}x | {len(tradeable)} Signale qualifiziert")

            if not AUTO_TRADE:
                log("  [AUTO_TRADE aus — nur Anzeige]")
            elif slots <= 0:
                log(f"  ⏸️  Bot-Limit erreicht ({open_count}/{MAX_POSITIONS} Orders diese Session) — kein neuer Trade")
            elif not tradeable:
                log(f"  ⏸️  Kein Signal über Mindest-R/R {MIN_RISK_REWARD:.2f}x oder Credit ${MIN_CREDIT}")

            # ── Phase 4: Orders platzieren ────────────────────────────────────
            for sig in selected:
                log(f"\n  🚀 Trade: {sig['symbol']} | Score {sig['score']:.3f}")
                await place_order(ib, sig)

            # Positionen für Launcher-Anzeige schreiben
            _write_positions_file()

            log(f"\n  Pause {SCAN_INTERVALL}s ...")
            for _ in range(SCAN_INTERVALL):
                if stop_event and stop_event.is_set():
                    break
                await asyncio.sleep(1)

    except Exception as e:
        import traceback
        log(f"KRITISCHER FEHLER: {e}\n{traceback.format_exc()}")
    finally:
        ib.disconnect()
        log("🔌 IB-Verbindung getrennt.")

if __name__ == "__main__":
    asyncio.run(run_bot())
