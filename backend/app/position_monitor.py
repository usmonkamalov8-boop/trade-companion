"""Background monitor for tcexec-managed futures positions: periodically re-runs the existing r3
strategy engine for each open, protected position and raises an in-app alert when structure or
confidence moves against the position, or price nears its own stop/target.

Read-only against tcexec: it only calls GET /status (the same endpoint the Futures tab already
polls) and never places, moves or cancels any order - it shares no code path with execution/*.py.
Alerts are in-memory only (in-app delivery, per the agreed scope) and are exposed to the app via
GET /api/positions/alerts, keyed by exchange symbol.

Only structure/confidence (from the same engine.analyze() every other screen uses) and pure
price-distance to the position's own stop/target are used - both are real, already-existing
fields; nothing here is guessed at or invented."""
import asyncio, os, time

import httpx

from . import engine, prefs, config as C

EXEC_URL = os.getenv("EXEC_URL", "http://127.0.0.1:8100")
NEAR_PCT = 0.35          # % distance to the stop/target counted as "close"
POLL_S = 75

_alerts = {}             # symbol -> {"text", "level", "kind", "ts"}
_state = {}              # symbol -> last {"direction", "status"} seen (edge-triggered, no repeat spam)


def _tok():
    return os.getenv("EXEC_TOKEN", "")


async def _positions():
    tok = _tok()
    if not tok:
        return []
    try:
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.get(f"{EXEC_URL}/status", headers={"X-Exec-Token": tok})
        if r.status_code != 200:
            return []
        sn = (r.json() or {}).get("snapshot") or {}
        return sn.get("positions") or []
    except Exception:
        return []


def _base(symbol):
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _pct(a, b):
    return abs(a - b) / b * 100 if b else 0.0


def _set(symbol, level, kind, text):
    _alerts[symbol] = {"text": text, "level": level, "kind": kind, "ts": int(time.time())}


def _clear(symbol, kind):
    a = _alerts.get(symbol)
    if a and a["kind"] == kind:
        _alerts.pop(symbol, None)


def alerts_by_symbol():
    return dict(_alerts)


async def _check_one(x):
    symbol = x.get("symbol")
    if not symbol or not x.get("managed") or x.get("stop") is None:
        return
    base = _base(symbol)
    if base not in C.CRYPTO:
        return
    cfg = prefs.get().get("position_alerts", {})
    near_pct = cfg.get("near_pct", NEAR_PCT)
    want = "long" if x.get("side") == "LONG" else "short"
    style = prefs.get()["analyst"]["style"]
    try:
        res = await engine.analyze(base, style)
    except Exception:
        return
    if res.get("error") or res.get("closed"):
        return
    s = res["setup"]
    prev = _state.get(symbol, {})
    try:
        mark, stop = float(x["mark"]), float(x["stop"])
        tp = float(x["tp"]) if x.get("tp") is not None else None
    except (TypeError, ValueError):
        return

    # 1. structure now clearly reads against the position's own side
    if cfg.get("structure_alerts", True) and s["direction"] not in ("none", want):
        if prev.get("direction") != s["direction"]:
            _set(symbol, "warning", "structure",
                 f"{symbol}: structure now reads {s['direction'].upper()} against your {want.upper()} "
                 f"position ({s['status']}, {s['confidence']}% confidence). Consider tightening the "
                 f"stop or scaling out.")
    else:
        _clear(symbol, "structure")

    # 2. the confluence backing this trade has degraded sharply while the position is still open
    if cfg.get("confidence_alerts", True) and (s["status"] == "LOW CONFLUENCE" or s["confidence"] < 35):
        if prev.get("status") != s["status"]:
            _set(symbol, "warning", "confidence",
                 f"{symbol}: the setup backing this trade has weakened ({s['status']}, "
                 f"{s['confidence']}% confidence). No fresh confluence supports holding at full size.")
    else:
        _clear(symbol, "confidence")

    # 3. pure price-distance to the position's own stop/target - no engine dependency
    if cfg.get("price_alerts", True):
        if _pct(mark, stop) <= near_pct:
            _set(symbol, "warning", "near_stop", f"{symbol}: price is within {near_pct:.2f}% of the stop ({stop}).")
        elif tp is not None and _pct(mark, tp) <= near_pct:
            _set(symbol, "success", "near_tp",
                 f"{symbol}: price is within {near_pct:.2f}% of the target ({tp}). Consider trailing the "
                 f"stop or taking partial profit.")
        else:
            _clear(symbol, "near_stop")
            _clear(symbol, "near_tp")
    else:
        _clear(symbol, "near_stop")
        _clear(symbol, "near_tp")

    _state[symbol] = {"direction": s["direction"], "status": s["status"]}


async def run():
    await asyncio.sleep(10)
    while True:
        try:
            for x in await _positions():
                await _check_one(x)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("position_monitor error:", e)
        await asyncio.sleep(POLL_S)
