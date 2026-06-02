import math
import asyncio
import os
import sys
import json
import queue
import random
import logging
import threading
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="ib_insync")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="eventkit")

# yfinance/Pandas-Kompatibilitätswarnungen: einmalig sauber ins Log, danach nicht mehr
_yf_warned: set = set()
_orig_showwarning = warnings.showwarning
def _clean_showwarning(message, category, filename, lineno, file=None, line=None):
    if 'yfinance' in (filename or '') or 'pandas' in (filename or '').lower():
        key = str(message)
        if key not in _yf_warned:
            _yf_warned.add(key)
            print(f"  ⚠️  yfinance Hinweis (einmalig): {message}", flush=True)
    else:
        _orig_showwarning(message, category, filename, lineno, file, line)
warnings.showwarning = _clean_showwarning
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

# ── Config laden (config.json oder --config <datei>) ─────────────────────────
import json as _json
_cfg_name = 'config.json'
for _i, _arg in enumerate(sys.argv[1:], 1):
    if _arg in ('--config', '-c') and _i < len(sys.argv):
        _cfg_name = sys.argv[_i + 1]
        break
    if _arg.startswith('--config='):
        _cfg_name = _arg.split('=', 1)[1]
        break
_cfg_path = os.path.join(_BASE, _cfg_name)
_cfg_defaults = {
    "ib_host": "127.0.0.1", "ib_port": 4001, "ib_account": "U25827024",
    "min_vola": 0.28, "abstand_y": 0.10, "min_credit": 70,
    "min_risk_reward": 0.20, "max_delta": 0.28, "max_positions": 8,
    "max_per_sector": 2, "scan_intervall": 60, "auto_trade": True,
    "take_profit_pct": 0.50, "stop_loss_mult": 2.0, "dte_exit": 21,
    "min_available_funds": 2000,
    "max_daily_loss": 500,          # Kill-Switch: max Tagesverlust in $ (0 = disabled)
    "max_weekly_loss": 0,           # Kill-Switch: max Wochenverlust in $ (0 = disabled)
    "max_risk_per_trade_pct": 0.02, # max 2 % NetLiq-Risiko pro Trade
    "max_total_risk_pct": 0.15,     # max 15 % NetLiq-Risiko gesamt offen
    "earnings_buffer_days": 14,     # kein Trade wenn Earnings < X Tage entfernt oder vor Expiry
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
    # Mega-Cap Tech (6) — META/CSCO/IBM/DELL gestrichen (kein Delayed-Datenstrom)
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'AMAT',
    # Halbleiter (7)
    'AMD', 'AVGO', 'QCOM', 'MU', 'LRCX', 'KLAC', 'MRVL',
    # Software & Cloud (8)
    'CRM', 'ORCL', 'NOW', 'ADBE', 'PLTR', 'PANW', 'CRWD', 'FTNT',
    # Consumer Tech / EV (4)
    'TSLA', 'NFLX', 'UBER', 'SHOP',
    # Fintech & Krypto (4)
    'COIN', 'PYPL', 'V', 'MA',
    # Banken & Finanzen (4)
    'JPM', 'GS', 'MS', 'BAC',
    # Pharma / Healthcare (5)
    'LLY', 'UNH', 'ABBV', 'AMGN', 'VRTX',
    # Energie (4)
    'XOM', 'CVX', 'COP', 'OXY',
    # Retail & Consumer (4)
    'WMT', 'COST', 'HD', 'CMG',
    # Industrie (2) — LMT/RTX/BA/GE gestrichen (kein Delayed-Datenstrom)
    'CAT', 'DE',
]  # gesamt: 48
MIN_VOLA         = float(_cfg.get('min_vola', 0.28))   # Hard-Floor IV (PDF: >28%)
MIN_VOLA_SOFT    = 0.35    # Score-Penalty Zone: IV 28–35 % → -0.10
IV_SOFT_PENALTY  = 0.10
MIN_IV_SPIKE     = 0.05
ABSTAND_Y        = float(_cfg['abstand_y'])
SPREAD_MAX_PCT   = 0.025
SPREAD_MIN       = 5
MIN_CREDIT_PERCENT = 0.18   # 18 % der Spread-Breite als Mindest-Credit (relativ)
MIN_CREDIT_ABS     = float(_cfg.get('min_credit', _cfg.get('min_credit_abs', 80)))  # Absolutes Minimum pro Kontrakt
MIN_RISK_REWARD  = float(_cfg['min_risk_reward'])
MAX_DELTA        = float(_cfg['max_delta'])
MIN_PROBABILITY  = 0.72
MAX_PROBABILITY  = 0.85    # Hard-Block: P(Win) > 85% → Credit zu klein
MAX_LOSS_PROB    = 0.22    # Hard-Block: P(MaxVerlust) > 22% → Totalverlustrisiko zu hoch
MIN_EV_RATIO     = 0.005   # Hard-Block: EV < 0.5% des Credits → statistisch kein Vorteil

# Decision Engine — Ranking-System: Score entscheidet, kein Hard-Filter-Stack
ENTRY_THRESHOLD  = 0.60    # Score ≥ 0.60: Trade-Kandidat
WATCH_THRESHOLD  = 0.50    # Score 0.50–0.60: Watch (war 0.62)
MAX_TRADES_PER_DAY = int(_cfg.get('max_trades_per_day', 10))  # Daily Budget
RATIO_TOLERANCE  = 0.20
MIN_DTE          = 45
MAX_DTE          = 60
SCAN_INTERVALL   = int(_cfg['scan_intervall'])
MAX_POSITIONS    = int(_cfg['max_positions'])
MAX_PER_SECTOR   = int(_cfg['max_per_sector'])
AUTO_TRADE       = bool(_cfg['auto_trade'])

# Confidence-Score je nach Preis-Datenquelle
PRICE_CONFIDENCE: dict[str, float] = {
    'REAL_BID_ASK': 1.0,   # Live NBBO — breitester Markt
    'MIDPRICE':     0.9,   # Mid-Point aus echten Bid+Ask
    'LAST_PRICE':   0.7,   # Greeks / letzter Handelspreis
    'BS_ESTIMATE':  0.4,   # Black-Scholes / yfinance-Schätzung
}
MIN_CONFIDENCE_LIVE = 0.9   # Mindestens echtes Bid/Ask erforderlich

# Kill-Switch
MAX_DAILY_LOSS         = float(_cfg.get('max_daily_loss', 500))    # 0 = disabled
MAX_WEEKLY_LOSS        = float(_cfg.get('max_weekly_loss', 0))      # 0 = disabled

# Account-Risk Limits
MAX_RISK_PER_TRADE_PCT = float(_cfg.get('max_risk_per_trade_pct', 0.02))
MAX_TOTAL_RISK_PCT     = float(_cfg.get('max_total_risk_pct', 0.15))

# Earnings-Filter
EARNINGS_BUFFER_DAYS   = int(_cfg.get('earnings_buffer_days', 14))

# Position-Sizing je nach Preis-Confidence (REAL_BID_ASK=3, MIDPRICE=2, sonst=1)
CONTRACTS_BY_CONFIDENCE = {
    'REAL_BID_ASK': 3,
    'MIDPRICE':     2,
    'LAST_PRICE':   1,
    'BS_ESTIMATE':  1,
}

# Liquiditätsscoring (kein Hard-Gate mehr — nur Referenzwert für log10-Score)
# Hard-Floor: OI < 20 UND Volume < 10 gleichzeitig → kein verwertbarer Datenpunkt
LIQUIDITY_SCAN_FLOOR_OI  = int(_cfg.get('liquidity_floor_oi',  20))
LIQUIDITY_SCAN_FLOOR_VOL = int(_cfg.get('liquidity_floor_vol', 10))
# Referenzwerte für log10-Normierung (OI/Vol bei diesen Werten → Score ≈ 1.0 je Leg)
MIN_OPEN_INTEREST  = int(_cfg.get('min_open_interest', 500))
MIN_OPTION_VOLUME  = int(_cfg.get('min_option_volume',  100))
MAX_BID_ASK_SPREAD = float(_cfg.get('max_bid_ask_spread', 0.12))  # 12 % des Mids

# Slippage-Modell: erwarteter Fill als Anteil des theoretischen Credits
SLIPPAGE_FACTOR: dict[str, float] = {
    'IB (Combo)':                0.92,
    'IB (Net-Bid)':              0.90,
    'IB (Bid)':                  0.88,
    'yfinance (Bid)':            0.82,
    'Black-Scholes (geschätzt)': 0.65,
    'default':                   0.80,
}

# Fill-Timeout: Entry-Order wird nach N Sekunden storniert wenn nicht gefüllt
FILL_TIMEOUT_SECONDS = int(_cfg.get('fill_timeout_seconds', 300))   # 5 Minuten

# Reconnect: maximale Versuche und Basis-Wartezeit zwischen den Versuchen
RECONNECT_MAX_ATTEMPTS = int(_cfg.get('reconnect_max_attempts', 10))
RECONNECT_BASE_WAIT    = int(_cfg.get('reconnect_base_wait',    15))   # Sekunden

# Bekannte Hochliquiditätssymbole — OI-Warnung wenn auffällig niedrig
_HIGH_LIQUIDITY_SYMS = frozenset({
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NFLX',
    'AMD', 'AVGO', 'JPM', 'GS', 'SPY', 'QQQ',
})

# VIX-Regime (Bull Put Spreads = Short Premium → VIX-abhängige Größensteuerung)
VIX_CALM_THRESHOLD    = float(_cfg.get('vix_calm',    16))   # < 16: zu wenig Prämie
VIX_ELEVATED_THRESHOLD= float(_cfg.get('vix_elevated', 30))  # 16–30: optimal
VIX_CRISIS_THRESHOLD  = float(_cfg.get('vix_crisis',   40))  # > 40: kein neuer Trade

# Event-Lock: kein neuer Trade N Stunden vor/nach Makro-Ereignis
EVENT_LOCK_HOURS = int(_cfg.get('event_lock_hours', 24))

# Makro-Kalender: FOMC-Sitzungstage + CPI-Veröffentlichungen + NFP
_MACRO_EVENTS: list[str] = [
    # CPI 2026
    '2026-06-10', '2026-07-14', '2026-08-12', '2026-09-10',
    '2026-10-14', '2026-11-12', '2026-12-10',
    # FOMC 2026 (Sitzungsende-Tag)
    '2026-06-10', '2026-07-29', '2026-09-16', '2026-10-28', '2026-12-09',
    # NFP 2026 (erster Freitag des Monats)
    '2026-06-05', '2026-07-02', '2026-08-07', '2026-09-04',
    '2026-10-02', '2026-11-06', '2026-12-04',
]

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
    'AFRM': 'Fintech', 'SOFI': 'Fintech',
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

def _reload_cfg():
    """Lädt config.json neu — aktualisiert Exit-/Trade-Parameter ohne Bot-Neustart."""
    global TAKE_PROFIT_PCT, STOP_LOSS_MULT, BREAKEVEN_TRIGGER_PCT, DTE_EXIT
    global AUTO_TRADE, MAX_POSITIONS, MAX_PER_SECTOR, SCAN_INTERVALL
    global MIN_CREDIT_ABS, MIN_RISK_REWARD, MAX_DELTA
    try:
        if not os.path.exists(_cfg_path):
            return
        import json as _json2
        with open(_cfg_path) as _f:
            updated = {**_cfg_defaults, **_json2.load(_f)}
        TAKE_PROFIT_PCT       = float(updated['take_profit_pct'])
        STOP_LOSS_MULT        = float(updated['stop_loss_mult'])
        DTE_EXIT              = int(updated['dte_exit'])
        AUTO_TRADE            = bool(updated['auto_trade'])
        MAX_POSITIONS         = int(updated['max_positions'])
        MAX_PER_SECTOR        = int(updated['max_per_sector'])
        SCAN_INTERVALL        = int(updated['scan_intervall'])
        MIN_CREDIT_ABS        = float(updated.get('min_credit', updated.get('min_credit_abs', 80)))
        MIN_RISK_REWARD       = float(updated['min_risk_reward'])
        MAX_DELTA             = float(updated['max_delta'])
    except Exception:
        pass   # Bei Fehler alte Werte behalten

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

_EXIT_RETRY_BACKOFF = [15, 30, 60, 120, 300]  # Sekunden: 15s → 30s → 1min → 2min → 5min

class _IBOrderQueue:
    """Globale serielle Pipeline für alle IB Order-Mutations (cancel + place).

    Alle cancelOrder- und placeOrder-Calls laufen durch diese einzige Lane:
    - verhindert Race Conditions zwischen parallelen Symbol-Exits
    - garantiert 250ms IB-Pacing zwischen Calls
    - macht das Execution-Verhalten deterministisch

    Read-only Queries (reqAllOpenOrders, reqPositions) laufen direkt — kein Queue.
    """
    _IB_PACING = 0.25  # Mindestabstand zwischen IB Order-Mutations

    def __init__(self):
        self._q: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._worker())

    async def cancel(self, ib, oid: int) -> None:
        await self._submit(ib.client.cancelOrder, oid, '')

    async def place(self, ib, contract, order):
        return await self._submit(ib.placeOrder, contract, order)

    async def _submit(self, fn, *args):
        loop = asyncio.get_event_loop()
        fut  = loop.create_future()
        await self._q.put((fn, args, fut))
        return await fut

    async def _worker(self):
        while True:
            fn, args, fut = await self._q.get()
            try:
                await asyncio.sleep(self._IB_PACING)
                result = fn(*args)
                if asyncio.iscoroutine(result):
                    result = await result
                fut.set_result(result)
            except Exception as exc:
                if not fut.done():
                    fut.set_exception(exc)
            finally:
                self._q.task_done()

_ibq: _IBOrderQueue | None = None  # wird in run_bot() initialisiert

async def _ib_cancel_paced(ib, oid: int) -> None:
    """Compat-Wrapper: leitet an _ibq weiter falls verfügbar, sonst direkter Call."""
    if _ibq is not None:
        await _ibq.cancel(ib, oid)
    else:
        ib.client.cancelOrder(oid, '')

def _exit_retry_delay(info: dict) -> int:
    """Exponentieller Backoff für Exit-Retries. Gibt Wartezeit in Sekunden zurück."""
    count = info.get('retry_count', 0)
    delay = _EXIT_RETRY_BACKOFF[min(count, len(_EXIT_RETRY_BACKOFF) - 1)]
    info['retry_count'] = count + 1
    return delay

def is_market_open() -> bool:
    """NYSE offen: Mo–Fr 09:30–16:00 ET (15:30–22:00 MEZ/15:30–22:00 MESZ)."""
    now_et = _now_et()
    if now_et.weekday() >= 5:
        return False
    open_t  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now_et < close_t

def seconds_until_market_open() -> tuple:
    """Nächste NYSE-Öffnungszeit — datetime wird neu konstruiert statt per .replace()
    um Timezone-Fold-Probleme auf Windows/ZoneInfo zu vermeiden."""
    now_et = _now_et()
    tz     = now_et.tzinfo
    for delta in range(8):   # max 7 Tage vorausschauen
        d    = (now_et + timedelta(days=delta)).date()
        cand = datetime(d.year, d.month, d.day, 9, 30, 0, tzinfo=tz)
        if cand.weekday() >= 5:   # Wochenende überspringen
            continue
        secs = int((cand - now_et).total_seconds())
        if secs > 0:
            return max(30, secs), cand
    fallback = now_et + timedelta(days=3)
    return 259200, fallback

# Speichert IV vom letzten Scan pro Symbol — für Spike-Erkennung
_iv_memory: dict = {}
# Speichert aktive Bot-Trades für Exit-Monitoring
_bot_trades: dict = {}
# IB-validierte Strikes und Expiries pro Symbol (einmalig beim Start geladen)
_strike_map: dict = {}
# IV-Cache: {symbol: (iv, timestamp)} — verhindert yfinance-Spam bei jedem Scan-Zyklus
_iv_cache: dict = {}
_IV_CACHE_TTL = 300  # Sekunden (5 Minuten)

# yfinance Rate-Limit Cooldown — wenn gesperrt, 10 Min direkt zu IB springen
_yf_blocked_until: float = 0.0
_YF_COOLDOWN = 600  # Sekunden
# Order-IDs die absichtlich storniert werden (TP/SL-Rotation → kein falsches 'cancelled')
_expected_cancels: set = set()
# Begrenzt gleichzeitige IB reqMktData-Aufrufe — verhindert Error 101 (Max Tickers)
_sem_ib_mktdata: asyncio.Semaphore | None = None
# Mutex pro Symbol — serialisiert Entry/Exit/Breakeven/Cancel auf demselben Contract
# (verhindert Error 201: gleichzeitige gegensätzliche Orders auf denselben Legs)
_contract_locks: dict[str, asyncio.Lock] = {}

def _sym_lock(symbol: str) -> asyncio.Lock:
    """Gibt einen asyncio.Lock pro Symbol zurück — immer nur EIN Order-Vorgang gleichzeitig."""
    return _contract_locks.setdefault(symbol, asyncio.Lock())

ACCOUNT_ID: str = ''

# Kill-Switch: True wenn Tages-/Wochenverlust-Limit überschritten
_kill_switch_active: bool  = False
_kill_switch_reason: str   = ''

# Daily Trade Budget: Anzahl Trades pro Kalendertag
_trades_today: dict = {}   # {'2026-05-15': 3, ...}

# Aktueller VIX-Stand (wird jede Scan-Runde aktualisiert)
_vix_level:  float = 0.0
_vix_regime: str   = 'unknown'

