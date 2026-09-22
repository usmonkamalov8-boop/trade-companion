"""Turns the analyst's screener rows into trade intents. The rules here are plain filters; an AI/ML scorer could later plug into
decide() to veto or size signals, but it would still have to pass the risk engine and (in manual mode) your confirmation."""
import hashlib, time

import httpx

from . import store


def decide(row, cfg):
    """(True, "") when the row is a tradeable signal under the current settings, else (False, reason). The place for a future model."""
    if row.get("direction") not in ("long", "short") or not row.get("calc"):
        return False, "no setup"
    if row.get("status") not in cfg["signal_states"]:
        return False, f"status {row.get('status')}"
    if (row.get("confidence") or 0) < cfg["min_confidence"]:
        return False, f"confidence {row.get('confidence')} below {cfg['min_confidence']}"
    if (row.get("rr1") or 0) < cfg["min_rr"]:
        return False, "reward to risk too low"
    return True, ""


def to_intent(row, cfg):
    c = row["calc"]
    return {"symbol": row["name"].upper() + "USDT", "side": "LONG" if row["direction"] == "long" else "SHORT", "entry_type": cfg["entry_type"],
            "price": c["entry"], "stop": c["stop"], "tp": c["tp1"], "risk_pct": cfg["risk_pct"], "leverage": cfg["default_leverage"],
            "margin_type": cfg["margin_type"], "source": "signal", "note": f"{row.get('style', '')} confidence {row.get('confidence')}"}


def signature(row):
    c = row["calc"]
    return hashlib.sha1(f"{row['name']}|{row.get('style')}|{row['direction']}|{c['entry']:.6g}|{c['stop']:.6g}".encode()).hexdigest()[:16]


async def fetch_rows(base_url, token, style):
    async with httpx.AsyncClient(timeout=30) as h:
        r = await h.get(f"{base_url}/api/screener", params={"market": "crypto", "style": style}, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json().get("rows", [])


async def scan(futures, fetch, now=time.time):
    """One pass: fetch rows, propose every new eligible signal once. Returns a small report."""
    cfg = store.config()["futures"]
    if not cfg["enabled"] or futures.halted:
        return {"skipped": "futures profile off or stopped"}
    rows = await fetch(cfg["style"])
    out = {"seen": len(rows), "proposed": 0, "skipped": 0}
    for row in rows:
        if row.get("name", "").upper() + "USDT" not in cfg["symbols"]:
            continue
        ok, why = decide(row, cfg)
        if not ok:
            continue
        sig = signature(row)
        seen = store.kv_get("sig:" + sig)
        if seen and now() - seen < 12 * 3600:
            continue
        r = await futures.propose(to_intent(row, cfg), "signal")
        if r.get("created") or r.get("auto"):
            store.kv_set("sig:" + sig, now())
            out["proposed"] += 1
        else:
            store.kv_set("sig:" + sig, now() - 12 * 3600 + 900)      # refused: look again in 15 minutes, not every minute
            out["skipped"] += 1
    return out
