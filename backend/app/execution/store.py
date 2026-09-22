"""Persistence for the execution engine: one SQLite file (WAL) plus a JSON config file people can also edit by hand."""
import json, os, sqlite3, threading, time
from pathlib import Path

from .. import config as C

DB_PATH = Path(os.getenv("EXEC_DB", str(C.BASE / "exec.db")))
CONFIG_PATH = Path(os.getenv("EXEC_CONFIG", str(C.BASE / "exec_config.json")))
_lock = threading.RLock()
_con = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, ts REAL, source TEXT, symbol TEXT, side TEXT, intent TEXT, status TEXT,
  nonce TEXT, expires_ts REAL, msg_id INTEGER, result TEXT, decided_by TEXT, decided_ts REAL, price0 REAL);
CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, ts REAL, proposal_id TEXT, symbol TEXT, side TEXT, qty REAL, entry_type TEXT,
  entry_price REAL, stop REAL, tp REAL, leverage INTEGER, margin TEXT, status TEXT, entry_avg REAL, exit_avg REAL, pnl REAL, fees REAL,
  close_ts REAL, close_reason TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS grids (id TEXT PRIMARY KEY, ts REAL, symbol TEXT, cfg TEXT, status TEXT, inventory REAL, invest REAL,
  start_price REAL, start_ts REAL, stop_ts REAL, state TEXT);
CREATE TABLE IF NOT EXISTS grid_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, gid TEXT, level INTEGER, side TEXT, price REAL, qty REAL,
  client_id TEXT, order_id TEXT, status TEXT, ts REAL, fill_ts REAL, fill_price REAL);
CREATE INDEX IF NOT EXISTS go_gid ON grid_orders (gid, status);
CREATE TABLE IF NOT EXISTS grid_cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, gid TEXT, ts REAL, level INTEGER, buy_price REAL,
  sell_price REAL, qty REAL, profit REAL, fees REAL);
"""


def init(path=None):
    global _con, DB_PATH
    with _lock:
        if _con is not None:
            _con.close()
        DB_PATH = Path(path) if path else DB_PATH
        _con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10, isolation_level=None)
        _con.row_factory = sqlite3.Row
        try:
            _con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        _con.executescript(SCHEMA)
        os.chmod(DB_PATH, 0o600)


def q(sql, args=()):
    with _lock:
        if _con is None:
            init()
        return [dict(r) for r in _con.execute(sql, args).fetchall()]


def x(sql, args=()):
    with _lock:
        if _con is None:
            init()
        return _con.execute(sql, args).lastrowid


def kv_get(key, default=None):
    r = q("SELECT value FROM kv WHERE key=?", (key,))
    if not r:
        return default
    try:
        return json.loads(r[0]["value"])
    except Exception:
        return default


def kv_set(key, value):
    x("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def event(level, kind, text):
    x("INSERT INTO events (ts, level, kind, text) VALUES (?,?,?,?)", (time.time(), level, kind, str(text)[:600]))
    x("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 2000")


def events(limit=100):
    return q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))


# ------------------------------------------------------------------ configuration
DEFAULTS = {
    "armed": False,                      # live trading needs an explicit arm step; paper mode does not
    "futures": {
        "enabled": True, "mode": "manual",              # manual = every signal asks you first; auto = risk-checked signals trade by themselves
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "RENDERUSDT", "INJUSDT", "FETUSDT", "NEARUSDT", "AVAXUSDT", "OPUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT"],
        "style": "intraday", "signal_states": ["READY"], "min_confidence": 60, "min_rr": 1.0, "min_stop_pct": 0.8,
        "entry_type": "LIMIT", "risk_pct": 0.5, "max_positions": 2, "max_leverage": 5, "default_leverage": 3, "margin_type": "ISOLATED",
        "max_notional_pct": 300, "daily_loss_limit_pct": 2.0, "max_daily_trades": 6, "cooldown_min": 60,
        "confirm_timeout_min": 5, "max_drift_pct": 0.3, "allow_no_stop": False, "stop_working_type": "MARK_PRICE",
        "protect_grace_s": 20, "on_unprotected": "close",
    },
    "spot_grid": {"enabled": True, "max_grids": 3, "fee_pct": 0.1, "poll_s": 5},
}
_LIMITS = {   # (min, max) for numeric futures settings
    "min_confidence": (0, 100), "min_rr": (0, 10), "min_stop_pct": (0, 20), "risk_pct": (0.01, 5), "max_positions": (1, 20), "max_leverage": (1, 125),
    "default_leverage": (1, 125), "max_notional_pct": (10, 5000), "daily_loss_limit_pct": (0.1, 50), "max_daily_trades": (1, 100), "cooldown_min": (0, 1440),
    "confirm_timeout_min": (1, 120), "max_drift_pct": (0.01, 5), "protect_grace_s": (5, 300)}


def _merge(base, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        _merge(cfg, json.loads(CONFIG_PATH.read_text()))
    except Exception:
        pass
    return cfg


def clean(patch):
    """Validate a config patch (unknown keys and bad values are dropped, numbers are clamped)."""
    out = {}
    if isinstance(patch.get("armed"), bool):
        out["armed"] = patch["armed"]
    f = patch.get("futures")
    if isinstance(f, dict):
        o = {}
        for k, v in f.items():
            if k in _LIMITS and isinstance(v, (int, float)) and not isinstance(v, bool):
                lo, hi = _LIMITS[k]
                o[k] = max(lo, min(hi, v)) if k not in ("max_positions", "max_leverage", "default_leverage", "max_daily_trades", "cooldown_min", "confirm_timeout_min", "protect_grace_s") else int(max(lo, min(hi, v)))
            elif k == "mode" and v in ("manual", "auto"):
                o[k] = v
            elif k == "enabled" and isinstance(v, bool):
                o[k] = v
            elif k == "entry_type" and v in ("LIMIT", "MARKET"):
                o[k] = v
            elif k == "margin_type" and v in ("ISOLATED", "CROSSED"):
                o[k] = v
            elif k == "on_unprotected" and v in ("close", "alert"):
                o[k] = v
            elif k == "stop_working_type" and v in ("MARK_PRICE", "CONTRACT_PRICE"):
                o[k] = v
            elif k == "allow_no_stop" and isinstance(v, bool):
                o[k] = v
            elif k == "style" and v in ("scalp", "intraday", "swing"):
                o[k] = v
            elif k == "signal_states" and isinstance(v, list):
                o[k] = [s for s in v if s in ("READY", "IN ZONE", "WAIT")]
            elif k == "symbols" and isinstance(v, list):
                o[k] = [s.upper() for s in v if isinstance(s, str) and s.isalnum() and s.upper().endswith("USDT")][:60]
        if o:
            out["futures"] = o
    g = patch.get("spot_grid")
    if isinstance(g, dict):
        o = {}
        if isinstance(g.get("enabled"), bool):
            o["enabled"] = g["enabled"]
        if isinstance(g.get("max_grids"), (int, float)) and not isinstance(g.get("max_grids"), bool):
            o["max_grids"] = int(max(1, min(20, g["max_grids"])))
        if isinstance(g.get("fee_pct"), (int, float)) and not isinstance(g.get("fee_pct"), bool):
            o["fee_pct"] = max(0.0, min(1.0, float(g["fee_pct"])))
        if o:
            out["spot_grid"] = o
    return out


def save_config(patch):
    cfg = config()
    stored = {}
    try:
        stored = json.loads(CONFIG_PATH.read_text())
    except Exception:
        pass
    _merge(stored, clean(patch))
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(stored, indent=2))
    os.replace(tmp, CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)
    return config()