_STATE_FILE          = os.path.join(_BASE, '.bot_state.json')
_HISTORY_FILE        = os.path.join(_BASE, 'trade_history.json')
_POSITIONS_FILE      = os.path.join(_BASE, 'positions.json')
_CLOSE_CMD_FILE      = os.path.join(_BASE, 'close_commands.json')
_SHADOW_FILE         = os.path.join(_BASE, 'shadow_trades.jsonl')
_RECOMMENDATIONS_FILE = os.path.join(_BASE, 'recommendations.json')

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
                'tp_target':       round(entry * (1 - TAKE_PROFIT_PCT), 2),
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


def _write_recommendations_file(signals: list) -> None:
    """Schreibt Bot-Empfehlungen in recommendations.json (menschlicher Filter vor Echtgeld-Trade)."""
    try:
        recs = []
        for s in signals:
            exp_raw = s.get('expiry_ib', '')
            try:
                exp_fmt = f"{exp_raw[:4]}-{exp_raw[4:6]}-{exp_raw[6:]}"
            except Exception:
                exp_fmt = exp_raw
            recs.append({
                'symbol':       s['symbol'],
                'short_strike': s['short_strike'],
                'long_strike':  s['long_strike'],
                'breite':       s['breite'],
                'expiry':       exp_fmt,
                'dte':          s['dte'],
                'preis':        round(s['preis'], 2),
                'iv':           round(s['iv'], 4),
                'praemie':      round(s['praemie'], 2),
                'credit':       round(s['credit'], 0),
                'max_risk':     round(s['max_risk'], 0),
                'risk_reward':  round(s['risk_reward'], 3),
                'prob_otm':     round(s['prob_otm'], 3),
                'score':        round(s['score'], 4),
                'ev':           round(s['ev'], 2),
                'sektor':       SECTOR_MAP.get(s['symbol'], 'Unbekannt'),
                'quelle':       s.get('praemie_quelle', ''),
            })
        with open(_RECOMMENDATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'generated':     datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'count':         len(recs),
                'recommendations': recs,
            }, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _log_shadow(entry: dict) -> None:
    """Hängt einen Shadow-Trade-Eintrag an shadow_trades.jsonl an (eine JSON-Zeile pro Eintrag)."""
    try:
        entry.setdefault('ts', datetime.now().isoformat(timespec='seconds'))
        with open(_SHADOW_FILE, 'a', encoding='utf-8') as _sf:
            _sf.write(_json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _shadow_from_sig(sig: dict, type_: str, stage: str, reason: str) -> None:
    """Logt einen vollständigen Signal-Dict als Shadow-Eintrag."""
    _log_shadow({
        'type':          type_,      # 'rejected' | 'blocked' | 'taken'
        'stage':         stage,      # 'score' | 'credit' | 'sector' | 'event_lock' | 'vix' | ...
        'reason':        reason,
        'symbol':        sig.get('symbol'),
        'preis':         sig.get('preis'),
        'iv':            round(sig.get('iv', 0), 4),
        'short_strike':  sig.get('short_strike'),
        'long_strike':   sig.get('long_strike'),
        'expiry':        sig.get('expiry_ib', '')[:8],
        'credit':        round(sig.get('credit', 0), 2),
        'risk_reward':   round(sig.get('risk_reward', 0), 3),
        'prob_otm':      round(sig.get('prob_otm', 0), 4),
        'prob_max_loss': round(sig.get('prob_max_loss', 0), 4),
        'ev':            round(sig.get('ev', 0), 2),
        'ev_raw':        round(sig.get('ev_raw', sig.get('ev', 0)), 2),
        'slippage':      sig.get('slippage_factor', 1.0),
        'score':         round(sig.get('score', 0), 4),
        'decision':      sig.get('decision'),
        'edge':          round(sig.get('edge', 0), 4),
        'risk':          round(sig.get('risk', 0), 4),
        'quality':       round(sig.get('quality', 0), 4),
        'vix':           round(_vix_level, 1),
        'vix_regime':    _vix_regime,
    })


def _shadow_partial(symbol: str, preis: float, iv: float,
                    stage: str, reason: str, **kwargs) -> None:
    """Logt einen partiellen Shadow-Eintrag (wenn Signal noch nicht vollständig berechnet ist)."""
    _log_shadow({
        'type':      'rejected',
        'stage':     stage,
        'reason':    reason,
        'symbol':    symbol,
        'preis':     preis,
        'iv':        round(iv, 4),
        'vix':       round(_vix_level, 1),
        'vix_regime': _vix_regime,
        **kwargs,
    })


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
            'close_reason':    info.get('close_reason', ''),
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
                if info.get('status') in ('open', 'closing', 'exit_retry') and info.get('short_conid')}
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
                _expected_cancels.add(order_id)  # absichtliche Stornierung markieren
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
    order_id = trade.order.orderId
    if status in ('Cancelled', 'ApiCancelled', 'Inactive'):
        if order_id in _expected_cancels:
            _expected_cancels.discard(order_id)
            return  # absichtliche TP/SL-Stornierung — Symbol nicht sperren
        current_st = _bot_trades[sym].get('status', '')
        if current_st in ('open', 'closing', 'recovery_pending'):
            # Position war offen — Exit gescheitert → Backoff-Retry
            _delay = _exit_retry_delay(_bot_trades[sym])
            retry_ts = (datetime.now() + timedelta(seconds=_delay)).timestamp()
            _bot_trades[sym]['status']   = 'exit_retry'
            _bot_trades[sym]['retry_at'] = retry_ts
            log(f"  🔁 [{sym}] Order #{order_id} abgelehnt — EXIT_RETRY in {_delay}s "
                f"(Versuch #{_bot_trades[sym].get('retry_count', 1)})")
        else:
            # Kein offener Trade (Entry-Order gecancelt) — nur überspringen
            _bot_trades[sym]['status'] = 'cancelled'
            log(f"  🚫 [{sym}] Order #{order_id} abgelehnt — kein offener Spread, Symbol übersprungen")
        _save_state()
    elif status == 'Filled':
        filled_qty = trade.orderStatus.filled or 0
        total_qty  = trade.order.totalQuantity or 1
        if 0 < filled_qty < total_qty:
            log(f"  ⚠️  [{sym}] PARTIAL FILL: {filled_qty}/{total_qty} Kontrakte — "
                f"Order #{order_id} noch aktiv. Position prüfen!")
        _tp_oid = _bot_trades[sym].get('tp_order_id', 0)
        _sl_oid = _bot_trades[sym].get('sl_order_id', 0)
        if _bot_trades[sym].get('status') == 'closing':
            exit_fill = abs(trade.orderStatus.avgFillPrice or 0)
            _bot_trades[sym]['status'] = 'done'
            _append_history(sym, _bot_trades[sym], exit_per_share=exit_fill)
            log(f"  💰 [{sym}] EXIT AUSGEFÜHRT @ ${exit_fill:.2f}/Share — Position geschlossen!")
        elif order_id and _tp_oid and order_id == _tp_oid:
            # IB-Bracket Take-Profit ausgeführt — kein close_spread() nötig
            exit_fill = abs(trade.orderStatus.avgFillPrice or 0)
            _bot_trades[sym]['status'] = 'done'
            _append_history(sym, _bot_trades[sym], exit_per_share=exit_fill)
            log(f"  💰 [{sym}] TP AUSGEFÜHRT (IB-Bracket) @ ${exit_fill:.2f}/Share — Position geschlossen!")
        elif order_id and _sl_oid and order_id == _sl_oid:
            # IB-Bracket Stop-Loss ausgeführt — kein close_spread() nötig
            exit_fill = abs(trade.orderStatus.avgFillPrice or 0)
            _bot_trades[sym]['status'] = 'done'
            _append_history(sym, _bot_trades[sym], exit_per_share=exit_fill)
            log(f"  🛑 [{sym}] SL AUSGEFÜHRT (IB-Bracket) @ ${exit_fill:.2f}/Share — Position geschlossen!")
        else:
            _bot_trades[sym]['status']        = 'open'
            _bot_trades[sym]['fill_confirmed'] = True   # Entry gefüllt — Fill-Timeout deaktiviert
            fill = trade.orderStatus.avgFillPrice
            if fill and fill > 0:
                _bot_trades[sym]['entry_per_share'] = abs(fill)
                log(f"  💰 [{sym}] TRADE AUSGEFÜHRT @ ${abs(fill):.2f}/Share — Viel Erfolg!")
            else:
                log(f"  ✅ [{sym}] Entry-Order bestätigt (Fill-Preis folgt)")
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

def _yf_net_credit(puts, short_strike, long_strike, short_bid_yf):
    """Berechnet den Netto-Credit aus yfinance-Daten (konservativ: Short-Bid − Long-Ask).
    Gibt (praemie, quelle) zurück oder None wenn Daten fehlen."""
    import math as _m
    def _safe(v):
        try:
            f = float(v)
            return f if f > 0 and not _m.isnan(f) else None
        except Exception:
            return None
    try:
        sr = puts[puts['strike'] == short_strike]
        lr = puts[puts['strike'] == long_strike]
        if sr.empty or lr.empty:
            return None
        s_bid = _safe(sr.iloc[0]['bid'])
        l_ask = _safe(lr.iloc[0]['ask'])
        if s_bid and l_ask:
            net = round(max(s_bid - l_ask, 0.01), 2)
            return net, "yfinance (Net Bid-Ask)"
    except Exception:
        pass
    return None

def _bs_iv_from_price(S, K, T, market_price, r=0.045):
    """Rückrechnung der impliziten Volatilität via Bisektion aus dem Optionspreis (Mid = (Bid+Ask)/2)."""
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return None
    lo, hi = 0.01, 5.0
    for _ in range(60):
        mid_iv = (lo + hi) / 2
        bs = _bs_put(S, K, T, mid_iv, r)
        if bs < market_price:
            lo = mid_iv
        else:
            hi = mid_iv
        if hi - lo < 0.0001:
            break
    iv = (lo + hi) / 2
    return iv if 0.05 <= iv <= 3.0 else None

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


def _check_credit(credit: float, breite: float, prob_otm: float):
    """Dynamischer Credit-Check: Mindestprämie = MAX(12% der Spread-Breite, $45).
    P(Win)-Anforderung steigt wenn die Prämie niedrig relativ zur Breite ist.

    Returns (passes: bool, required_credit: float, min_pwin: float)
    """
    spread_risk = breite * 100
    required    = max(spread_risk * MIN_CREDIT_PERCENT, MIN_CREDIT_ABS)

    if credit < required:
        return False, required, None

    # Credit-Ratio bestimmt die P(Win)-Anforderung
    ratio = credit / spread_risk
    if ratio < 0.15:
        min_pwin = 0.78   # Niedrige Prämie → höhere Sicherheit gefordert
    elif ratio > 0.20:
        min_pwin = 0.70   # Hohe Prämie → P(Win)-Hürde etwas niedriger
    else:
        min_pwin = MIN_PROBABILITY  # 15–20 %: Standard 72 %

    if prob_otm < min_pwin:
        return False, required, min_pwin

    return True, required, min_pwin


def _round_to_standard_strike(strike: float, price: float) -> float:
    """Rundet einen Strike auf das nächste typische Options-Inkrement.
    Fallback wenn der Strike-Map-Eintrag für ein Symbol fehlt."""
    if price >= 500:
        inc = 10.0
    elif price >= 200:
        inc = 5.0
    elif price >= 50:
        inc = 2.5
    else:
        inc = 1.0
    return round(strike / inc) * inc


async def build_strike_map(ib):
    """Lädt IB-verfügbare Strikes und Expiries für alle Watchlist-Symbole.
    Einmalig beim Bot-Start — verhindert 'Qualifizierung fehlgeschlagen' für nicht-existente Strikes."""
    global _strike_map
    log("📋 Lade IB Strike-Map für Watchlist ...")
    _sem_map = asyncio.Semaphore(10)

    async def _fetch(symbol):
        async with _sem_map:
            try:
                stock = Stock(symbol, 'SMART', 'USD')
                await ib.qualifyContractsAsync(stock)
                if not stock.conId:
                    return
                chains = await ib.reqSecDefOptParamsAsync(symbol, '', 'STK', stock.conId)
                if not chains:
                    return
                chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
                if chain and chain.strikes:
                    _strike_map[symbol] = {
                        'strikes':     sorted(chain.strikes),
                        'expirations': sorted(chain.expirations),
                    }
            except Exception:
                pass

    try:
        await asyncio.wait_for(
            asyncio.gather(*[_fetch(s) for s in WATCHLIST]),
            timeout=90
        )
    except asyncio.TimeoutError:
        log(f"  ⚠️  Strike-Map Timeout — {len(_strike_map)}/{len(WATCHLIST)} Symbole geladen")
    log(f"✅ Strike-Map: {len(_strike_map)}/{len(WATCHLIST)} Symbole geladen")


async def get_market_data(symbol, ib=None):
    """Hole Kurs und ATM-IV via yfinance (Stocks nie via IB reqMktData — Subscription-Limit)."""
    return await _get_market_data_yf(symbol)


async def _get_market_data_yf(symbol, ib=None):
    """IV via OPRA (Type 1): ATM-Strike aus Cache-Preis, impliedVolatility → modelGreeks → Bid/Ask-Fallback."""
    import math as _math

    if ib is None or not ib.isConnected() or symbol not in _strike_map:
        return None, None

    try:
        sm = _strike_map[symbol]
        strikes  = sm.get('strikes', [])
        expiries = sm.get('expirations', [])
        if not strikes or not expiries:
            return None, None

        # Aktienkurs aus Hintergrund-Cache (Type-4-Stream) — kein Extra-API-Call
        price = None
        for t in ib.tickers():
            if t.contract and t.contract.symbol == symbol and t.contract.secType == 'STK':
                for val in [t.last, t.close,
                            getattr(t, 'delayedLast',  None),
                            getattr(t, 'delayedClose', None)]:
                    if val is not None and val > 0 and not _math.isnan(val):
                        price = float(val)
                        break
                if price:
                    break
        if not price or price <= 0:
            return None, None

        # Echter ATM-Strike: nächster Strike zum aktuellen Kurs
        strike = min(strikes, key=lambda s: abs(s - price))

        # Expiry ~38 DTE
        today = datetime.now()
        exp = min(expiries, key=lambda e: abs((datetime.strptime(e, '%Y%m%d') - today).days - 38))
        if (datetime.strptime(exp, '%Y%m%d') - today).days < 7:
            return None, None

        opt_con = Option(symbol, exp, strike, 'P', 'SMART')
        await ib.qualifyContractsAsync(opt_con)

        # Wenn ATM-Strike für diese Expiry nicht existiert → bis zu 4 nächste Strikes versuchen
        if not opt_con.conId:
            alt_strikes = sorted(strikes, key=lambda s: abs(s - price))[:5]
            for alt_s in alt_strikes:
                if alt_s == strike:
                    continue
                opt_alt = Option(symbol, exp, alt_s, 'P', 'SMART')
                await ib.qualifyContractsAsync(opt_alt)
                if opt_alt.conId:
                    opt_con = opt_alt
                    strike = alt_s
                    break

        if not opt_con.conId:
            log(f"   [IV-DBG {symbol}] kein Contract: strike={strike} exp={exp} — Strike für diese Expiry nicht verfügbar")
            return None, None

        ib.reqMarketDataType(1)  # OPRA Echtzeit für Optionen
        t_opt = ib.reqMktData(opt_con, '', False, False)

        def _valid_iv(v) -> bool:
            try:
                return v is not None and v > 0 and not _math.isnan(v)
            except Exception:
                return False

        iv = None
        for _ in range(10):  # max 5s — IBKR braucht bei stark gehandelten Symbolen bis 3s
            await asyncio.sleep(0.5)
            # Versuch 1: bidGreeks / askGreeks — kommen direkt aus OPRA, kein Underlying nötig
            for grk_attr in ('bidGreeks', 'askGreeks'):
                grk = getattr(t_opt, grk_attr, None)
                if grk:
                    iv_raw = getattr(grk, 'impliedVol', None)
                    if _valid_iv(iv_raw):
                        iv = float(iv_raw)
                        break
            if iv:
                break
            # Versuch 2: modelGreeks (wird nur geliefert wenn IBKR Underlying-Preis kennt)
            mg = getattr(t_opt, 'modelGreeks', None)
            if mg:
                iv_raw = getattr(mg, 'impliedVol', None)
                if _valid_iv(iv_raw):
                    iv = float(iv_raw)
                    break
            # Versuch 3: OPRA Bid/Ask vorhanden → echte IV per BS-Bisektion rückrechnen
            bid = getattr(t_opt, 'bid', None)
            ask = getattr(t_opt, 'ask', None)
            if _valid_iv(bid) and _valid_iv(ask):
                mid_price = (bid + ask) / 2.0
                T_years   = (datetime.strptime(exp, '%Y%m%d') - datetime.now()).days / 365.0
                iv_bs = _bs_iv_from_price(price, strike, T_years, mid_price)
                if iv_bs:
                    iv = iv_bs
                    break

        await asyncio.sleep(0.2)  # Puffer vor Cancel — verhindert Error 300
        try:
            ib.cancelMktData(t_opt)
        except Exception:
            pass

        if not iv:
            _bid = getattr(t_opt, 'bid', None)
            _ask = getattr(t_opt, 'ask', None)
            log(f"   [IV-DBG {symbol}] Stream offen, kein Tick: bid={_bid} ask={_ask} "
                f"(strike={strike} exp={exp})")

        return (None, iv) if (iv and iv > 0) else (None, None)

    except Exception:
        pass

    return None, None

