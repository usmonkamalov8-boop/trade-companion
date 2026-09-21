"""Economic calendar with red-folder alerts.

Primary source: the free Forex Factory weekly JSON feed (two hosts). If both fail, a backup
feed (TradingView calendar) is used so the Calendar screen is never empty. Only events for the
currencies and impact levels chosen in the app's Settings are kept. Alerts go to the activity
log (kind "news"); the push dispatcher forwards them to your phone even when the app is closed."""
import asyncio, json, os, time
from datetime import datetime, timedelta, timezone
import httpx
from . import events, prefs, tz as TZ, config as C

FF_URLS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
           "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json"]
FF_NEXT = ["https://nfs.faireconomy.media/ff_calendar_nextweek.json",
           "https://cdn-nfs.faireconomy.media/ff_calendar_nextweek.json"]
TV_URL = "https://economic-calendar.tradingview.com/events"
HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Mobile Safari/537.36",
           "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.forexfactory.com/"}
TV_HEADERS = {**HEADERS, "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}
TV_COUNTRIES = {"USD": ["US"], "EUR": ["EU", "DE", "FR", "IT", "ES"], "GBP": ["GB"], "JPY": ["JP"], "AUD": ["AU"],
                "CAD": ["CA"], "CHF": ["CH"], "NZD": ["NZ"]}
CACHE = C.BASE / "calendar_cache.json"
SENT = C.BASE / "calendar_sent.json"
AFFECTS = {"USD": "Gold, USD pairs, crypto", "EUR": "EUR/USD", "GBP": "GBP/USD", "JPY": "USD/JPY",
           "AUD": "AUD/USD", "CAD": "USD/CAD", "CHF": "USD/CHF", "NZD": "NZD/USD"}

_st = {"events": [], "updated": 0.0, "fetched": 0.0, "error": None, "next_try": 0.0,
       "source": None, "attempts": []}


def _load_cache():
    try:
        d = json.loads(CACHE.read_text())
        _st["events"], _st["updated"], _st["source"] = d["events"], d["updated"], d.get("source")
    except Exception:
        pass


_load_cache()


def cfg():
    p = prefs.get()["calendar"]
    return {
        "levels": {"high"} if p["impact"] == "high" else {"high", "medium"},
        "cur": set(p["currencies"]),
        "leads": sorted(set(p["leads"]), reverse=True) or [60, 15, 0],
        "alerts": p["alerts"],
    }


def local(ts, tzname=None):
    """Wall-clock time in the user's time zone (Settings > Time zone) and a 'UTC+4' label."""
    return TZ.local(ts)


def _event(cur, title, ts, impact, forecast, previous):
    return {"id": f"{cur}|{title}|{int(ts)}", "title": title, "currency": cur, "impact": impact, "ts": ts,
            "forecast": forecast, "previous": previous}


def _norm_ff(e):
    try:
        dt = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
        cur, title = str(e["country"]).upper(), str(e["title"]).strip()
    except Exception:
        return None
    return _event(cur, title, dt.astimezone(timezone.utc).timestamp(), str(e.get("impact") or "").lower(),
                  str(e.get("forecast") or ""), str(e.get("previous") or ""))


def _fmt_val(v, unit):
    if v is None or v == "":
        return ""
    return f"{v}{unit or ''}"


def _norm_tv(e, rev):
    try:
        dt = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cur = str(e.get("currency") or rev.get(str(e.get("country")).upper(), "")).upper()
        title = str(e["title"]).strip()
        imp = {1: "high", 0: "medium", -1: "low"}.get(int(e.get("importance", -1)), "low")
    except Exception:
        return None
    if not cur:
        return None
    unit = e.get("unit") or ""
    return _event(cur, title, dt.astimezone(timezone.utc).timestamp(), imp,
                  _fmt_val(e.get("forecast"), unit), _fmt_val(e.get("previous"), unit))


async def _get_json(cl, url, params=None, headers=None):
    r = await cl.get(url, params=params, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except Exception:
        raise RuntimeError("not JSON (blocked or rate limited)")


async def refresh(force=False):
    """Fetch the calendar. Runs at most every 30 min (5 min after a failure); a failed fetch keeps
    the last good data. Force-refresh is limited to once per 60 seconds."""
    now = time.time()
    if force:
        if now - _st["fetched"] < 60:
            return
    elif now < _st["next_try"]:
        return
    attempts, out, source = [], {}, None
    async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as cl:
        for url in FF_URLS:
            t0 = time.time()
            try:
                data = await _get_json(cl, url)
                got = [n for n in (_norm_ff(e) for e in data) if n]
                if not got:
                    raise RuntimeError("empty feed")
                for n in got:
                    out[n["id"]] = n
                attempts.append({"source": "Forex Factory", "url": url.split("/")[2], "ok": True,
                                 "count": len(got), "ms": int((time.time() - t0) * 1000)})
                source = "Forex Factory"
                break
            except Exception as ex:
                attempts.append({"source": "Forex Factory", "url": url.split("/")[2], "ok": False,
                                 "error": f"{type(ex).__name__}: {str(ex)[:80]}"})
        if source == "Forex Factory":
            for url in FF_NEXT:                       # best effort: the feed may not exist yet
                try:
                    for e in await _get_json(cl, url):
                        n = _norm_ff(e)
                        if n:
                            out[n["id"]] = n
                    break
                except Exception:
                    continue
        else:
            t0 = time.time()
            try:
                c = cfg()
                rev = {ctry: cur for cur, cs in TV_COUNTRIES.items() for ctry in cs}
                countries = ",".join(x for cur in c["cur"] for x in TV_COUNTRIES.get(cur, []))
                start = datetime.now(timezone.utc) - timedelta(hours=6)
                params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                          "to": (start + timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                          "countries": countries}
                data = await _get_json(cl, TV_URL, params, TV_HEADERS)
                rows = data.get("result", data) if isinstance(data, dict) else data
                got = [n for n in (_norm_tv(e, rev) for e in rows) if n]
                if not got:
                    raise RuntimeError("empty feed")
                for n in got:
                    out[n["id"]] = n
                attempts.append({"source": "TradingView (backup)", "url": "economic-calendar.tradingview.com",
                                 "ok": True, "count": len(got), "ms": int((time.time() - t0) * 1000)})
                source = "TradingView (backup)"
            except Exception as ex:
                attempts.append({"source": "TradingView (backup)", "url": "economic-calendar.tradingview.com",
                                 "ok": False, "error": f"{type(ex).__name__}: {str(ex)[:80]}"})
    _st["fetched"], _st["attempts"] = now, attempts
    if source:
        _st["events"] = sorted(out.values(), key=lambda e: e["ts"])
        _st.update({"updated": now, "error": None, "next_try": now + 1800, "source": source})
        try:
            CACHE.write_text(json.dumps({"events": _st["events"], "updated": now, "source": source}))
        except Exception:
            pass
    else:
        errs = [a.get("error", "") for a in attempts if not a["ok"]]
        _st["error"] = errs[0] if errs else "feed unavailable"
        _st["next_try"] = now + 300


def status():
    return {"updated": _st["updated"], "error": _st["error"], "source": _st["source"],
            "currencies": sorted(cfg()["cur"])}


def diag():
    return {"source": _st["source"], "updated": _st["updated"], "error": _st["error"],
            "count": len(_st["events"]), "attempts": _st["attempts"],
            "next_try_in": max(0, int(_st["next_try"] - time.time()))}


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
    lab = TZ.label_now()
    return [{**e, "mins": round((e["ts"] - now) / 60), "affects": AFFECTS.get(e["currency"], ""),
             "local_time": TZ.hm(e["ts"]), "local_day": TZ.day(e["ts"]), "tz": lab} for e in rows]


def _alert(e, lead, mins, c):
    d, tzl = local(e["ts"])
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
    d, tzl = local(time.time() + 900)
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
