import hashlib, hmac, json, os, subprocess, time
from datetime import datetime, timezone
from urllib.parse import urlencode
import httpx
from . import config as C

FAPI = "https://fapi.binance.com"
DEFAULT = {
    "halted": False,
    "profiles": {
        "hier": {"enabled": True, "shadow": False, "risk_pct": 1.0, "max_positions": 3},
        "scalp": {"enabled": True, "shadow": True, "risk_pct": 1.0, "max_positions": 2},
    },
}


def load():
    st = json.loads(json.dumps(DEFAULT))
    try:
        d = json.loads(C.CONTROL_FILE.read_text())
        st["halted"] = bool(d.get("halted", False))
        for k, v in d.get("profiles", {}).items():
            if k in st["profiles"]:
                st["profiles"][k].update(v)
    except Exception:
        pass
    return st


def save(st):
    tmp = C.CONTROL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(tmp, C.CONTROL_FILE)


def service_state():
    try:
        r = subprocess.run(["systemctl", "is-active", C.BOT_SERVICE],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


async def _signed(method, path, params=None):
    if not (C.BINANCE_KEY and C.BINANCE_SECRET):
        raise RuntimeError("Binance keys are not set in backend/.env")
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 10000
    q = urlencode(p)
    sig = hmac.new(C.BINANCE_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(timeout=15) as cl:
        r = await cl.request(method, f"{FAPI}{path}?{q}&signature={sig}",
                             headers={"X-MBX-APIKEY": C.BINANCE_KEY})
    if r.status_code != 200:
        raise RuntimeError(f"Binance {r.status_code}: {r.text[:200]}")
    return r.json()


async def _raw_positions():
    rows = await _signed("GET", "/fapi/v2/positionRisk")
    return [r for r in rows if r["symbol"] in C.PAIRS and float(r["positionAmt"]) != 0]


async def positions():
    out = []
    for p in await _raw_positions():
        amt = float(p["positionAmt"])
        out.append({
            "symbol": p["symbol"], "side": "LONG" if amt > 0 else "SHORT",
            "qty": abs(amt), "entry": float(p["entryPrice"]),
            "mark": float(p["markPrice"]), "pnl": float(p["unRealizedProfit"]),
            "liq": float(p.get("liquidationPrice") or 0),
        })
    return out


async def account():
    rows = await _signed("GET", "/fapi/v2/balance")
    u = next((r for r in rows if r["asset"] == "USDT"), {})
    return {"balance": float(u.get("balance", 0)),
            "available": float(u.get("availableBalance", 0)),
            "upnl": float(u.get("crossUnPnl", 0))}


async def pnl(days=7):
    rows = await _signed("GET", "/fapi/v1/income", {
        "incomeType": "REALIZED_PNL",
        "startTime": int((time.time() - days * 86400) * 1000), "limit": 1000})
    by_sym, by_day = {}, {}
    wins = losses = 0
    for r in rows:
        if r["symbol"] not in C.PAIRS:
            continue
        v = float(r["income"])
        if v == 0:
            continue
        by_sym[r["symbol"]] = by_sym.get(r["symbol"], 0) + v
        d = datetime.fromtimestamp(int(r["time"]) / 1000, timezone.utc).strftime("%m-%d")
        by_day[d] = by_day.get(d, 0) + v
        wins += v > 0
        losses += v < 0
    return {"days": days, "total": round(sum(by_sym.values()), 2),
            "trades": wins + losses, "wins": wins, "losses": losses,
            "by_symbol": {k: round(v, 2) for k, v in by_sym.items()},
            "by_day": {k: round(v, 2) for k, v in sorted(by_day.items())}}


async def close_all():
    results = []
    for p in await _raw_positions():
        amt = float(p["positionAmt"])
        sym = p["symbol"]
        params = {"symbol": sym, "side": "SELL" if amt > 0 else "BUY",
                  "type": "MARKET", "quantity": p["positionAmt"].lstrip("-")}
        if p.get("positionSide", "BOTH") == "BOTH":
            params["reduceOnly"] = "true"
        else:
            params["positionSide"] = p["positionSide"]
        try:
            await _signed("POST", "/fapi/v1/order", params)
            results.append({"symbol": sym, "ok": True})
        except Exception as e:
            results.append({"symbol": sym, "ok": False, "error": str(e)})
            continue  # never cancel SL/TP if the close failed
        for path in ("/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"):
            try:
                await _signed("DELETE", path, {"symbol": sym})
            except Exception:
                pass
    return results