async def _yf_stock_scan(symbols: list, ib=None) -> dict:
    """Liest Aktienkurse aus dem Hintergrund-Cache — kein API-Aufruf, <0.1s."""
    import math as _math
    if ib is None or not ib.isConnected():
        return {}
    results = {}
    try:
        cache = {t.contract.symbol: t for t in ib.tickers()
                 if t.contract and t.contract.secType == 'STK'}
        for sym in symbols:
            t = cache.get(sym)
            if t is None:
                continue
            # Live-Felder zuerst (falls vorhanden), dann Delayed-Felder (Type 4 liefert delayedLast/delayedClose)
            price = None
            for val in [t.last, t.close,
                        getattr(t, 'delayedLast',  None),
                        getattr(t, 'delayedClose', None)]:
                if val is not None and val > 0 and not _math.isnan(val):
                    price = float(val)
                    break
            if price:
                results[sym] = (price, None)
    except Exception:
        pass
    return results


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
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=15)
    except (asyncio.TimeoutError, Exception):
        return False, None

async def check_earnings_conflict(symbol: str, expiry_str: str) -> tuple:
    """Prüft Earnings-Risiko. Gibt (hard_block, penalty, reason) zurück.
    hard_block=True: Earnings in ≤3 Tagen UND vor Expiry (akutes Risiko).
    penalty: Score-Abzug 0.25/0.20/0.15/0.05/0.0 je nach Nähe und Position zur Expiry.
    """
    def _fetch():
        import yfinance as yf
        from datetime import date as date_t
        today = date_t.today()
        expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
        cal = yf.Ticker(symbol).calendar
        if cal is None:
            return False, 0.0, ''
        if isinstance(cal, dict):
            raw_dates = cal.get('Earnings Date', [])
        else:
            try:
                raw_dates = cal.loc['Earnings Date'].tolist()
            except Exception:
                return False, 0.0, ''
        best = (False, 0.0, '')   # (hard, penalty, reason) für nächstes Earnings-Datum
        for d in (raw_dates or []):
            try:
                ed = d.date() if hasattr(d, 'date') else datetime.strptime(str(d)[:10], '%Y-%m-%d').date()
                if ed < today:
                    continue
                days = (ed - today).days
                if ed <= expiry_date:
                    # Earnings passieren WÄHREND wir die Position halten
                    if days <= 3:
                        return True, 0.25, f"Earnings {ed} in {days}d (vor Expiry — Hard Block)"
                    elif days <= 7:
                        best = (False, 0.20, f"Earnings {ed} in {days}d vor Expiry")
                    elif days <= 14:
                        if best[1] < 0.15:
                            best = (False, 0.15, f"Earnings {ed} in {days}d vor Expiry")
                    else:
                        if best[1] < 0.10:
                            best = (False, 0.10, f"Earnings {ed} in {days}d vor Expiry")
                else:
                    # Earnings passieren NACH Expiry — wir halten nicht durch
                    if days <= 7:
                        if best[1] < 0.05:
                            best = (False, 0.05, f"Earnings {ed} in {days}d (nach Expiry)")
                    elif days <= EARNINGS_BUFFER_DAYS:
                        if best[1] < 0.02:
                            best = (False, 0.02, f"Earnings {ed} in {days}d (nach Expiry)")
            except Exception:
                continue
        return best
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=15)
    except Exception:
        return False, 0.0, ''


_vix_cache_val: float = 0.0
_vix_cache_ts:  float = 0.0
_VIX_CACHE_TTL = 120  # VIX max alle 2 Minuten neu holen

async def start_background_streaming(symbols: list, ib) -> None:
    """Einmalig beim Start: VIX (Type 3) + alle Watchlist-Aktien (Type 4) als Dauer-Stream."""
    log(f"   ⚙️  Starte Hintergrund-Streams für {len(symbols)} Symbole + VIX ...")

    # VIX: Type 3 — CBOE-Index, kein Live-Abo nötig
    try:
        ib.reqMarketDataType(3)
        vix_con = Index('VIX', 'CBOE')
        await ib.qualifyContractsAsync(vix_con)
        if vix_con.conId:
            ib.reqMktData(vix_con, '', False, False)
            log("   ✅ VIX-Stream gestartet (Type 3 Delayed)")
    except Exception as e:
        log(f"   ⚠️  VIX-Stream fehlgeschlagen: {e}")

    # Aktien: Type 4 (Delayed-Frozen) — robuster als Type 3, vermeidet Error 322 'bM'
    # Type 4 gibt immer den letzten bekannten Kurs zurück (Delayed während Handelszeiten,
    # Frozen nach Börsenschluss) — kein separates US-Aktien-Abo nötig
    ib.reqMarketDataType(4)
    count = 0
    for sym in symbols:
        try:
            con = Stock(sym, 'SMART', 'USD')
            await ib.qualifyContractsAsync(con)
            if con.conId:
                ib.reqMktData(con, '', False, False)
                count += 1
                await asyncio.sleep(0.1)  # 100ms — gibt dem Server Luft zwischen Anfragen
        except Exception:
            pass

    log(f"   ✅ {count}/{len(symbols)} Aktien-Streams geöffnet — warte 10s auf erste Daten ...")
    await asyncio.sleep(10)  # Warm-up: letzte Symbole in der Liste brauchen mehr Zeit
    log(f"   ✅ Daten-Pool bereit")
    ib.reqMarketDataType(1)  # Für Options-Scan (OPRA) zurück auf Live


async def get_vix(ib=None) -> float:
    """Liest VIX direkt aus dem Hintergrund-Cache — kein API-Aufruf im Zyklus."""
    import math
    global _vix_cache_val
    if ib is None or not ib.isConnected():
        return _vix_cache_val
    try:
        for t in ib.tickers():
            if t.contract and t.contract.symbol == 'VIX' and t.contract.secType == 'IND':
                for val in [t.last, t.close,
                            getattr(t, 'delayedLast',  None),
                            getattr(t, 'delayedClose', None)]:
                    if val is not None and val > 0 and not math.isnan(val):
                        _vix_cache_val = float(val)
                        return _vix_cache_val
    except Exception:
        pass
    return _vix_cache_val


def vix_regime(vix: float) -> tuple:
    """Gibt (regime_str, size_factor) zurück.
    size_factor == 0.0 bedeutet: kein neuer Trade (Krisenmodus)."""
    if vix <= 0:
        return 'unknown', 1.0
    if vix < VIX_CALM_THRESHOLD:
        return 'calm', 0.5       # wenig Prämie, Hälfte der Kontrakte
    if vix < VIX_ELEVATED_THRESHOLD:
        return 'normal', 1.0
    if vix < VIX_CRISIS_THRESHOLD:
        return 'elevated', 0.75  # gut für Premium, aber etwas konservativer
    return 'crisis', 0.0          # Gap-Risiko zu hoch → kein neuer Trade


def check_event_lock() -> tuple:
    """Prüft ob ein Makro-Event (CPI/FOMC/NFP) innerhalb EVENT_LOCK_HOURS liegt.
    Gibt (locked, reason_str) zurück."""
    now = datetime.now()
    for ds in _MACRO_EVENTS:
        try:
            ev_dt = datetime.strptime(ds, '%Y-%m-%d').replace(hour=8, minute=30)
            hours = (ev_dt - now).total_seconds() / 3600
            if -2 <= hours <= EVENT_LOCK_HOURS:
                label = 'CPI/NFP/FOMC'
                return True, f"{label} am {ds} (noch {max(0, hours):.0f}h)"
        except Exception:
            continue
    return False, ''


async def check_kill_switch(ib) -> bool:
    """Liest Tages-P&L aus IBKR; setzt _kill_switch_active wenn Limit überschritten.
    Gibt True zurück wenn Trading gestoppt werden soll."""
    global _kill_switch_active, _kill_switch_reason
    if _kill_switch_active:
        return True
    if MAX_DAILY_LOSS <= 0 and MAX_WEEKLY_LOSS <= 0:
        return False
    if not ib or not ib.isConnected():
        return False
    try:
        acct_vals = ib.accountValues()
        def _val(tag):
            for v in acct_vals:
                if v.tag == tag and v.currency in ('USD', '') and v.value not in ('', '-'):
                    try:
                        return float(v.value)
                    except Exception:
                        pass
            return None
        day_pnl = _val('DayPnL')
        if day_pnl is None:
            realized   = _val('RealizedPnL') or 0.0
            unrealized = _val('UnrealizedPnL') or 0.0
            day_pnl = realized + unrealized
        if MAX_DAILY_LOSS > 0 and day_pnl < -MAX_DAILY_LOSS:
            _kill_switch_reason = f"Tages-P&L ${day_pnl:+.0f} < -${MAX_DAILY_LOSS:.0f}"
            _kill_switch_active = True
            log(f"  🛑 KILL-SWITCH aktiv: {_kill_switch_reason} — kein neuer Trade bis Neustart")
            return True
    except Exception as e:
        log(f"  ⚠️  Kill-Switch-Check fehlgeschlagen: {e}")
    return False


# ── Liquidity Scoring: Rolling Stats per Symbol ──────────────────────────────
# Vergleich erfolgt relativ zu den historischen Werten des Symbols selbst (P90),
# nicht gegen absolute Schwellenwerte. Selbst-kalibrierend über die Laufzeit.
_liq_stats: dict = {}   # symbol → {'oi': [float, ...], 'vol': [float, ...]}

def _update_liq_stats(symbol: str, oi: float, vol: float) -> None:
    s = _liq_stats.setdefault(symbol, {'oi': [], 'vol': []})
    if oi >= 0:
        s['oi'].append(oi)
        if len(s['oi']) > 50:
            s['oi'].pop(0)
    if vol >= 0:
        s['vol'].append(vol)
        if len(s['vol']) > 50:
            s['vol'].pop(0)

def _compute_liq_score(symbol: str, oi: float, vol: float) -> float:
    """log1p-basierter Liquidity Score 0–1. Relativ zu symbol-eigener P90-Historie
    (≥5 Datenpunkte), sonst Fallback auf absolute Referenzwerte."""
    oi  = max(0.0, oi)
    vol = max(0.0, vol)
    s = _liq_stats.get(symbol, {})
    oi_vals  = s.get('oi',  [])
    vol_vals = s.get('vol', [])
    if len(oi_vals) >= 5 and len(vol_vals) >= 5:
        # Percentile-basiert: aktueller Wert relativ zu P90 des Symbols
        oi_p90  = sorted(oi_vals) [int(len(oi_vals)  * 0.9)]
        vol_p90 = sorted(vol_vals)[int(len(vol_vals) * 0.9)]
        oi_score  = math.log1p(oi)  / math.log1p(max(oi_p90,  1))
        vol_score = math.log1p(vol) / math.log1p(max(vol_p90, 1))
    else:
        # Fallback: Normierung gegen konfigurierte Referenzwerte
        oi_score  = math.log1p(oi)  / math.log1p(max(MIN_OPEN_INTEREST,  1))
        vol_score = math.log1p(vol) / math.log1p(max(MIN_OPTION_VOLUME,  1))
    return min(1.0, oi_score * 0.6 + vol_score * 0.4)


