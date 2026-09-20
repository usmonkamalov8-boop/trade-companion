"""Forex Factory economic calendar (free weekly JSON feed, no key) and red-folder alerts.

Only high-impact ("red folder") events for the currencies in CAL_CURRENCIES are tracked
by default. Alerts are written to the activity log (kind "news"), which the push
dispatcher forwards to your phone, so they arrive even when the app is closed."""
import asyncio, json, os, time
from datetime import datetime, timezone
import httpx
from . import events, config as C

FEEDS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
         "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]   # next week is best effort
UA = {"User-Agent": "Mozilla/5.0"}
CACHE = C.BASE / "calendar_cache.json"
SENT = C.BASE / "calendar_sent.json"
AFFECTS = {"USD": "Gold, USD pairs, crypto", "EUR": "EUR/USD", "GBP": "GBP/USD", "JPY": "USD/JPY"}

_st = {"events": [], "updated": 0.0, "fetched": 0.0, "error": None, "next_try": 0.0}


def _load_cache():
    try:
        d = json.loads(CACHE.read_text())
        _st["events"], _st["updated"] = d["events"], d["updated"]
    except Exception:
        pass


_load_cache()


def cfg():
    imp = os.getenv("CAL_IMPACT", "High").strip().lower()
    levels = {"high"} if imp == "high" else ({"high", "medium"} if imp == "medium" else {"high", "medium", "low"})
    leads = []
    for x in os.getenv("CAL_LEADS", "60,15,0").split(","):
        x = x.strip()
        if x.isdigit():
            leads.append(int(x))
    return {
        "levels": levels,
        "cur": {c.strip().upper() for c in os.getenv("CAL_CURRENCIES", "USD,EUR,GBP,JPY").split(",") if c.strip()},
        "leads": sorted(set(leads), reverse=True) or [60, 15, 0],
        "alerts": os.getenv("CAL_ALERTS", "1").strip() != "0",
        "tz": os.getenv("CAL_TZ", "UTC").strip() or "UTC",
    }


def local(ts, tzname):
    """Local wall-clock time and a 'UTC+4' label for a unix timestamp."""
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(ts, ZoneInfo(tzname))
    except Exception:
        d = datetime.fromtimestamp(ts, timezone.utc)
    off = (d.utcoffset().total_seconds() / 3600) if d.utcoffset() else 0
    return d, f"UTC{off:+g}"


def _norm(e):
    try:
        dt = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        cur, title = str(e["country"]).upper(), str(e["title"]).strip()
    except Exception:
        return None
    ts = dt.timestamp()
    return {"id": f"{cur}|{title}|{int(ts)}", "title": title, "currency": cur,
            "impact": str(e.get("impact") or "").lower(), "ts": ts,
            "forecast": str(e.get("forecast") or ""), "previous": str(e.get("previous") or "")}


async def refresh(force=False):
    """Fetch the weekly feed. Runs at most every 30 min (5 min after a failure); the free feed
    is rate limited per IP, so a failed fetch keeps the last good data."""
    now = time.time()
    if force:
        if now - _st["fetched"] < 120:
            return
    elif now < _st["next_try"]:
        return
    out, week_ok, err = {}, False, None
    async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as cl:
        for i, url in enumerate(FEEDS):
            try:
                r = await cl.get(url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                for e in r.json():
                    n = _norm(e)
                    if n:
                        out[n["id"]] = n
                if i == 0:
                    week_ok = True
            except Exception as ex:
                if i == 0:
                    err = f"{type(ex).__name__}: {str(ex)[:100]}"
    _st["fetched"] = now
    if week_ok:
        _st["events"] = sorted(out.values(), key=lambda e: e["ts"])
        _st["updated"], _st["error"], _st["next_try"] = now, None, now + 1800
        try:
            CACHE.write_text(json.dumps({"events": _st["events"], "updated": now}))
        except Exception:
            pass
    else:
        _st["error"], _st["next_try"] = err or "feed unavailable", now + 300


def status():
    return {"updated": _st["updated"], "error": _st["error"], "currencies": sorted(cfg()["cur"])}


def _levels(impact, c):
    if impact == "high":
        return {"high"}
    if impact == "medium":
        return {"high", "medium"}
    return c["levels"]


async def upcoming(hours=168, impact=None, past_h=2):
    await refresh()
    c = cfg()
    levels = _levels(impact, c)
    now = time.time()
    rows = [e for e in _st["events"]
            if e["currency"] in c["cur"] and e["impact"] in levels
            and now - past_h * 3600 <= e["ts"] <= now + hours * 3600]
    return [{**e, "mins": round((e["ts"] - now) / 60), "affects": AFFECTS.get(e["currency"], "")} for e in rows]


def _alert(e, lead, mins, c):
    d, tzl = local(e["ts"], c["tz"])
    folder = "Red folder" if e["impact"] == "high" else "Orange folder"
    name = f"{e['currency']} {e['title']}"
    extra = []
    if e["forecast"]:
        extra.append(f"Forecast {e['forecast']}")
    if e["previous"]:
        extra.append(f"previous {e['previous']}")
    if lead > 0:
        title = f"{folder}: {name} in {max(1, round(mins))} min"
        text = f"Release at {d:%H:%M} ({tzl})."
    else:
        title = f"{folder} NOW: {name}"
        text = "Being released now. Expect a volatility spike."
    if extra:
        text += " " + ", ".join(extra) + "."
    aff = AFFECTS.get(e["currency"], "")
    if aff:
        text += f" Affects: {aff}."
    events.add("news", title, text, "warning")


def test_alert():
    c = cfg()
    d, tzl = local(time.time() + 900, c["tz"])
    events.add("news", "Red folder: USD Test event in 15 min",
               f"This is a test of the red-folder alert. Release at {d:%H:%M} ({tzl}). "
               "Forecast 0.3%, previous 0.4%. Affects: Gold, USD pairs, crypto.", "warning")


def _load_sent():
    try:
        return set(json.loads(SENT.read_text()))
    except Exception:
        return set()


def _save_sent(s):
    cutoff = time.time() - 2 * 86400
    keep = []
    for k in s:
        try:
            if int(k.split("|")[-2]) >= cutoff:
                keep.append(k)
        except Exception:
            pass
    try:
        SENT.write_text(json.dumps(keep))
    except Exception:
        pass


async def run():
    await asyncio.sleep(6)
    sent = _load_sent()
    while True:
        try:
            await refresh()
            c = cfg()
            changed = False
            if c["alerts"]:
                now = time.time()
                horizon = max(c["leads"]) + 1
                for e in _st["events"]:
                    if e["currency"] not in c["cur"] or e["impact"] not in c["levels"]:
                        continue
                    mins = (e["ts"] - now) / 60
                    if mins < -2 or mins > horizon:
                        continue
                    due = [L for L in c["leads"]
                           if mins <= L and f"{e['id']}|{L}" not in sent and (mins > 0 or L == 0)]
                    if not due:
                        continue
                    lead = min(due)           # the most imminent lead that is due
                    for L in c["leads"]:      # older leads must not fire late
                        if mins <= L:
                            sent.add(f"{e['id']}|{L}")
                    _alert(e, lead, mins, c)
                    changed = True
            if changed:
                _save_sent(sent)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print("calendar error:", ex)
        await asyncio.sleep(20)