async def build_bull_put_spread(symbol, preis, iv, ib=None, news_hit: bool = False, iv_spike: bool = False):
    """Berechnet Bull-Put-Spread. Gibt Signal-Dict zurück oder None."""
    try:
        # ── 1. Expiry-Auswahl aus IB Strike-Map ──────────────────────────────
        if symbol not in _strike_map or not _strike_map[symbol].get('expirations'):
            log(f"   [{symbol}] ✗ Keine IB Strike-Map — überspringe")
            return None

        map_entry = _strike_map[symbol]
        today     = datetime.now()
        dte_map   = []
        for e in map_entry['expirations']:
            try:
                dte_map.append((e, (datetime.strptime(e, '%Y%m%d') - today).days))
            except Exception:
                pass

        valid = [e for e, d in dte_map if MIN_DTE <= d <= MAX_DTE]
        if not valid:
            candidates = [(e, d) for e, d in dte_map if d >= 21]
            if not candidates:
                return None
            expiry_ib_str = min(candidates, key=lambda x: abs(x[1] - MIN_DTE))[0]
        else:
            expiry_ib_str = valid[0]

        expiry_yf = f"{expiry_ib_str[:4]}-{expiry_ib_str[4:6]}-{expiry_ib_str[6:]}"
        dte       = (datetime.strptime(expiry_ib_str, '%Y%m%d') - today).days

        # ── 2. Earnings-Check ─────────────────────────────────────────────────
        hard_block, earn_penalty, conflict_reason = await check_earnings_conflict(symbol, expiry_yf)
        if hard_block:
            log(f"   [{symbol}] 🚫 Earnings-HardBlock: {conflict_reason} — überspringe")
            _shadow_partial(symbol, preis, iv, 'earnings', conflict_reason, expiry=expiry_yf)
            return None
        if earn_penalty > 0:
            log(f"   [{symbol}] ⚠️  Earnings-Penalty: {conflict_reason} → Score -{earn_penalty:.2f}")

        # ── 3. Strike-Auswahl direkt aus IB Strike-Map ───────────────────────
        ib_strikes  = sorted(map_entry['strikes'])
        target      = preis * (1 - ABSTAND_Y)
        valid_short = [s for s in ib_strikes if s < preis]
        if not valid_short:
            log(f"   [{symbol}] ✗ Keine OTM Strikes in IB Strike-Map — überspringe")
            return None
        short_strike = _round_to_standard_strike(
            min(valid_short, key=lambda s: abs(s - target)), preis
        )

        # ── 4. IB Marktdaten für Short-Put (Bid/Ask) ─────────────────────────
        if not (ib and ib.isConnected()):
            return None
        global _sem_ib_mktdata
        if _sem_ib_mktdata is None:
            _sem_ib_mktdata = asyncio.Semaphore(2)

        # Qualifizierung: wenn gerundeter Strike für diese Expiry nicht existiert,
        # nächsten IB-Strike probieren (Strike-Map enthält Strikes aus allen Expiries)
        t_scan = None
        for _try_strike in sorted(valid_short, key=lambda s: abs(s - short_strike))[:4]:
            _candidate = _round_to_standard_strike(_try_strike, preis)
            try:
                _con = Option(symbol, expiry_ib_str, _candidate, 'P', 'SMART')
                await ib.qualifyContractsAsync(_con)
                if _con.conId:
                    short_strike = _candidate
                    async with _sem_ib_mktdata:
                        t_scan = ib.reqMktData(_con, '', False, False)
                        await asyncio.sleep(8)
                        try:
                            ib.cancelMktData(t_scan)
                        except Exception:
                            pass
                    break
            except Exception:
                continue

        if t_scan is None:
            log(f"   [{symbol}] ✗ Short-Put nicht qualifizierbar — überspringe")
            return None

        _sb = t_scan.bid if (t_scan.bid and not math.isnan(t_scan.bid) and t_scan.bid > 0) else 0.0
        _sa = t_scan.ask if (t_scan.ask and not math.isnan(t_scan.ask) and t_scan.ask > 0) else 0.0

        # modelGreeks-Fallback: IB Delayed liefert oft kein echtes Bid/Ask für Optionen
        if _sb == 0.0:
            _mg = getattr(t_scan, 'modelGreeks', None)
            if _mg and getattr(_mg, 'optPrice', None) and not math.isnan(_mg.optPrice) and _mg.optPrice > 0:
                _sb = float(_mg.optPrice)
                _sa = _sb * 1.05  # synthetischer Ask: +5% als konservativer Spread

        # ── 5. Liquiditäts-Check via Bid/Ask (OI/Volume in Delayed-Daten nicht verfügbar) ─
        if _sb == 0 and _sa == 0:
            log(f"   [{symbol}] ✗ Kein Bid/Ask von IB — überspringe")
            _shadow_partial(symbol, preis, iv, 'liquidity', "Kein IB-Bid/Ask", short_strike=short_strike)
            return None
        if _sb > 0 and _sa > 0:
            _ba_pct = (_sa - _sb) / ((_sb + _sa) / 2)
            if _ba_pct > MAX_BID_ASK_SPREAD:
                log(f"   [{symbol}] ✗ Bid/Ask-Spread {_ba_pct:.1%} > {MAX_BID_ASK_SPREAD:.1%} — zu illiquide")
                _shadow_partial(symbol, preis, iv, 'liquidity',
                                f"BidAskSpread={_ba_pct:.1%} > {MAX_BID_ASK_SPREAD:.1%}",
                                short_strike=short_strike)
                return None
            _liquidity_score = max(0.1, 1.0 - _ba_pct * 3)
        else:
            _liquidity_score = 0.4

        # ── 6. Initiale Prämie aus IB-Bid ─────────────────────────────────────
        bid = _sb
        if not bid > 0:
            log(f"   [{symbol}] ✗ Kein IB-Bid für Short-Put — überspringe")
            _shadow_partial(symbol, preis, iv, 'no_live_data', "Kein IB-Bid", short_strike=short_strike)
            return None
        praemie        = bid
        praemie_quelle = "IB (Bid)"

        # ── 7. Long-Strike und Spread-Breite ──────────────────────────────────
        valid_long  = [s for s in ib_strikes if s < short_strike]
        spread_max  = max(SPREAD_MIN, round(preis * SPREAD_MAX_PCT / 5) * 5)
        breite_ziel = max(SPREAD_MIN, min(math.ceil((praemie * 4) / 5) * 5, spread_max))
        if valid_long:
            long_target = short_strike - breite_ziel
            snapped_l   = min(valid_long, key=lambda s: abs(s - long_target))
            long_strike = _round_to_standard_strike(snapped_l, preis)
        else:
            long_strike = short_strike - SPREAD_MIN
        breite = short_strike - long_strike

        # ── Long-Put Ask holen → echter Netto-Credit (Short-Bid minus Long-Ask) ──
        _long_ask_net = 0.0
        try:
            _l_con_net = Option(symbol, expiry_ib_str, long_strike, 'P', 'SMART')
            await ib.qualifyContractsAsync(_l_con_net)
            if _l_con_net.conId > 0:
                async with _sem_ib_mktdata:
                    _t_long = ib.reqMktData(_l_con_net, '', False, False)
                    await asyncio.sleep(5)
                    _la = _t_long.ask if (_t_long.ask and not math.isnan(_t_long.ask) and _t_long.ask > 0) else 0.0
                    if _la == 0.0:
                        _la = _t_long.bid if (_t_long.bid and not math.isnan(_t_long.bid) and _t_long.bid > 0) else 0.0
                    try:
                        ib.cancelMktData(_t_long)
                    except Exception:
                        pass
                _long_ask_net = _la
        except Exception:
            pass

        if _long_ask_net > 0:
            praemie        = max(_sb - _long_ask_net, 0.01)
            praemie_quelle = "IB (Net-Bid)"

        # ── IB Combo/Bag Pricing (verbessert Prämie von IB-Bid zu Netto-Credit) ─
        try:
            s_con = Option(symbol, expiry_ib_str, short_strike, 'P', 'SMART')
            l_con = Option(symbol, expiry_ib_str, long_strike,  'P', 'SMART')
            await ib.qualifyContractsAsync(s_con, l_con)
            if s_con.conId > 0 and l_con.conId > 0:
                combo_bag = Bag(
                    symbol=symbol, exchange='SMART', currency='USD',
                    comboLegs=[
                        ComboLeg(conId=s_con.conId, ratio=1, action='SELL', exchange='SMART'),
                        ComboLeg(conId=l_con.conId, ratio=1, action='BUY',  exchange='SMART'),
                    ]
                )
                async with _sem_ib_mktdata:
                    t_combo = ib.reqMktData(combo_bag, '', False, False)
                    await asyncio.sleep(5)
                    combo_bid = t_combo.bid if (t_combo.bid and not math.isnan(t_combo.bid)) else None
                    try: ib.cancelMktData(t_combo)
                    except Exception: pass
                if combo_bid is not None and combo_bid > 0:
                    praemie        = combo_bid
                    praemie_quelle = "IB (Combo)"
                # else: IB-Bid aus Schritt 6 bleibt erhalten
        except Exception:
            pass  # IB-Bid aus Schritt 6 bleibt erhalten

        if praemie_quelle == "Black-Scholes (geschätzt)":
            log(f"   [{symbol}] ✗ Keine Live-/Delayed-Daten verfügbar — Symbol übersprungen")
            _shadow_partial(symbol, preis, iv, 'no_live_data', "Keine verwertbaren Marktdaten",
                            short_strike=short_strike)
            return None

        credit    = praemie * 100
        max_risk  = (breite - praemie) * 100
        rr        = praemie / (breite - praemie) if breite > praemie else 0.0
        T         = max(dte / 365, 0.001)
        prob_otm      = _bs_prob_otm(preis, short_strike, T, iv)
        prob_max_loss = 1.0 - _bs_prob_otm(preis, long_strike, T, iv)

        # Slippage-adjustierter EV: theoretischen Credit um erwarteten Fill-Abschlag korrigieren
        _slip     = SLIPPAGE_FACTOR.get(praemie_quelle, SLIPPAGE_FACTOR['default'])
        eff_credit = credit * _slip
        ev        = (prob_otm * eff_credit) - (prob_max_loss * max_risk)
        ev_raw    = (prob_otm * credit)     - (prob_max_loss * max_risk)   # ohne Slippage (Info)
        ev_ratio  = ev / eff_credit if eff_credit > 0 else 0.0

        # ── Hard-Gates (vor Score, kein Penalty-Ausgleich möglich) ──────
        if prob_otm > MAX_PROBABILITY:
            log(f"   [{symbol}] ✗ P(Win)={prob_otm:.1%} > {MAX_PROBABILITY:.0%} — Credit zu klein, überspringe")
            _shadow_partial(symbol, preis, iv, 'prob_otm', f"P(Win)={prob_otm:.1%}>{MAX_PROBABILITY:.0%}",
                            short_strike=short_strike)
            return None
        if prob_max_loss > MAX_LOSS_PROB:
            log(f"   [{symbol}] ✗ P(MaxVerlust)={prob_max_loss:.1%} > {MAX_LOSS_PROB:.0%} — Totalverlustrisiko zu hoch")
            _shadow_partial(symbol, preis, iv, 'prob_max_loss', f"P(MaxL)={prob_max_loss:.1%}>{MAX_LOSS_PROB:.0%}",
                            short_strike=short_strike)
            return None
        if ev_ratio < MIN_EV_RATIO:
            log(f"   [{symbol}] ✗ EV-Ratio={ev_ratio:.3f} < {MIN_EV_RATIO} — kein statistischer Vorteil")
            _shadow_partial(symbol, preis, iv, 'ev_ratio', f"EV-Ratio={ev_ratio:.3f}<{MIN_EV_RATIO}",
                            short_strike=short_strike)
            return None

        # ── Deterministischer 4-Komponenten Score ────────────────────────
        _iv_penalty  = IV_SOFT_PENALTY if iv < MIN_VOLA_SOFT else 0.0
        _credit_pct  = credit / (breite * 100) if breite > 0 else 0.0
        _rr_norm     = min(rr / MIN_RISK_REWARD, 1.0)
        _credit_norm = min(_credit_pct / MIN_CREDIT_PERCENT, 1.0)
        _news_bonus  = 0.05 if news_hit else 0.0

        score = min(1.0, max(0.0,
            0.35 * prob_otm
            + 0.30 * _rr_norm
            + 0.25 * _credit_norm
            + 0.10 * _liquidity_score
            + _news_bonus
            - earn_penalty
            - _iv_penalty
        ))
        decision = 'TRADE' if score >= ENTRY_THRESHOLD else 'WATCH' if score >= WATCH_THRESHOLD else 'SKIP'

        # Hard-Gate: Mindest-Credit-Größe (Infrastruktur, kein Score-Thema)
        credit_ok_hard = credit >= max(breite * 100 * MIN_CREDIT_PERCENT, MIN_CREDIT_ABS)

        return {
            'symbol':           symbol,
            'preis':            preis,
            'iv':               iv,
            'dte':              dte,
            'expiry_ib':        expiry_ib_str,
            'short_strike':     short_strike,
            'long_strike':      long_strike,
            'breite':           breite,
            'praemie':          praemie,
            'praemie_quelle':   praemie_quelle,
            'credit':           credit,
            'max_risk':         max_risk,
            'risk_reward':      rr,
            'prob_otm':         prob_otm,
            'prob_max_loss':    prob_max_loss,
            'ev':               ev,
            'ev_raw':           ev_raw,
            'ev_ratio':         ev_ratio,
            'slippage_factor':  _slip,
            'score':            score,
            'decision':         decision,
            'edge':             round(0.35 * prob_otm + 0.30 * _rr_norm, 4),
            'risk':             round(earn_penalty + _iv_penalty, 4),
            'quality':          round(0.25 * _credit_norm + 0.10 * _liquidity_score + _news_bonus, 4),
            'liquidity_score':  round(_liquidity_score, 3),
            'earnings_penalty': earn_penalty,
            'iv_penalty':       _iv_penalty,
            'credit_ok_hard':   credit_ok_hard,
        }
    except asyncio.TimeoutError:
        log(f"   [{symbol}] ⏱️  build_bull_put_spread Timeout — überspringe")
        return None
    except Exception as e:
        log(f"   [{symbol}] ❌ build_bull_put_spread Fehler: {e}")
        return None

def count_bot_orders():
    """Zählt aktive Spread-Orders des Bots — ignoriert reine Aktien-Positionen."""
    return sum(1 for info in _bot_trades.values()
               if info.get('status') in ('open', 'closing', 'exit_retry')
               and info.get('short_conid'))

async def has_open_position(ib, symbol):
    try:
        return any(p.contract.symbol == symbol for p in ib.positions())
    except Exception:
        return False

def already_traded(symbol):
    """Blockiert nur wenn eine echte Position aktiv ist oder gerade platziert wird.
    'done'/'cancelled'/'failed' = Position geschlossen/kein Fill → Retrade erlaubt.
    place_order prüft zusätzlich via ib.positions() gegen doppelte Eröffnung."""
    return symbol in _bot_trades and _bot_trades[symbol].get('status') in (
        'open', 'closing', 'placing', 'exit_retry', 'recovery_pending')

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
            global _sem_ib_mktdata
            if _sem_ib_mktdata is None:
                _sem_ib_mktdata = asyncio.Semaphore(2)
            async with _sem_ib_mktdata:
                t_s = ib.reqMktData(s_contract, '', False, False)
                t_l = ib.reqMktData(l_contract,  '', False, False)
                await asyncio.sleep(4)
                s_bid = t_s.bid if (t_s.bid and t_s.bid > 0) else None
                s_ask = t_s.ask if (t_s.ask and t_s.ask > 0) else None
                l_bid = t_l.bid if (t_l.bid and t_l.bid > 0) else None
            try: ib.cancelMktData(t_s)
            except Exception: pass
            try: ib.cancelMktData(t_l)
            except Exception: pass
            # IB-Daten nur verwenden wenn Short-Leg einen echten Bid hat.
            # Kein Bid = illiquide/wertlos — Ask ist dann oft ein veralteter
            # Stale-Order der den echten Marktwert massiv überschätzt.
            if s_bid is not None:
                ask = s_ask if s_ask else s_bid + 0.01
                bid = l_bid if l_bid else 0.0
                spread_width = short_strike - long_strike
                return min(max(0.0, ask - bid), spread_width)
            # Kein Bid auf Short-Leg → IB-Daten unzuverlässig → yfinance
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
        s_ask_val = float(short_ask[0])
        if s_ask_val <= 0:
            return None   # kein valider Marktpreis (Markt geschlossen / yfinance-Cache)
        return max(0.0, s_ask_val - float(long_bid[0]))
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=20)
    except (asyncio.TimeoutError, Exception):
        return None

async def close_spread(ib, symbol, info, reason):
    """Exit-State-Machine: CANCEL → WAIT → GATE → PLACE.

    Kein reqGlobalCancel im Live-Flow (erzeugt Race Conditions).
    Jede Order wird genau einmal gecancelt — kein Spam.
    Polling ist read-only — keine weiteren Cancels während Warten.
    Hard-Gate vor placeOrder: IB muss wirklich sauber sein.
    """
    _BLOCKING  = {'Submitted', 'PreSubmitted', 'PendingSubmit', 'PendingCancel', 'ApiPending'}
    _TERMINAL  = {'Filled', 'Cancelled', 'ApiCancelled'}

    try:
        if ib is not None:
            # ── PHASE 1: CANCEL (jede Order genau einmal) ──────────────────────────
            log(f"  🧹 [{symbol}] Exit-Cancel: storniere aktive Orders ...")
            await ib.reqAllOpenOrdersAsync()
            _cancelled_ids: set = set()

            # A: gespeicherte TP/SL-IDs einmalig direkt canceln (mit Pacing)
            for label, oid in [('TP', info.get('tp_order_id', 0)),
                                ('SL', info.get('sl_order_id', 0))]:
                if not oid or oid <= 0 or oid in _cancelled_ids:
                    continue
                _expected_cancels.add(oid)
                try:
                    await _ib_cancel_paced(ib, oid)
                    _cancelled_ids.add(oid)
                    log(f"  🗑  [{symbol}] {label}-Order #{oid} storniert")
                except Exception as e:
                    log(f"  ⚠️  [{symbol}] {label}-Cancel #{oid}: {e}")

            # B: alle sichtbaren blocking + Inactive Orders für dieses Symbol einmalig canceln
            for t in ib.trades():
                if t.contract.symbol != symbol:
                    continue
                if t.orderStatus.status not in (_BLOCKING | {'Inactive'}):
                    continue
                oid = t.order.orderId or 0
                if oid <= 0 or oid in _cancelled_ids:
                    continue
                _expected_cancels.add(oid)
                try:
                    await _ib_cancel_paced(ib, oid)
                    _cancelled_ids.add(oid)
                    log(f"  🗑  [{symbol}] Order #{oid} ({t.orderStatus.status}) storniert")
                except Exception:
                    pass

            # ── PHASE 2: WAIT — IB-Server-Sync abwarten ────────────────────────────
            await asyncio.sleep(2.0)

            # ── PHASE 3: GATE-POLL (read-only) ─────────────────────────────────────
            # Wartet NUR darauf dass die in Phase 1 gecancelten Order-IDs verschwinden.
            # Prüft NICHT account-weit (würde bei aktiven Brackets anderer Positionen
            # nie sauber sein). Wenn nichts gecancelt wurde → sofort weiter.
            cancel_confirmed = False
            if not _cancelled_ids:
                cancel_confirmed = True  # nichts gecancelt → kein Warten nötig
            else:
                for _attempt in range(40):  # 40 × 0.5s = 20s Timeout
                    await asyncio.sleep(0.5)
                    fresh = await ib.reqAllOpenOrdersAsync()
                    _all_active_oids = {
                        t.order.orderId
                        for t in (fresh if fresh is not None else ib.openTrades())
                        if t.orderStatus.status in _BLOCKING
                    }
                    # Nur Server-bestätigte aktive Orders blockieren — Inactive Orders
                    # die bereits gecancelt wurden tauchen nicht mehr in reqAllOpenOrders
                    # auf und sind IB-seitig erledigt (lokaler Cache hinkt nach).
                    _still_blocking = _cancelled_ids & _all_active_oids
                    if not _still_blocking:
                        cancel_confirmed = True
                        break
                    if _attempt % 6 == 0:
                        log(f"  ⏳ [{symbol}] Warte auf Cancel-Bestätigung ({_attempt+1}/40): {_still_blocking}")

                if not cancel_confirmed:
                    log(f"  🔄 [{symbol}] Timeout (20s) — 5s Extra-Puffer ...")
                    await asyncio.sleep(5.0)
                    _final_fresh = await ib.reqAllOpenOrdersAsync()
                    _final_oids = {
                        t.order.orderId
                        for t in (_final_fresh if _final_fresh is not None else ib.openTrades())
                        if t.orderStatus.status in _BLOCKING
                    }
                    _still = _cancelled_ids & _final_oids
                    if _still:
                        _delay = _exit_retry_delay(info)
                        log(f"  ❌ [{symbol}] Cancel nicht bestätigt nach 25s: {_still} — "
                            f"EXIT_RETRY in {_delay}s (Versuch #{info.get('retry_count', 1)})")
                        info['status']   = 'exit_retry'
                        info['retry_at'] = (datetime.now() + timedelta(seconds=_delay)).timestamp()
                        _save_state()
                        return
                    cancel_confirmed = True

            # ── PRE-FLIGHT: IB Combo-Order-Limit prüfen ────────────────────────────
            # IB erlaubt max. ~10 aktive Combo/BAG-Orders account-weit.
            # Bracket-Orders anderer Positionen zählen mit → Limit kann überschritten sein.
            await ib.reqAllOpenOrdersAsync()
            await asyncio.sleep(0.3)
            _active_combos = [
                t for t in ib.openTrades()
                if t.contract.secType == 'BAG'
                and t.orderStatus.status in _BLOCKING
            ]
            _IB_COMBO_LIMIT = 7  # konservativ: IB-Limit scheint bei 8 zu liegen, 1 Slot für unsere Order
            if len(_active_combos) >= _IB_COMBO_LIMIT:
                _delay = _exit_retry_delay(info)
                log(f"  ⏳ [{symbol}] IB-Combo-Limit: {len(_active_combos)}/{_IB_COMBO_LIMIT} "
                    f"aktive BAG-Orders — EXIT_RETRY in {_delay}s (warte bis andere Orders füllen/canceln)")
                info['status']   = 'exit_retry'
                info['retry_at'] = (datetime.now() + timedelta(seconds=_delay)).timestamp()
                _save_state()
                return

            log(f"  ✅ [{symbol}] IB clean ({len(_active_combos)} aktive BAGs) — sende Exit-Order")

        # ── PHASE 4: PLACE ──────────────────────────────────────────────────────
        # BUY kehrt Legs um: SELL short_put (deckt Short) + BUY long_put (schließt Long)
        bag = Bag(
            symbol=symbol, exchange='SMART', currency='USD',
            comboLegs=[
                ComboLeg(conId=info['short_conid'], ratio=1, action='SELL', exchange='SMART'),
                ComboLeg(conId=info['long_conid'],  ratio=1, action='BUY',  exchange='SMART'),
            ]
        )
        entry = info['entry_per_share']
        info['close_reason'] = reason

        if not is_market_open():
            _secs, _open_et = seconds_until_market_open()
            info['status']   = 'exit_retry'
            info['retry_at'] = (datetime.now() + timedelta(seconds=_secs + 30)).timestamp()
            log(f"  ⏸️  [{symbol}] Markt geschlossen — Exit bei Öffnung ({_open_et.strftime('%H:%M ET')})")
            _save_state()
            return

        info['status'] = 'closing'
        info['close_initiated_at'] = datetime.now().timestamp()

        _cur_exit = await get_spread_value(
            symbol, info.get('expiry_yf', ''),
            info.get('short_strike', 0), info.get('long_strike', 0), ib)
        _spread_width = abs(info.get('short_strike', 0) - info.get('long_strike', 0))
        if _cur_exit and _cur_exit >= 0.02:
            close_limit = round(_cur_exit * 2.0, 2)
            src = f'live ${_cur_exit*100:.0f}¢ ×2 (sofort-Fill)'
        elif entry and entry >= 0.10:
            close_limit = round(entry * 2.0, 2)
            src = f'entry×2 (${entry:.2f})'
        elif _spread_width > 0:
            close_limit = round(_spread_width * 0.80, 2)
            src = f'spread-width fallback (80% von ${_spread_width:.0f})'
        else:
            close_limit = 5.00
            src = 'absolute fallback'
        close_limit = max(close_limit, 0.05)
        order = LimitOrder('BUY', 1, close_limit, tif='DAY')
        order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        order.account = _cfg.get('ib_account', '')
        if _ibq is not None:
            trade = await _ibq.place(ib, bag, order)
        else:
            trade = ib.placeOrder(bag, order)
        info['exit_order_id'] = trade.order.orderId
        log(f"  ⏰ [{symbol}] EXIT {reason} @ ${close_limit:.2f} DAY ({src}) | Order #{trade.order.orderId}")
    except Exception as e:
        import traceback
        log(f"  ❌ [{symbol}] Exit-Fehler: {e}\n{traceback.format_exc()}")

async def _process_close_commands(ib):
    """Verarbeitet manuelle Exit-Befehle die das Frontend in close_commands.json schreibt."""
    if not os.path.exists(_CLOSE_CMD_FILE):
        return
    try:
        with open(_CLOSE_CMD_FILE) as f:
            cmds = json.load(f)
        if not cmds:
            return
        os.remove(_CLOSE_CMD_FILE)   # sofort löschen → kein Doppel-Exit
        for sym in cmds:
            info = _bot_trades.get(sym)
            if info and info.get('status') in ('open', 'error', 'exit_retry'):
                log(f"  🖱️  [{sym}] Manueller Exit via Frontend (Status: {info.get('status')})")
                info['status'] = 'open'   # Reset damit close_spread() durchläuft
                info.pop('retry_count', None)
                async with _sym_lock(sym):
                    await close_spread(ib, sym, info, 'MANUAL_EXIT')
            elif info and info.get('status') == 'closing':
                log(f"  ⚠️  [{sym}] Manueller Exit: Position schließt bereits ...")
            elif info:
                log(f"  ⚠️  [{sym}] Manueller Exit ignoriert — Status: {info.get('status')}")
    except Exception as e:
        log(f"  ⚠️  Close-Command Fehler: {e}")

async def monitor_exits(ib=None):
    """DTE-Exit und Breakeven-Update. TP/SL werden von IBKR-Bracket-Orders verwaltet."""
    if ib:
        await _process_close_commands(ib)
    if not _bot_trades:
        return

    # IB-Abgleich: Positionen die manuell in CapTrader geschlossen wurden sofort entfernen
    if ib is not None:
        try:
            _ib_syms = {p.contract.symbol for p in ib.positions()
                        if p.contract.secType == 'OPT' and p.position != 0}
            _ib_order_syms = {t.contract.symbol for t in ib.openTrades()
                              if t.contract.secType in ('OPT', 'BAG')}
            _active_statuses = ('open', 'exit_retry', 'error')  # 'closing' nie entfernen — Exit-Order läuft
            _removed = []
            for _sym, _info in list(_bot_trades.items()):
                if _info.get('status') in _active_statuses:
                    if _sym not in _ib_syms and _sym not in _ib_order_syms:
                        _bot_trades.pop(_sym, None)
                        _removed.append(_sym)
            if _removed:
                _save_state()
                log(f"  🧹 IB-Abgleich: {_removed} manuell geschlossen — aus State entfernt")
        except Exception:
            pass
    for symbol, info in list(_bot_trades.items()):
        # EXIT_RETRY: Exit-Order wurde abgelehnt — nach 60s Cooldown erneut versuchen
        if info.get('status') == 'exit_retry':
            if not ib:
                continue
            retry_at = info.get('retry_at', 0)
            remaining = int(retry_at - datetime.now().timestamp())
            if remaining > 0:
                log(f"  ⏳ [{symbol}] EXIT_RETRY: Warte noch {remaining}s bis Retry")
                continue
            # Self-Healing: TP-Exit wegen $0-Daten (Markt geschlossen) → zurück auf 'open'
            if info.get('close_reason') == 'TP_HIT':
                _entry_h = info.get('entry_per_share', 0)
                _tp_h    = round(_entry_h * (1 - TAKE_PROFIT_PCT), 2)
                _cur_h   = await get_spread_value(
                    symbol, info.get('expiry_yf',''), info.get('short_strike',0),
                    info.get('long_strike',0), ib)
                if _cur_h is None or _cur_h < 0.02 or _cur_h > _tp_h:
                    log(f"  🔄 [{symbol}] EXIT_RETRY-Reset: TP-Trigger war ungültig "
                        f"(Markt war geschlossen) — zurück auf 'open'")
                    info['status']       = 'open'
                    info['close_reason'] = ''
                    info.pop('tp_hit', None)
                    info.pop('retry_count', None)
                    _save_state()
                    continue
            # Dead-State: nach 5 erfolglosen Versuchen manuellen Eingriff verlangen.
            # Verhindert Endlos-Loop der das IB-Combo-Limit dauerhaft blockiert.
            if info.get('retry_count', 0) > len(_EXIT_RETRY_BACKOFF):
                log(f"  🛑 [{symbol}] EXIT_RETRY: {info['retry_count']} Versuche alle fehlgeschlagen "
                    f"— manueller Eingriff erforderlich! Position in CapTrader prüfen und schließen.")
                info['status'] = 'error'
                _save_state()
                continue
            log(f"  🔁 [{symbol}] EXIT_RETRY: Cooldown abgelaufen — erneuter Schließ-Versuch "
                f"(#{info.get('retry_count', 0) + 1}/{len(_EXIT_RETRY_BACKOFF)})")
            info['status'] = 'closing'   # kurz auf 'closing' für close_spread
            async with _sym_lock(symbol):
                await close_spread(ib, symbol, info, 'RETRY_EXIT')
            continue

        # Stale-Closing: Exit-Order hängt >20 Min ohne Fill → stornieren und sofort neu
        if info.get('status') == 'closing' and ib and is_market_open():
            initiated = info.get('close_initiated_at', 0)
            if initiated and (datetime.now().timestamp() - initiated) > 1200:
                stale_oid = info.get('exit_order_id', 0)
                if stale_oid:
                    try:
                        _expected_cancels.add(stale_oid)
                        ib.client.cancelOrder(stale_oid, '')
                    except Exception:
                        pass
                info['status']   = 'exit_retry'
                info['retry_at'] = datetime.now().timestamp()  # sofort
                info.pop('close_initiated_at', None)
                info.pop('exit_order_id', None)
                _save_state()
                log(f"  🔄 [{symbol}] Stale Exit-Order #{stale_oid} >20min ohne Fill — sofort neu")
            continue

        if info.get('status') != 'open':
            continue

        # Fill-Timeout: Entry-Order nicht gefüllt innerhalb FILL_TIMEOUT_SECONDS?
        if (not info.get('fill_confirmed', True)   # True = rückwärtskompatibel für alte Trades
                and info.get('fill_deadline', '')):
            if datetime.now().isoformat() > info['fill_deadline']:
                entry_oid = info.get('entry_order_id', 0)
                log(f"  ⏱️  [{symbol}] Fill-Timeout ({FILL_TIMEOUT_SECONDS}s) — "
                    f"storniere Entry #{entry_oid}")
                if entry_oid and ib is not None:
                    try:
                        _expected_cancels.add(entry_oid)
                        ib.client.cancelOrder(entry_oid, '')
                    except Exception as e:
                        log(f"  ⚠️  [{symbol}] Entry-Cancel fehlgeschlagen: {e}")
                info['status'] = 'failed'
                _save_state()
                continue

        if not info.get('expiry_yf'):
            continue

        dte_remaining = (datetime.strptime(info['expiry_yf'], '%Y-%m-%d') - datetime.now()).days

        # Bereits abgelaufen (DTE < 0): OTM verfallen → History schreiben, aus State löschen
        if dte_remaining < 0:
            log(f"  🗑️  [{symbol}] Verfallen am {info['expiry_yf']} (OTM) — schreibe History, entferne State")
            async with _sym_lock(symbol):
                info['status'] = 'expired_otm'
                _append_history(symbol, info, exit_per_share=0.0)
                _bot_trades.pop(symbol, None)
                _save_state()
            continue

        # 0-DTE-Exit: immer schließen am Verfallstag (Assignment-Risiko)
        if dte_remaining == 0:
            log(f"  ⏰ [{symbol}] 0-DTE — Verfallstag, schließe Position (Assignment-Risiko)")
            async with _sym_lock(symbol):
                await close_spread(ib, symbol, info, 'EXPIRY_EXIT')
            continue

        # 21-DTE-Exit: nur schließen wenn Kurs nah am Short Strike (Gamma-Gefahr)
        if dte_remaining <= DTE_EXIT:
            preis, _ = await get_market_data(symbol)
            if preis is not None and info.get('short_strike'):
                puffer = (preis - info['short_strike']) / preis
                if puffer < BUFFER_MIN_PCT:
                    log(f"  ⏰ [{symbol}] 21-DTE-Exit: Kurs ${preis:.2f} nur {puffer:.1%} über Short Strike "
                        f"${info['short_strike']:.0f} — soft close")
                    async with _sym_lock(symbol):
                        await close_spread(ib, symbol, info, 'DTE_EXIT')
                    continue
                else:
                    log(f"  ✅ [{symbol}] 21-DTE erreicht — Puffer {puffer:.1%} > {BUFFER_MIN_PCT:.0%} "
                        f"— tief OTM, verfallen lassen")

        entry = info['entry_per_share']
        if not entry or entry <= 0:
            log(f"  ⚠️  [{symbol}] Einstiegspreis nicht bekannt — P&L-Anzeige deaktiviert "
                f"(Bot-Neustart während offener Position?)")
            continue

        # ── Anzeige-P&L aus ib.portfolio() (gleicher Wert wie CapTrader) ────────────
        # Nur für die UI-Anzeige — IB cached Combo-Werte und friert manchmal ein.
        _pnl_display = None
        if ib is not None:
            try:
                expiry_ib_pfx = info['expiry_yf'].replace('-', '')
                _pf = ib.portfolio()
                _legs = [p for p in _pf
                         if p.contract.symbol == symbol
                         and p.contract.secType == 'OPT'
                         and p.contract.right == 'P'
                         and p.contract.lastTradeDateOrContractMonth.startswith(expiry_ib_pfx)
                         and (abs(p.contract.strike - info['short_strike']) < 0.5
                              or abs(p.contract.strike - info['long_strike']) < 0.5)
                         and p.unrealizedPNL is not None
                         and not math.isnan(p.unrealizedPNL)]
                if len(_legs) >= 2:
                    _pnl_display = round(sum(p.unrealizedPNL for p in _legs), 2)
            except Exception:
                pass

        # ── Aktueller Spread-Preis aus Einzel-Legs (immer frisch, nie eingefroren) ──
        # IB berechnet Combo-Preise aus dem letzten Combo-Trade — der kann stundenlang
        # eingefroren sein. Einzel-Legs liefern immer echte Live-Bid/Ask-Kurse.
        current = await get_spread_value(
            symbol, info['expiry_yf'], info['short_strike'], info['long_strike'], ib
        )
        if current is None:
            log(f"  ⚠️  [{symbol}] Kein Marktpreis verfügbar — überspringe")
            continue
        current = max(0.0, current)

        n_contracts = max(1, info.get('n_contracts', 1))
        pnl_per_ctr = round((entry - current) * 100, 2)   # 1 Kontrakt, preis-basiert
        # Daten-Qualitätsprüfung: current < $0.02 bedeutet Markt geschlossen oder stale Daten
        # (ein aktiver Options-Spread kann nicht legitim $0 wert sein wenn DTE > 0)
        if current < 0.02:
            log(f"  ⏸  [{symbol}] Marktpreis ${current*100:.1f}¢ — kein valider Kurs "
                f"(Markt geschlossen?), überspringe TP/SL-Check")
            if _pnl_display is not None:
                info['unrealized_pnl'] = round(_pnl_display, 2)
            continue

        pnl_dollar  = _pnl_display if _pnl_display is not None \
                      else round(pnl_per_ctr * n_contracts, 2)
        pnl_share   = pnl_per_ctr / 100
        pnl_pct     = (pnl_per_ctr / (entry * 100) * 100) if entry > 0 else 0

        # Breakeven: bestehende SL-Order auf Breakeven-Preis modifizieren (Modify, kein Cancel)
        # Kein Cancel des TP nötig → kein Error 201 (TP-Leg BUY long_put ≠ BE-SL SELL long_put
        # tritt nur auf wenn neues Bag mit umgekehrten Legs platziert wird)
        if pnl_share >= entry * BREAKEVEN_TRIGGER_PCT and not info.get('at_breakeven'):
            async with _sym_lock(symbol):
                if info.get('at_breakeven'):     # double-check nach Lock-Erwerb
                    pass
                else:
                    info['at_breakeven'] = True
                    be_close = round(entry * 1.02, 2)  # entry + 2% Puffer für Slippage
                    sl_order_id = info.get('sl_order_id', 0)
                    sl_modified = False

                    # Primär: bestehende SL-Order auf Breakeven-Preis modifizieren (kein Cancel nötig)
                    if sl_order_id and ib is not None:
                        await ib.reqAllOpenOrdersAsync()
                        await asyncio.sleep(0.5)
                        for t in ib.openTrades():
                            if t.order.orderId == sl_order_id:
                                t.order.lmtPrice = be_close
                                if _ibq is not None:
                                    asyncio.ensure_future(_ibq.place(ib, t.contract, t.order))
                                else:
                                    ib.placeOrder(t.contract, t.order)
                                sl_modified = True
                                log(f"  🔒 [{symbol}] Breakeven-SL @ ${be_close:.2f} GTC "
                                    f"(Modify #{sl_order_id}) | P&L: +${pnl_dollar:.0f}")
                                break

                    if not sl_modified:
                        # SL bereits weg → neue Closing-Bag-Order würde Error 201 riskieren
                        # (TP-Leg BUY long_put ↔ neues SELL long_put = gegenläufig auf selben Contract)
                        # Sicher: TP und SL stornieren, Position läuft bis Verfall oder 21-DTE-Exit
                        _cancel_order_by_id(ib, info.get('tp_order_id', 0), symbol, 'TP')
                        _cancel_order_by_id(ib, info.get('sl_order_id', 0), symbol, 'SL')
                        log(f"  🔒 [{symbol}] Breakeven: TP/SL storniert — "
                            f"keine neue Order (läuft bis Verfall/DTE-Exit) | P&L: +${pnl_dollar:.0f}")

                    _save_state()

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

        # ── Software-TP/SL Fallback: nur für Positionen OHNE IB-Bracket-Orders ──
        # Betrifft Legacy-Positionen (tp_order_id=0) oder wenn Bracket-Platzierung
        # beim Entry fehlschlug. IB-Bracket-Positionen werden von _on_order_status
        # behandelt — hier niemals eingreifen wenn tp_order_id gesetzt ist.
        if not info.get('tp_order_id') and not info.get('sl_order_id') and ib is not None:
            tp_close_price = round(entry * (1 - TAKE_PROFIT_PCT), 2)
            sl_close_price = round(entry * STOP_LOSS_MULT, 2)
            if current <= tp_close_price and not info.get('tp_hit'):
                log(f"  🎯 [{symbol}] Software-TP (kein Bracket): "
                    f"${current*100:.0f}¢ ≤ ${tp_close_price*100:.0f}¢ — schließe Position")
                async with _sym_lock(symbol):
                    info['tp_hit'] = True
                    _save_state()
                    await close_spread(ib, symbol, info, 'TP_HIT')
                continue
            if current >= sl_close_price and not info.get('sl_hit'):
                log(f"  🛑 [{symbol}] Software-SL (kein Bracket): "
                    f"${current*100:.0f}¢ ≥ ${sl_close_price*100:.0f}¢ — schließe Position")
                async with _sym_lock(symbol):
                    info['sl_hit'] = True
                    _save_state()
                    await close_spread(ib, symbol, info, 'SL_HIT')
                continue

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

        # Mutex: alle Order-Aktionen für dieses Symbol serialisiert
        # (verhindert Error 201: Entry/Exit/Breakeven dürfen nie gleichzeitig Orders senden)
        async with _sym_lock(sym):
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
            global _sem_ib_mktdata
            if _sem_ib_mktdata is None:
                _sem_ib_mktdata = asyncio.Semaphore(2)
            async with _sem_ib_mktdata:
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

            price_src = 'BS_ESTIMATE'   # Default — wird bei besseren Daten überschrieben

            if short_bid is None or long_ask is None:
                def _greek_price(ticker, side):
                    g = ticker.bidGreeks if side == 'bid' else ticker.askGreeks
                    return g.optPrice if g and g.optPrice and g.optPrice > 0 else None
                sb_greek = _greek_price(t_short, 'bid')
                la_greek = _greek_price(t_long,  'ask')
                if sb_greek and la_greek:
                    short_bid = sb_greek
                    long_ask  = la_greek
                    price_src = 'LAST_PRICE'
                    log(f"  ⚠️  [{sym}] Kein Bid/Ask — bidGreeks: Short ${short_bid:.2f}  Long ${long_ask:.2f}")
                else:
                    def _model_price(ticker):
                        g = ticker.modelGreeks
                        return g.optPrice if g and g.optPrice and g.optPrice > 0 else None
                    sb_model = _model_price(t_short)
                    la_model = _model_price(t_long)
                    if sb_model and la_model:
                        short_bid = sb_model
                        long_ask  = la_model
                        price_src = 'LAST_PRICE'
                        log(f"  ⚠️  [{sym}] Kein Bid/Ask — modelGreeks: Short ${short_bid:.2f}  Long ${long_ask:.2f}")
                    else:
                        short_last = t_short.last if t_short.last and t_short.last > 0 else None
                        long_last  = t_long.last  if t_long.last  and t_long.last  > 0 else None
                        if short_last and long_last:
                            short_bid = short_last
                            long_ask  = long_last
                            price_src = 'LAST_PRICE'
                            log(f"  ⚠️  [{sym}] Kein Bid/Ask, kein Greek — Last-Preis: Short ${short_last:.2f}  Long ${long_last:.2f}")
                        else:
                            log(f"  ✗ [{sym}] Keine IB-Marktdaten verfügbar — Trade abgebrochen")
                            _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                            return

            has_real_bid = bool(t_short.bid and t_short.bid > 0)
            has_real_ask = bool(t_long.ask  and t_long.ask  > 0)

            ibkr_net = round(short_bid - long_ask, 2) if (short_bid and long_ask) else 0.0
            has_model = not has_real_bid and bool(
                t_short.modelGreeks and t_short.modelGreeks.optPrice
                and t_short.modelGreeks.optPrice > 0)
            discount    = 0.75 if (has_real_bid or has_model) else 0.65
            limit_price = round(max(ibkr_net * discount, 0.01), 2)
            quelle      = "IBKR-Bid" if has_real_bid else ("modelGreeks" if has_model else "Last-Preis-Fallback")
            if has_real_bid:
                price_src = 'REAL_BID_ASK'
            elif price_src == 'BS_ESTIMATE':
                price_src = 'LAST_PRICE'

            # ── Confidence-Gate ─────────────────────────────────────────────
            confidence = PRICE_CONFIDENCE[price_src]
            min_conf   = MIN_CONFIDENCE_LIVE
            if confidence < min_conf:
                log(f"  ✗ [{sym}] Confidence {confidence:.2f} [{price_src}] < {min_conf:.2f} min — Trade abgebrochen")
                _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                return

            has_model  = bool(t_short.modelGreeks and t_short.modelGreeks.optPrice
                              and t_short.modelGreeks.optPrice > 0)
            rr_minimum = MIN_RISK_REWARD if has_real_bid else MIN_RISK_REWARD * 1.5

            short_delta = None
            if t_short.modelGreeks and t_short.modelGreeks.delta is not None:
                short_delta = abs(t_short.modelGreeks.delta)
            delta_str = f"Δ={short_delta:.3f}" if short_delta is not None else "Δ=n/a"
            log(f"  📡 [{sym}] {quelle} [Conf={confidence:.2f}/{price_src}]: "
                f"Short ${short_bid:.2f}  Long ${long_ask:.2f}  "
                f"Netto: ${ibkr_net:.2f} → Limit: ${limit_price:.2f}  {delta_str}")

            if short_delta is not None and short_delta > MAX_DELTA:
                log(f"  ✗ [{sym}] Delta {short_delta:.3f} > {MAX_DELTA} — Short-Put zu nah am Kurs, Trade abgebrochen")
                _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                return

            market_rr     = ibkr_net / (sig['breite'] - ibkr_net) if sig['breite'] > ibkr_net else 0.0
            market_credit = ibkr_net * 100
            _is_paper_rr  = ACCOUNT_ID.upper().startswith('DU')

            if not _is_paper_rr and market_rr < rr_minimum:
                log(f"  ✗ [{sym}] R/R {market_rr:.2f}x < {rr_minimum:.2f}x ({quelle}) — Trade abgebrochen")
                _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                return
            sig_prob = sig.get('prob_otm', 0)
            # Paper: Credit-Recheck überspringen — Scan-Net ≠ IBKR-Net (Scan-Bug: nur Short-Bid)
            if not _is_paper_rr:
                credit_ok, req_credit, req_pwin = _check_credit(market_credit, sig['breite'], sig_prob)
                if not credit_ok:
                    spread_risk = sig['breite'] * 100
                    if market_credit >= req_credit:
                        log(f"  ✗ [{sym}] Credit ${market_credit:.0f} OK aber P(Win) {sig_prob:.1%} < {req_pwin:.0%} — Trade abgebrochen")
                    else:
                        log(f"  ✗ [{sym}] Credit ${market_credit:.0f} < erforderlich ${req_credit:.0f} ({MIN_CREDIT_PERCENT:.0%} von ${spread_risk:.0f} Risiko) — Trade abgebrochen")
                    _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                    return

            expiry_yf = sig['expiry_ib'][:4] + '-' + sig['expiry_ib'][4:6] + '-' + sig['expiry_ib'][6:]

            # ── Account-Risk-Check + Position Sizing ──────────────────────────
            spread_risk_usd = sig['breite'] * 100   # max. Verlust pro Kontrakt
            net_liq = 0.0
            try:
                _av = {v.tag: v.value for v in ib.accountValues() if v.currency == 'USD'}
                raw_nl = (_av.get('NetLiquidation') or _av.get('NetLiquidation-S') or '0')
                net_liq = float(raw_nl) if raw_nl else 0.0
            except Exception:
                pass

            if net_liq > 0:
                per_trade_pct = spread_risk_usd / net_liq
                if per_trade_pct > MAX_RISK_PER_TRADE_PCT:
                    log(f"  ✗ [{sym}] Risiko {per_trade_pct:.1%} > {MAX_RISK_PER_TRADE_PCT:.1%} "
                        f"(${spread_risk_usd:.0f} / ${net_liq:,.0f} NetLiq) — Trade abgebrochen")
                    _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                    return
                open_risk = sum(
                    (info.get('short_strike', 0) - info.get('long_strike', 0)) * 100
                    for s, info in _bot_trades.items()
                    if s != sym and info.get('status') in ('open', 'closing', 'exit_retry')
                    and info.get('short_conid')
                )
                total_pct = (open_risk + spread_risk_usd) / net_liq
                if total_pct > MAX_TOTAL_RISK_PCT:
                    log(f"  ✗ [{sym}] Gesamt-Risiko {total_pct:.1%} > {MAX_TOTAL_RISK_PCT:.1%} "
                        f"(offen ${open_risk:.0f} + neu ${spread_risk_usd:.0f}) — Trade abgebrochen")
                    _bot_trades[sym] = {'status': 'failed', 'entry_per_share': 0, 'at_breakeven': False}
                    return

            # Position Sizing: Confidence × VIX-Regime, gedeckelt durch Risk-Limit
            n_contracts_conf = CONTRACTS_BY_CONFIDENCE.get(price_src, 1)
            _, vix_factor    = vix_regime(_vix_level)
            n_contracts_vix  = max(1, int(n_contracts_conf * vix_factor))
            if net_liq > 0 and MAX_RISK_PER_TRADE_PCT > 0 and spread_risk_usd > 0:
                max_by_risk = max(1, int(net_liq * MAX_RISK_PER_TRADE_PCT / spread_risk_usd))
                n_contracts = min(n_contracts_vix, max_by_risk)
            else:
                n_contracts = 1
            log(f"  📏 [{sym}] Position Sizing: {n_contracts} Kontrakt(e)"
                f" [Conf:{n_contracts_conf} × VIX:{vix_factor:.1f} → {n_contracts_vix},"
                f" RiskCap:{max_by_risk if net_liq > 0 else '?'}]")

            _fill_deadline = (datetime.now() + timedelta(seconds=FILL_TIMEOUT_SECONDS)).isoformat()
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
                'n_contracts':     n_contracts,
                'opened_at':       datetime.now().strftime('%Y-%m-%d %H:%M'),
                'fill_confirmed':  False,          # wird True wenn Entry-Fill-Event feuert
                'fill_deadline':   _fill_deadline, # Timeout für Entry-Fill
                'entry_order_id':  0,              # wird nach placeOrder gesetzt
            }

            tp_close = max(round(limit_price * (1 - TAKE_PROFIT_PCT), 2), 0.01)
            sl_close = round(limit_price * STOP_LOSS_MULT, 2)

            _is_paper = ACCOUNT_ID.upper().startswith('DU')

            # SELL-Order: IBKR führt ComboLeg-Aktionen exakt aus (SELL short put, BUY long put = Bull Put Spread)
            # BUY-Order würde Legs umkehren → Bear Put Spread (falsches Ergebnis)
            entry_order = LimitOrder('SELL', n_contracts, limit_price, tif='GTC')
            # Paper: transmit=True (kein Bracket) — IBKR lehnt Combo-Child-Orders ab (Error 201)
            entry_order.transmit = _is_paper
            entry_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
            entry_order.account = _cfg.get('ib_account', '')
            if _ibq is not None:
                entry_trade = await _ibq.place(ib, bag, entry_order)
            else:
                entry_trade = ib.placeOrder(bag, entry_order)
            parent_id = entry_trade.order.orderId

            _bot_trades[sym]['entry_order_id'] = parent_id

            if _is_paper:
                # Paper-Konto: OCA-Gruppe als Bracket-Ersatz (Error 201 verhindert parentId)
                # Beide Orders stehen in IBKR auch wenn der Bot abstürzt
                import random as _rnd
                _oca = f"BPS_{sym}_{int(time.time())}_{_rnd.randint(100,999)}"
                tp_trade = sl_trade = None
                try:
                    tp_order = LimitOrder('BUY', n_contracts, tp_close, tif='GTC')
                    tp_order.ocaGroup = _oca
                    tp_order.ocaType  = 1  # Cancel remaining with block
                    tp_order.transmit = False
                    tp_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
                    tp_order.account = _cfg.get('ib_account', '')
                    if _ibq is not None:
                        tp_trade = await _ibq.place(ib, bag, tp_order)
                    else:
                        tp_trade = ib.placeOrder(bag, tp_order)

                    sl_order = LimitOrder('BUY', n_contracts, sl_close, tif='GTC')
                    sl_order.ocaGroup = _oca
                    sl_order.ocaType  = 1
                    sl_order.transmit = True
                    sl_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
                    sl_order.account = _cfg.get('ib_account', '')
                    if _ibq is not None:
                        sl_trade = await _ibq.place(ib, bag, sl_order)
                    else:
                        sl_trade = ib.placeOrder(bag, sl_order)

                    _bot_trades[sym]['tp_order_id'] = tp_trade.order.orderId
                    _bot_trades[sym]['sl_order_id'] = sl_trade.order.orderId
                    log(f"  ✅ [{sym}] OCA-BRACKET (Paper) platziert — TP #{tp_trade.order.orderId} / SL #{sl_trade.order.orderId}")
                except Exception as _oca_err:
                    log(f"  ⚠️  [{sym}] OCA-Bracket fehlgeschlagen ({_oca_err}) — nur Software-Monitor aktiv")
            else:
                # Live-Konto: klassisches Bracket mit TP + SL
                tp_order = LimitOrder('BUY', n_contracts, tp_close, tif='GTC')
                tp_order.parentId = parent_id
                tp_order.transmit = False
                tp_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
                tp_order.account = _cfg.get('ib_account', '')
                if _ibq is not None:
                    tp_trade = await _ibq.place(ib, bag, tp_order)
                else:
                    tp_trade = ib.placeOrder(bag, tp_order)

                sl_order = LimitOrder('BUY', n_contracts, sl_close, tif='GTC')
                sl_order.parentId = parent_id
                sl_order.transmit = True
                sl_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
                sl_order.account = _cfg.get('ib_account', '')
                if _ibq is not None:
                    sl_trade = await _ibq.place(ib, bag, sl_order)
                else:
                    sl_trade = ib.placeOrder(bag, sl_order)

                _bot_trades[sym]['tp_order_id'] = tp_trade.order.orderId
                _bot_trades[sym]['sl_order_id'] = sl_trade.order.orderId

            _save_state()

            log(f"  🟡 [{sym}] ORDER GESENDET — warte auf Broker-Bestätigung ...")
            if _is_paper:
                log(f"  ✅ [{sym}] ENTRY-ORDER PLATZIERT (Paper — OCA-Bracket) × {n_contracts} Kontrakt(e)")
                log(f"     Entry  #{parent_id}:  +${limit_price:.2f}  (Credit ${market_credit*n_contracts:.0f})  R/R: {market_rr:.2f}x")
                if tp_trade and sl_trade:
                    log(f"     TP     #{tp_trade.order.orderId}:  +${tp_close:.2f}  (+{TAKE_PROFIT_PCT:.0%} = +${tp_close*100*n_contracts:.0f})")
                    log(f"     SL     #{sl_trade.order.orderId}:  +${sl_close:.2f}  (-{STOP_LOSS_MULT:.0%} = -{sl_close*100*n_contracts:.0f})")
            else:
                log(f"  ✅ [{sym}] BRACKET-ORDER PLATZIERT (alle GTC) × {n_contracts} Kontrakt(e)")
                log(f"     Entry  #{parent_id}:  +${limit_price:.2f}  (Credit ${market_credit*n_contracts:.0f})  R/R: {market_rr:.2f}x")
                log(f"     TP     #{tp_trade.order.orderId}:  +${tp_close:.2f}  (+{TAKE_PROFIT_PCT:.0%} = +${tp_close*100*n_contracts:.0f})")
                log(f"     SL     #{sl_trade.order.orderId}:  +${sl_close:.2f}  (-{STOP_LOSS_MULT:.0%} = -{sl_close*100*n_contracts:.0f})")
            return True
    except Exception as e:
        import traceback
        log(f"  ❌ [{sym}] Order-Fehler: {e}\n{traceback.format_exc()}")

def print_ranking(signals, selected):
    """Zeigt eine Ranking-Tabelle aller Signale dieses Zyklus."""
    selected_symbols = {s['symbol'] for s in selected}
    log(f"\n{'─'*100}")
    log(f"  {'#':<3} {'Symbol':<6} {'IV':>6} {'Kurs':>8} {'Strike':>12} "
        f"{'Credit':>8} {'R/R':>6} {'P(Win)':>7} {'EV':>7} {'Score':>7}  Status")
    log(f"{'─'*100}")
    for i, s in enumerate(signals, 1):
        status   = "→ TRADE" if s['symbol'] in selected_symbols else "  skip"
        triggers = ', '.join(s.get('triggers', []))
        log(f"  {i:<3} {s['symbol']:<6} {s['iv']:>6.1%} {s['preis']:>8.2f} "
            f"  {s['short_strike']:>5.0f}P/{s['long_strike']:>4.0f}P "
            f"  ${s['credit']:>6.2f}"
            f"  {s['risk_reward']:>5.2f}x  {s.get('prob_otm', 0):>6.1%}"
            f"  {s.get('ev', 0):>+6.2f}$  {s['score']:>6.3f}  {status}")
        if triggers:
            log(f"       ↳ {triggers} | edge={s.get('edge',0):.3f} risk={s.get('risk',0):.3f}"
                f" liq={s.get('liquidity_score',0):.3f} earn_pen={s.get('earnings_penalty',0):.3f}")
    log(f"{'─'*100}")

async def configure_environment(ib) -> None:
    """Verbindet mit IB-Konto, setzt Marktdaten-Typ und loggt Modus."""
    global ACCOUNT_ID, AUTO_TRADE
    accounts = ib.managedAccounts()
    ACCOUNT_ID = accounts[0] if accounts else _cfg.get('ib_account', '')
    is_paper = ACCOUNT_ID.upper().startswith('DU')
    # Paper → Auto-Trade aktiv; Live → nur Empfehlungen (Sicherheitsnetz)
    AUTO_TRADE = is_paper
    ib.reqMarketDataType(1)  # Typ 1 = Live-Echtzeit (OPRA + US Real-Time Abo aktiv)
    log("=" * 60)
    if is_paper:
        log("  MODUS: PAPER  (Konto: " + ACCOUNT_ID + ")")
        log("  Simuliertes Konto — Auto-Trade AKTIV")
    else:
        log("  MODUS: LIVE  (Konto: " + ACCOUNT_ID + ")")
        log("  Echtzeit-Marktdaten aktiv (OPRA + US Real-Time)")
        log("  Empfehlungs-Modus — kein Auto-Trade (Sicherheitsnetz)")
    log("=" * 60)


def _print_shadow_summary(days: int = 30) -> None:
    """Gibt eine kurze Auswertung der Shadow-Trades der letzten `days` Tage aus."""
    if not os.path.exists(_SHADOW_FILE):
        return
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows: list[dict] = []
        with open(_SHADOW_FILE, encoding='utf-8') as sf:
            for line in sf:
                try:
                    r = _json.loads(line)
                    if r.get('ts', '') >= cutoff:
                        rows.append(r)
                except Exception:
                    continue
        if not rows:
            return

        taken    = [r for r in rows if r.get('type') == 'taken']
        rejected = [r for r in rows if r.get('type') == 'rejected']
        blocked  = [r for r in rows if r.get('type') == 'blocked']

        log(f"\n{'─'*60}")
        log(f"  📊 SHADOW ANALYTICS — letzte {days} Tage ({len(rows)} Einträge)")
        log(f"  Taken: {len(taken)}  |  Rejected: {len(rejected)}  |  Blocked: {len(blocked)}")

        # Rejection-Gründe zusammenfassen
        from collections import Counter
        stages = Counter(r.get('stage') for r in rejected + blocked)
        for stage, cnt in stages.most_common():
            log(f"     {stage:<20} {cnt:>4}×")

        # Häufigste blockierte Symbole
        sym_blocked = Counter(r.get('symbol') for r in rejected + blocked)
        top5 = sym_blocked.most_common(5)
        if top5:
            log(f"  Top-5 geblockte Symbole: {', '.join(f'{s}({n})' for s, n in top5)}")

        # Historische Signale im Score-Bereich 0.50–ENTRY_THRESHOLD (damals zu schwach, heute evtl. anders)
        watch = [r for r in rejected if r.get('decision') == 'WATCH']
        if watch:
            avg_score = sum(r.get('score', 0) for r in watch) / len(watch)
            avg_ev    = sum(r.get('ev', 0) for r in watch) / len(watch)
            log(f"  Hist. Grenzfälle (Score <{ENTRY_THRESHOLD:.2f}): {len(watch)} | ⌀Score {avg_score:.3f} | ⌀EV ${avg_ev:+.0f}")
        log(f"{'─'*60}\n")
    except Exception as e:
        log(f"  ⚠️  Shadow-Analytics fehlgeschlagen: {e}")


async def _reconciliation_loop(ib, stop_event=None) -> None:
    """Background-Reconciliation: prüft alle 60s auf Orphan-BAG-Orders und Ghost-Positionen.

    Läuft als Hintergrund-Task. Ergänzt den Startup-Sweep um kontinuierliche Bereinigung:
    - Orphan BAG Orders: offen ohne 'closing'-Position → canceln
    - Ghost Positionen: bot-State sagt 'open' aber IB hat keine OPT-Position → entfernen
    """
    await asyncio.sleep(45)  # Startup-Phase abwarten
    while not (stop_event and stop_event.is_set()):
        try:
            await asyncio.sleep(60)
            if not ib or not ib.isConnected():
                continue

            open_orders = await ib.reqAllOpenOrdersAsync()

            # Orphan BAG Orders: BAG offen aber kein bekannter State und keine TP/SL-ID → stornieren
            _recon_protected_syms = {s for s, v in _bot_trades.items()
                                     if v.get('status') in ('closing', 'open', 'exit_retry')}
            _recon_protected_oids = {v.get('tp_order_id', 0) for v in _bot_trades.values()} \
                                  | {v.get('sl_order_id', 0) for v in _bot_trades.values()}
            _recon_protected_oids.discard(0)
            orphan_bags   = [
                t for t in open_orders
                if t.contract.secType == 'BAG'
                and t.contract.symbol not in _recon_protected_syms
                and (t.order.orderId or 0) not in _recon_protected_oids
            ]
            if orphan_bags:
                log(f"  🔄 [RECON] {len(orphan_bags)} Orphan-BAG(s) entdeckt — stornieren ...")
                for _ot in orphan_bags:
                    _oid = _ot.order.orderId or 0
                    if _oid > 0:
                        _expected_cancels.add(_oid)
                        try:
                            await _ib_cancel_paced(ib, _oid)
                            log(f"     → #{_oid} ({_ot.contract.symbol} {_ot.orderStatus.status}) storniert")
                        except Exception as _ce:
                            log(f"     ⚠️  #{_oid}: {_ce}")

            # Ghost Positionen: bot denkt 'open'/'closing'/'exit_retry' aber IB hat keine OPT-Pos
            _ib_opt_syms   = {p.contract.symbol for p in ib.positions()
                              if p.contract.secType == 'OPT' and p.position != 0}
            _ib_order_syms = {t.contract.symbol for t in open_orders
                              if t.contract.secType in ('OPT', 'BAG')}
            _ghost = [
                s for s, v in list(_bot_trades.items())
                if v.get('status') in ('open', 'closing', 'exit_retry', 'error')
                and s not in _ib_opt_syms
                and s not in _ib_order_syms
            ]
            for _gs in _ghost:
                log(f"  🧹 [RECON] [{_gs}] Ghost-Position — kein IB-Pendant → entfernt")
                del _bot_trades[_gs]
            if _ghost:
                _save_state()

        except asyncio.CancelledError:
            break
        except Exception as _re:
            log(f"  ⚠️  [RECON] Fehler: {_re}")


async def _reconnect_ib(ib: 'IB', host: str, port: int,
                         stop_event: 'threading.Event | None' = None) -> bool:
    """Versucht die IB-Verbindung nach Trennung wiederherzustellen (exp. Backoff)."""
    for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
        if stop_event and stop_event.is_set():
            return False
        wait_sec = min(RECONNECT_BASE_WAIT * attempt, 300)
        log(f"  🔄 IB-Reconnect Versuch {attempt}/{RECONNECT_MAX_ATTEMPTS} in {wait_sec}s ...")
        await asyncio.sleep(wait_sec)
        try:
            if ib.isConnected():
                return True
            client_id = random.randint(10, 999)
            await asyncio.wait_for(ib.connectAsync(host, port, clientId=client_id), timeout=30)
            if ib.isConnected():
                log(f"  ✅ IB-Reconnect erfolgreich (Versuch {attempt})")
                return True
        except Exception as e:
            log(f"  ⚠️  Reconnect-Versuch {attempt} fehlgeschlagen: {e}")
    log(f"  ❌ IB-Reconnect nach {RECONNECT_MAX_ATTEMPTS} Versuchen nicht möglich")
    return False


async def run_bot(stop_event: threading.Event = None):
    global _ibq
    ib = IB()
    log(f"🤖 Master-Bot startet... Verbinde zur IB (Port {_cfg.get('ib_port', 7496)})")
    _print_shadow_summary(days=30)

    # Global IB Order Queue initialisieren — serialisiert alle cancel/place Calls
    _ibq = _IBOrderQueue()
    _ibq.start()
    log("  ✅ IBOrderQueue gestartet (alle Order-Mutations laufen durch serielle Pipeline)")

    try:
        client_id = random.randint(10, 999)
        await ib.connectAsync(
            _cfg.get('ib_host', '127.0.0.1'),
            int(_cfg.get('ib_port', 7496)),
            clientId=client_id,
        )
        log("✅ Verbunden mit IB (nur für Order-Placement)")

        await configure_environment(ib)

        # ib_insync-Logger filtern: informative Codes und bekannte Nicht-Fehler unterdrücken
        import logging as _logging

        _IB_SUPPRESS_CODES = {
            10089, 10090, 10091,    # Kein Abo / Subscription nötig — yfinance-Fallback greift
            10197,                  # Keine Combo-Daten bei konkurrierender Live-Sitzung — Fallback auf Einzel-Bid
            2104, 2106, 2107,       # Market-Data-Farm OK
            2108, 2158, 2157,       # Hist./SecDef-Farm OK
            504,                    # Not connected (transient)
            101,                    # Max Tickers — Demo-typisch, wird via Fallback behandelt
            200,                    # Kein Contract gefunden — wird im Code abgefangen (conId=0)
            10147,                  # Cancel für orderId=0 — wird im Code übersprungen
            321,                    # Invalid genTickList — Sicherheitsnetz
            10213,                  # Regulatory Snapshot nachts nicht erlaubt — Streaming-Fallback greift
            399,                    # Verzögerte Marktdaten verfügbar — kein Handlungsbedarf
        }
        _IB_SUPPRESS_PHRASES = (
            'cancelMktData: No reqId found',   # Cancel auf bereits bereinigter Subscription
            'Es sind verzögerte Marktdaten',   # Duplicate des 10091-Textes
            'Maximale Anzahl an Tickern',       # Error 101 Langtext
        )

        class _IBNoiseFilter(_logging.Filter):
            def filter(self, record):
                msg = record.getMessage()
                for code in _IB_SUPPRESS_CODES:
                    if f'Error {code},' in msg or f'error {code},' in msg.lower():
                        return False
                return not any(p in msg for p in _IB_SUPPRESS_PHRASES)

        _ib_filter = _IBNoiseFilter()
        # Filter auf alle ib_insync-Logger UND deren Handler anwenden
        for _logger_name in ('ib_insync', 'ib_insync.ib', 'ib_insync.wrapper',
                             'ib_insync.client', 'ib_insync.util'):
            _lg = _logging.getLogger(_logger_name)
            _lg.addFilter(_ib_filter)
            for _h in _lg.handlers:
                _h.addFilter(_ib_filter)
        # Fallback: Root-Handler abdecken (falls ib_insync dorthin propagiert)
        for _h in _logging.root.handlers:
            _h.addFilter(_ib_filter)

        # Event-Handler: gecancelte Orders in Echtzeit tracken
        ib.orderStatusEvent += _on_order_status

        # Event-Handler: Disconnect protokollieren
        def _on_ib_disconnected():
            log("  ⚠️  IB-Verbindung getrennt — nächster Zyklus: Reconnect-Versuch")
        ib.disconnectedEvent += _on_ib_disconnected

        # Event-Handler: IBKR-Fehler loggen
        # 200 = "No security definition" — normal beim Optionsscan, unterdrücken
        # >=2000 = reine Info/System-Meldungen, nicht relevant
        _SUPPRESS_CODES = {200, 354, 10167}
        def _on_ib_error(reqId, errorCode, errorString, _contract):
            if errorCode < 2000 and errorCode not in _SUPPRESS_CODES:
                log(f"  ⚠️  IBKR Error {errorCode} (reqId={reqId}): {errorString}")
        ib.errorEvent += _on_ib_error

        # IB Strike-Map einmalig laden — valide Strikes/Expiries für alle Watchlist-Symbole
        await build_strike_map(ib)

        # Hintergrund-Streams aufbauen: VIX + alle Watchlist-Aktien dauerhaft registrieren
        await start_background_streaming(WATCHLIST, ib)

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
            existing = _bot_trades.get(sym, {})
            # Überspringen nur wenn bereits ein valider Einstiegspreis bekannt ist
            if existing.get('entry_per_share', 0) > 0:
                continue
            short_legs = [p for p in legs if p.position < 0]
            long_legs  = [p for p in legs if p.position > 0]
            # Vorhandene State-Daten (strikes, conids, tp/sl-IDs) erhalten, nur Preis ergänzen
            entry: dict = {**existing, 'status': existing.get('status', 'open'),
                           'at_breakeven': existing.get('at_breakeven', False),
                           'entry_per_share': 0}

            if short_legs:
                sl = max(short_legs, key=lambda x: x.contract.strike)
                entry['short_strike'] = sl.contract.strike
                entry['short_conid']  = sl.contract.conId
                raw = abs(sl.avgCost)
                # IB gibt avgCost per-Kontrakt (×100) zurück → pro Share umrechnen
                recovered = raw / 100 if raw > 10 else raw
                if recovered > 0:
                    entry['entry_per_share'] = recovered
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
                if entry['entry_per_share'] > 0:
                    entry['entry_per_share'] = max(0, entry['entry_per_share'] - paid)

            # avgCost=0 im Demo-Konto: Fallback auf Limit-Preis der offenen Entry-Order
            if entry['entry_per_share'] <= 0:
                for ot in ib.openTrades():
                    if ot.contract.symbol == sym and abs(ot.order.lmtPrice or 0) > 0:
                        fallback = abs(ot.order.lmtPrice)
                        entry['entry_per_share'] = fallback
                        log(f"  ⚠️  [{sym}] avgCost=0 (Demo) — Einstiegspreis von Limit-Order: ${fallback:.2f}")
                        break

            if entry['entry_per_share'] <= 0:
                log(f"  ⚠️  [{sym}] Einstiegspreis konnte nicht rekonstruiert werden — "
                    f"P&L-Anzeige deaktiviert bis zur nächsten Füllung")

            was_known = sym in _bot_trades
            _bot_trades[sym] = entry
            if not was_known:
                pre_loaded += 1

        if pre_loaded:
            log(f"   {pre_loaded} bestehende Order(s)/Position(en) aus IB geladen — werden nicht dupliziert")

        # State-Abgleich: Einträge aus State-File entfernen die kein echtes IB-Pendant haben.
        # Verhindert Ghost-Positionen nach Account-Wechsel oder manuellem Schließen in TWS.
        ib_position_syms  = set(put_by_sym.keys())
        ib_order_syms     = {o.contract.symbol for o in open_orders if o.contract.secType == 'OPT'}
        ghost_syms = [
            sym for sym, info in list(_bot_trades.items())
            if info.get('status') in ('open', 'closing', 'exit_retry', 'error')
            and sym not in ib_position_syms
            and sym not in ib_order_syms
        ]
        for sym in ghost_syms:
            del _bot_trades[sym]
            log(f"  🧹 [{sym}] Ghost-Position aus State entfernt — kein echtes IB-Pendant gefunden")
        if ghost_syms:
            _save_state()

        # Startup-BAG-Sweep: zombie BAG-Orders canceln (gecrashe Exits).
        # Schützt: (a) Symbole mit status='closing', (b) bekannte TP/SL-Bracket-Order-IDs
        # für 'open'-Positionen — diese sollen auf IB aktiv bleiben.
        _protected_syms = {s for s, v in _bot_trades.items()
                           if v.get('status') in ('closing', 'open', 'exit_retry')}
        _protected_oids = {v.get('tp_order_id', 0) for v in _bot_trades.values()} \
                        | {v.get('sl_order_id', 0) for v in _bot_trades.values()}
        _protected_oids.discard(0)
        _zombie_bags  = [
            o for o in open_orders
            if o.contract.secType == 'BAG'
            and o.contract.symbol not in _protected_syms
            and (o.order.orderId or 0) not in _protected_oids
        ]
        if _zombie_bags:
            log(f"  🧹 Startup-Sweep: {len(_zombie_bags)} zombie BAG-Order(s) canceln ...")
            for _zo in _zombie_bags:
                _zoid = _zo.order.orderId or 0
                if _zoid > 0:
                    try:
                        _expected_cancels.add(_zoid)
                        await _ib_cancel_paced(ib, _zoid)  # über _ibq mit Pacing
                        log(f"     → BAG #{_zoid} ({_zo.contract.symbol}) storniert")
                    except Exception as _ze:
                        log(f"     ⚠️  BAG #{_zoid} Cancel-Fehler: {_ze}")
            await asyncio.sleep(2.0)

        # Split-Leg-Check: Symbol mit nur einem OPT-Leg → Spread teilweise geschlossen
        for sym, legs in put_by_sym.items():
            short_c = [p for p in legs if p.position < 0]
            long_c  = [p for p in legs if p.position > 0]
            if bool(short_c) != bool(long_c):
                log(f"  ⚠️  [{sym}] Split-Leg erkannt — nur {'Short' if short_c else 'Long'}-Leg offen! "
                    f"Bitte in CapTrader manuell prüfen und ggf. schließen.")

        # Background-Reconciliation starten
        asyncio.ensure_future(_reconciliation_loop(ib, stop_event))
        log("  ✅ Reconciliation-Loop gestartet (alle 60s: Orphan-BAGs + Ghost-Positionen)")
        log("")
    except TimeoutError:
        port = _cfg.get('ib_port', 7496)
        log(f"❌ Verbindung fehlgeschlagen (Timeout auf Port {port}).")
        log("   → TWS/IB Gateway läuft?")
        log("   → API aktiviert? (Edit → Global Configuration → API → Enable Socket Clients)")
        log("   → Port korrekt? TWS Live=7496, Gateway Live=4001")
        ib.disconnect()
        return

    try:
        while not (stop_event and stop_event.is_set()):
            _reload_cfg()   # Einstellungen aus config.json aktualisieren (Hot-Reload)
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

            # ── Verbindungscheck / Auto-Reconnect ────────────────────────────
            if ib and not ib.isConnected():
                log("  ⚠️  IB nicht verbunden — Auto-Reconnect ...")
                _host = _cfg.get('ib_host', '127.0.0.1')
                _port = int(_cfg.get('ib_port', 7496))
                reconnected = await _reconnect_ib(ib, _host, _port, stop_event)
                if reconnected:
                    ib.orderStatusEvent += _on_order_status
                    await ib.reqAllOpenOrdersAsync()
                    await asyncio.sleep(1.0)
                    log("  ✅ IB-State nach Reconnect synchronisiert")
                else:
                    log("  ❌ Reconnect fehlgeschlagen — nur Exit-Monitoring (ohne IB-Daten)")

            # ── VIX-Regime + Event-Lock ──────────────────────────────────────
            global _vix_level, _vix_regime
            _vix_level = await get_vix(ib)
            _regime_str, _size_factor = vix_regime(_vix_level)
            _vix_regime = _regime_str
            vix_icon = {'calm': '😴', 'normal': '✅', 'elevated': '⚡', 'crisis': '🚨'}.get(_regime_str, '❓')
            log(f"  {vix_icon} VIX {_vix_level:.1f} [{_regime_str.upper()}]"
                + (f" — Size-Faktor {_size_factor:.1f}x" if _size_factor != 1.0 else ""))

            _ev_locked, _ev_reason = check_event_lock()
            if _ev_locked:
                log(f"  🔒 EVENT-LOCK: {_ev_reason} — kein neuer Trade")

            # ── Kill-Switch-Check ─────────────────────────────────────────────
            if await check_kill_switch(ib):
                log(f"  🛑 KILL-SWITCH aktiv ({_kill_switch_reason}) — Scan übersprungen, nur Exit-Monitoring läuft")
                for _cd in range(SCAN_INTERVALL, 0, -1):
                    if stop_event and stop_event.is_set():
                        break
                    if _cd == SCAN_INTERVALL or _cd % 10 == 0:
                        log(f"  ⏳ Nächster Zyklus in {_cd}s ...")
                    await asyncio.sleep(1)
                continue

            # ── Phase 1a: Stock-Scan (yfinance primär, IB-Snapshot Fallback) ──
            t0 = datetime.now()
            import time as _time
            log(f"   Scanne {len(WATCHLIST)} Symbole ...")
            ib_price_data: dict = await _yf_stock_scan(WATCHLIST, ib)
            elapsed = (datetime.now() - t0).total_seconds()
            log(f"   ✅ {len(ib_price_data)}/{len(WATCHLIST)} Preise erhalten ({elapsed:.1f}s)")

            # ── Phase 1c: IV via Cache + yfinance-Fallback (TTL 5min) ──────────
            # IV ändert sich langsam → Cache verhindert yfinance-Spam jeden Scan-Zyklus
            import time as _time
            now_ts = _time.time()
            no_iv = [s for s, (_, v) in ib_price_data.items() if v is None]
            # Cache-Treffer sofort eintragen
            for sym in list(no_iv):
                cached = _iv_cache.get(sym)
                if cached and now_ts - cached[1] < _IV_CACHE_TTL:
                    p, _ = ib_price_data[sym]
                    ib_price_data[sym] = (p, cached[0])
                    no_iv.remove(sym)
            # Nur abgelaufene / unbekannte IV via OPRA holen
            if no_iv:
                log(f"   IV für {len(no_iv)} Symbole (OPRA ATM-Put, Type 1) ...")
                _sem_iv = asyncio.Semaphore(5)
                async def _iv_fill(sym):
                    async with _sem_iv:
                        _, yf_iv = await _get_market_data_yf(sym, ib)
                    if yf_iv is not None:
                        p, _ = ib_price_data[sym]
                        ib_price_data[sym] = (p, yf_iv)
                        _iv_cache[sym] = (yf_iv, _time.time())
                await asyncio.gather(*[_iv_fill(s) for s in no_iv],
                                     return_exceptions=True)

            # ── Phase 1d: News-Check und Signal-Berechnung für Trigger ───────
            _sem_news = asyncio.Semaphore(5)
            _sem_sig  = asyncio.Semaphore(4)

            async def scan_symbol(symbol):
                entry = ib_price_data.get(symbol)
                if entry is None:
                    log(f"   [{symbol}] ⏳ Keine Preisdaten")
                    return None
                preis, iv = entry
                if iv is None:
                    log(f"   [{symbol}] ⏳ Kein IV — überspringe")
                    return None

                prev_iv  = _iv_memory.get(symbol)
                iv_spike = prev_iv is not None and (iv - prev_iv) >= MIN_IV_SPIKE
                _iv_memory[symbol] = iv

                async with _sem_news:
                    news_hit, headline = await check_news_trigger(symbol)

                if iv <= MIN_VOLA:
                    log(f"   [{symbol}] ✗  IV={iv:.1%} (unter {MIN_VOLA:.1%})")
                    return None

                trigger_reasons = []
                if iv_spike:
                    trigger_reasons.append(f"IV-Spike +{iv - prev_iv:.1%}")
                if news_hit:
                    trigger_reasons.append(f"News: \"{headline[:60]}\"")

                async with _sem_sig:
                    sig = await build_bull_put_spread(symbol, preis, iv, ib, news_hit=news_hit, iv_spike=iv_spike)
                if sig:
                    sig['triggers'] = trigger_reasons
                    return sig
                return None

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*[scan_symbol(s) for s in WATCHLIST],
                                   return_exceptions=True),
                    timeout=300)
            except asyncio.TimeoutError:
                log("  ⏱️  Scan-Timeout nach 300s — nächster Zyklus")
                results = []
            results     = [r for r in results if not isinstance(r, BaseException)]
            all_signals = [s for s in results if s is not None]
            elapsed = (datetime.now() - t0).seconds
            log(f"\n   [LIVE] Scan abgeschlossen in {elapsed}s | {len(WATCHLIST)} Symbole gescannt | {len(all_signals)} Signale über IV-Filter")

            # ── Phase 2: Signale filtern und ranken ───────────────────────────
            qualified = [
                s for s in all_signals
                if s['praemie_quelle'] != "Black-Scholes (geschätzt)"
                and s.get('credit_ok_hard', True)
                and s.get('decision') == 'TRADE'
            ]
            qualified.sort(key=lambda s: s['score'], reverse=True)

            # Alle qualifizierten Signale sind handelbar — sortiert nach R/R,
            # Slot-Limit begrenzt natürlich auf die besten N
            tradeable = qualified
            best_rr   = qualified[0]['risk_reward'] if qualified else None

            all_signals.sort(key=lambda s: s['risk_reward'], reverse=True)

            # ── Phase 3: Entscheiden wie viele Trades möglich sind ────────────
            open_count   = count_bot_orders()
            slots        = MAX_POSITIONS - open_count
            selected     = []
            _margin_stop = False

            if AUTO_TRADE and slots > 0:
                # Sektor-Exposure nur aus echten Spread-Positionen zählen
                sector_counts: dict = {}
                for s, info in _bot_trades.items():
                    if info.get('status') in ('open', 'closing', 'exit_retry') and info.get('short_conid'):
                        sec = SECTOR_MAP.get(s, 'Unbekannt')
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1

                # Margin-Check: reqAccountSummaryAsync → Cache → Paper-Fallback
                _is_paper_acct = ACCOUNT_ID.upper().startswith('DU')
                available = 0.0
                try:
                    summary = await asyncio.wait_for(ib.reqAccountSummaryAsync(), timeout=10)
                    # Kein Währungsfilter — Paper-Konten liefern teils BASE, USD oder leere Felder
                    av = {v.tag: v.value for v in summary if v.account == ACCOUNT_ID}
                    raw = (av.get('AvailableFunds') or av.get('AvailableFunds-S')
                           or av.get('NetLiquidation') or av.get('TotalCashValue') or '0')
                    available = float(raw)

                    if available <= 0:
                        # Fallback: lokaler TWS-Cache
                        cached_vals = {v.tag: v.value for v in ib.accountValues()
                                       if v.account == ACCOUNT_ID}
                        raw2 = (cached_vals.get('AvailableFunds') or cached_vals.get('TotalCashValue')
                                or cached_vals.get('NetLiquidation') or '0')
                        available = float(raw2)
                except Exception:
                    log(f"  ⚠️  Kapital-Abfrage fehlgeschlagen — überspringe Margin-Check")

                if available <= 0 and _is_paper_acct:
                    # Paper-Konto: IB liefert oft $0 über API → virtuelles Budget als Fallback
                    available = 50_000.0
                    log(f"  ℹ️  Paper-Konto meldet $0 — virtuelles Kapital: ${available:,.0f}")
                elif available > 0:
                    log(f"  💰 Verfügbare Mittel: ${available:,.0f}")
                else:
                    log(f"  ⚠️  Kapital $0 — Margin-Check wird ausgeführt")

                if available < MIN_AVAILABLE_FUNDS:
                    log(f"  ⛔ Margin-Stop: ${available:,.0f} < ${MIN_AVAILABLE_FUNDS:,} Minimum — kein neuer Trade")
                    tradeable = []
                    _margin_stop = True

                # Daily Trade Budget: Wie viele neue Trades heute noch erlaubt?
                _today_str   = datetime.now().strftime('%Y-%m-%d')
                _day_count   = _trades_today.get(_today_str, 0)
                _day_budget  = MAX_TRADES_PER_DAY - _day_count
                _effective_slots = min(slots, _day_budget)
                if _day_budget <= 0:
                    log(f"  ⛔ Daily Budget erschöpft ({MAX_TRADES_PER_DAY}/Tag) — kein neuer Trade heute")
                    tradeable = []
                elif _day_budget < slots:
                    log(f"  📆 Daily Budget: {_day_count}/{MAX_TRADES_PER_DAY} heute — "
                        f"noch {_day_budget} Trade(s) möglich")

                for sig in tradeable:
                    if len(selected) >= _effective_slots:
                        break
                    if already_traded(sig['symbol']):
                        log(f"  ⏸️  [{sig['symbol']}] Bereits in dieser Session gehandelt — übersprungen")
                        _shadow_from_sig(sig, 'blocked', 'already_traded', 'bereits diese Session gehandelt')
                        continue
                    if await has_open_position(ib, sig['symbol']):
                        log(f"  ⏸️  [{sig['symbol']}] Position im Portfolio — übersprungen")
                        _shadow_from_sig(sig, 'blocked', 'open_position', 'Position bereits im Portfolio')
                        continue
                    sector = SECTOR_MAP.get(sig['symbol'], 'Unbekannt')
                    if sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
                        log(f"  ⏸️  [{sig['symbol']}] Sektor-Limit: {sector} bereits {sector_counts[sector]}/{MAX_PER_SECTOR} — übersprungen")
                        _shadow_from_sig(sig, 'blocked', 'sector_limit',
                                         f"Sektor {sector}: {sector_counts[sector]}/{MAX_PER_SECTOR}")
                        # IV-Memory löschen: nächsten Zyklus neu bewerten wenn Slot frei wird
                        _iv_memory.pop(sig['symbol'], None)
                        continue
                    selected.append(sig)
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

            elif not AUTO_TRADE and tradeable:
                # Empfehlungs-Modus: beste qualifizierte Signale ohne Auto-Trade auswählen
                selected = tradeable[:MAX_POSITIONS]

            # ── Ranking-Tabelle ausgeben ──────────────────────────────────────
            if all_signals:
                print_ranking(all_signals, selected)
                # Zeige warum Signale aus all_signals nicht in tradeable landeten
                blocked = [s for s in all_signals if s not in tradeable]
                for s in blocked:
                    reasons = []
                    if _margin_stop:
                        reasons.append(f"Margin-Stop: Kapital < ${MIN_AVAILABLE_FUNDS:,}")
                    if s['praemie_quelle'] == "Black-Scholes (geschätzt)":
                        reasons.append("kein echtes Bid (BS-Schätzung) — Live-Modus erfordert echtes Bid")
                    if not s.get('credit_ok_hard', True):
                        _c, _b = s['credit'], s['breite']
                        _req = max(_b * 100 * MIN_CREDIT_PERCENT, MIN_CREDIT_ABS)
                        reasons.append(f"Credit ${_c:.0f} < erforderlich ${_req:.0f} (Hard-Gate)")
                    decision = s.get('decision', 'SKIP')
                    score    = s.get('score', 0.0)
                    edge     = s.get('edge', 0.0)
                    risk     = s.get('risk', 0.0)
                    quality  = s.get('quality', 0.0)
                    if decision != 'TRADE':
                        reasons.append(
                            f"Score {score:.3f} < {ENTRY_THRESHOLD} [{decision}]"
                            f" | Edge={edge:.3f} Risk={risk:.3f} Quality={quality:.3f}"
                        )
                    log(f"  ✗ [{s['symbol']}] blockiert: {', '.join(reasons) or 'unbekannt'}")
                    _stage = 'credit' if not s.get('credit_ok_hard', True) else 'score'
                    _shadow_from_sig(s, 'rejected', _stage, ' | '.join(reasons) or 'unbekannt')
            else:
                log("\n  Keine Signale in diesem Zyklus.")

            if best_rr:
                log(f"  Bestes R/R: {best_rr:.2f}x | {len(tradeable)} Signale qualifiziert")

            if slots <= 0:
                log(f"  ⏸️  Bot-Limit erreicht ({open_count}/{MAX_POSITIONS} Orders diese Session) — kein neuer Trade")
            elif not tradeable:
                log(f"  ⏸️  Kein Signal mit Score ≥ {ENTRY_THRESHOLD} (TRADE) und erfülltem Credit-Gate")

            # ── Phase 4: Orders platzieren ────────────────────────────────────
            # VIX-Krisenmodus: keine neuen Trades
            _cur_regime, _cur_factor = vix_regime(_vix_level)
            if _cur_factor <= 0 and selected:
                log(f"  🚨 VIX {_vix_level:.1f} [CRISIS] — {len(selected)} Trade(s) blockiert")
                for _s in selected:
                    _shadow_from_sig(_s, 'blocked', 'vix_crisis', f"VIX {_vix_level:.1f} > {VIX_CRISIS_THRESHOLD}")
                selected = []
            # Event-Lock: keine neuen Trades vor Makro-Ereignis
            if _ev_locked and selected:
                log(f"  🔒 EVENT-LOCK ({_ev_reason}) — {len(selected)} Trade(s) blockiert")
                for _s in selected:
                    _shadow_from_sig(_s, 'blocked', 'event_lock', _ev_reason)
                selected = []
            # Exit-Reconciliation: keine neuen Entries solange EXIT_RETRY aktiv
            _retry_syms = [s for s, v in _bot_trades.items() if v.get('status') == 'exit_retry']
            if _retry_syms and selected:
                log(f"  ⏸️  Neue Entries pausiert — EXIT_RETRY aktiv: {_retry_syms}")
                for _s in selected:
                    _shadow_from_sig(_s, 'blocked', 'exit_retry', f"EXIT_RETRY: {_retry_syms}")
                selected = []

            # ── Phase 4b: Auto-Trade (Paper) oder Empfehlungs-Modus (Live) ─────
            if selected and AUTO_TRADE:
                # Paper-Konto: Orders direkt platzieren
                log(f"\n{'═'*54}")
                log(f"  AUTO-TRADE — {len(selected)} Order(s) werden platziert")
                log(f"{'═'*54}")
                _write_recommendations_file(selected)
                for sig in selected:
                    exp_raw = sig.get('expiry_ib', '')
                    try:
                        exp_fmt = f"{exp_raw[:4]}-{exp_raw[4:6]}-{exp_raw[6:]}"
                    except Exception:
                        exp_fmt = exp_raw
                    log(f"  📤 Platziere: {sig['symbol']} "
                        f"{sig['short_strike']:.0f}/{sig['long_strike']:.0f}P  "
                        f"{exp_fmt}  Credit ${sig['credit']:.0f}")
                    try:
                        ok = await place_order(ib, sig)
                        if ok:
                            log(f"  ✅ [{sig['symbol']}] Order übermittelt")
                            _shadow_from_sig(sig, 'taken', 'auto_trade', 'Auto-Trade platziert')
                        else:
                            log(f"  ❌ [{sig['symbol']}] Order fehlgeschlagen")
                            _shadow_from_sig(sig, 'blocked', 'order_failed', 'place_order returned False')
                    except Exception as _oe:
                        log(f"  ❌ [{sig['symbol']}] Order-Fehler: {_oe}")
                        _shadow_from_sig(sig, 'blocked', 'order_error', str(_oe))
                log(f"{'═'*54}")

            elif selected:
                # Live-Konto: nur Empfehlungen anzeigen — kein Auto-Trade
                log(f"\n{'═'*54}")
                log(f"  EMPFEHLUNGEN — BITTE MANUELL PRÜFEN UND PLATZIEREN")
                log(f"{'═'*54}")
                for i, sig in enumerate(selected, 1):
                    exp_raw = sig.get('expiry_ib', '')
                    try:
                        exp_fmt = f"{exp_raw[:4]}-{exp_raw[4:6]}-{exp_raw[6:]}"
                    except Exception:
                        exp_fmt = exp_raw
                    log(f"  {i}. {sig['symbol']:6s}  "
                        f"{sig['short_strike']:.0f}/{sig['long_strike']:.0f}P  "
                        f"{exp_fmt}  ({sig['dte']}DTE)")
                    log(f"     Prämie ${sig['praemie']:.2f}  |  "
                        f"Credit ${sig['credit']:.0f}  |  "
                        f"Max-Risiko ${sig['max_risk']:.0f}")
                    log(f"     RR {sig['risk_reward']:.2f}x  |  "
                        f"P(OTM) {sig['prob_otm']:.1%}  |  "
                        f"Score {sig['score']:.3f}  |  "
                        f"EV ${sig['ev']:+.0f}")
                    log(f"     Quelle: {sig.get('praemie_quelle', '—')}")
                log(f"{'═'*54}")
                _write_recommendations_file(selected)
                log(f"  Gespeichert: {_RECOMMENDATIONS_FILE}")
                for sig in selected:
                    _shadow_from_sig(sig, 'watch', 'recommendation', 'Empfehlung — manueller Trade erforderlich')

            else:
                log("  Keine Empfehlungen in diesem Zyklus.")
                _write_recommendations_file([])

            # Positionen für Launcher-Anzeige schreiben
            _write_positions_file()

            for _cd in range(SCAN_INTERVALL, 0, -1):
                if stop_event and stop_event.is_set():
                    break
                if _cd == SCAN_INTERVALL or _cd % 10 == 0:
                    log(f"\n  ⏳ Nächster Zyklus in {_cd}s ...")
                await asyncio.sleep(1)

    except Exception as e:
        import traceback
        log(f"KRITISCHER FEHLER: {e}\n{traceback.format_exc()}")
    finally:
        ib.disconnect()
        log("🔌 IB-Verbindung getrennt.")

if __name__ == "__main__":
    asyncio.run(run_bot())
