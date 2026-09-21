"""Background push notifications through ntfy (https://ntfy.sh or your own ntfy server) and/or a Telegram bot.

Every new row in the activity log (from the API, the watcher, the calendar or the bot) whose
category is enabled in the app's Settings is delivered. The ntfy Android app shows the banner even when Trade Companion
is closed; Telegram is the fallback when ntfy refuses (the free ntfy.sh server allows 250 messages a day per server IP
and answers 429 after that). Routes: auto = ntfy first and Telegram whenever ntfy fails or is paused, ntfy, telegram, both.
A provider that fails is paused (until 00:00 UTC for the ntfy.sh daily quota) so the server does not hammer it."""
import asyncio, html, json, os, time
import httpx
from . import events, prefs, tz, config as C

STATE = C.BASE / "push_state.json"
_TITLES = {"position": "Position update", "trade": "Trade update", "command": "Bot control action",
           "service": "Bot service change", "warning": "Alert", "news": "News alert",
           "risk": "Risk change", "profile": "Profile change", "system": "System message", "setup": "Trade setup", "digest": "Weekly digest"}


PROVIDERS = ("ntfy", "telegram")


def cfg():
    p = prefs.get()["push"]
    return {
        "topic": os.getenv("NTFY_TOPIC", "").strip(),
        "server": os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/"),
        "token": os.getenv("NTFY_TOKEN", "").strip(),
        "tg_token": os.getenv("TG_BOT_TOKEN", "").strip(),
        "tg_chat": os.getenv("TG_CHAT_ID", "").strip(),
        "tg_api": os.getenv("TG_API", "https://api.telegram.org").strip().rstrip("/"),
        "detail": p["detail"],
        "kinds": p["kinds"],
        "on": p["enabled"],
        "route": p.get("route", "auto"),
        "budget": p.get("ntfy_budget", 200),
    }


def configured(p, c):
    return bool(c["topic"]) if p == "ntfy" else bool(c["tg_token"] and c["tg_chat"])


def enabled(c=None):
    c = c or cfg()
    return c["on"] and any(configured(p, c) for p in PROVIDERS)


def _utc_day(now=None):
    return time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))


def _next_midnight_utc(now=None):
    now = now or time.time()
    return (int(now // 86400) + 1) * 86400 + 30            # the ntfy.sh visitor counters reset at 00:00 UTC


def _health():
    s = _state()
    h = s.get("health") or {}
    for p in PROVIDERS:
        h.setdefault(p, {})
        h[p].setdefault("sent", 0)
        h[p].setdefault("day", "")
        h[p].setdefault("paused_until", 0)
        h[p].setdefault("error", None)
    return s, h


def _mark_ok(p, now=None):
    s, h = _health()
    d = _utc_day(now)
    x = h[p]
    x["sent"] = (x["sent"] + 1) if x["day"] == d else 1
    x["day"], x["error"], x["paused_until"] = d, None, 0
    s["health"] = h
    _save_state(s)


def _mark_fail(p, msg, pause, now=None):
    s, h = _health()
    h[p]["error"] = str(msg)[:200]
    h[p]["paused_until"] = (now or time.time()) + pause
    h[p]["err_ts"] = now or time.time()
    s["health"] = h
    _save_state(s)


def _sent_today(h, p, now=None):
    return h[p]["sent"] if h[p]["day"] == _utc_day(now) else 0


def info():
    c = cfg()
    s, h = _health()
    now = time.time()
    prov = {}
    for p in PROVIDERS:
        prov[p] = {"configured": configured(p, c), "sent_today": _sent_today(h, p), "error": h[p]["error"],
                   "paused_until": h[p]["paused_until"] if h[p]["paused_until"] > now else 0}
    prov["telegram"]["chat"] = ("..." + c["tg_chat"][-4:]) if c["tg_chat"] else ""
    prov["ntfy"]["budget"] = c["budget"] if "ntfy.sh" in c["server"] else 0
    return {"enabled": enabled(c), "configured": any(v["configured"] for v in prov.values()), "server": c["server"],
            "topic": c["topic"], "detail": c["detail"], "route": c["route"], "providers": prov}


def should_push(e, c):
    return bool(c["kinds"].get(e["kind"], False)) or e["level"] == "error"


def _state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(d):
    try:
        STATE.write_text(json.dumps(d))
    except Exception:
        pass


def _mins(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def in_quiet(now=None):
    """Are we inside the quiet hours from Settings (in the user's time zone, may wrap midnight)?"""
    q = prefs.get()["setups"]["quiet"]
    if not q.get("enabled"):
        return False
    d = tz.local(now or time.time())[0]
    cur, a, b = d.hour * 60 + d.minute, _mins(q["from"]), _mins(q["to"])
    if a == b:
        return False
    return a <= cur < b if a < b else (cur >= a or cur < b)


def policy(body, e, now=None):
    """Quiet hours silence setup pushes (priority 1); a daily cap turns extra 'high' pushes into normal ones.
    Urgent READY alerts always sound outside quiet hours; inside them only if 'allow urgent' is on."""
    if e.get("kind") != "setup":
        return body
    st = prefs.get()["setups"]
    prio = body["priority"]
    if in_quiet(now):
        if not (st["quiet"].get("allow_urgent") and prio == 5):
            body["priority"] = 1
            return body
    cap = st.get("loud_cap", 3)
    if prio >= 4:
        s = _state()
        today = tz.local(now or time.time())[0].date().isoformat()
        loud = s.get("loud") or {}
        n = loud.get("n", 0) if loud.get("day") == today else 0
        if prio == 4 and cap and n >= cap:
            body["priority"] = 3
            body["message"] = (body["message"] + " (daily limit for loud alerts reached)")[:400]
        else:
            s["loud"] = {"day": today, "n": n + 1}
            _save_state(s)
    return body


def setup_priority(e, c=None):
    """ntfy priority (1-5) for a setup alert from its confidence: 5 = urgent (loudest, can break through Do Not
    Disturb), 4 = high, 3 = default, 2 = quiet. Each level has its own Android notification channel in the ntfy app,
    so it can have its own sound. READY alerts are at least high."""
    import re
    s = prefs.get()["setups"]["sound"]
    m = re.search(r"(?:confidence |, )(\d{1,3})\b", e["title"])
    prio = 3
    ready = e.get("level") == "success"                 # READY: price in the zone with confirmation, no news hold
    if s.get("enabled", True) and m:
        conf = int(m.group(1))
        prio = 5 if conf >= s["urgent_from"] else 4 if conf >= s["high_from"] else 3 if conf >= s["quiet_below"] else 2
    if prio == 5 and not ready:
        prio = 4                    # urgent means READY: a setup price has not reached yet is worth a look, not an alarm
    if ready:
        prio = max(prio, 4)
    return prio


def build(e, c):
    title, text = e["title"], e.get("text") or ""
    low = e["title"].lower()
    if c["detail"] == "minimal":     # keep symbols and amounts out of the push text
        title, text = _TITLES.get(e["kind"], "Bot event"), ""
    if e["level"] == "error" or "liquidation" in low or (e["kind"] == "news" and " now" in low):
        prio = 5
    elif e["level"] == "warning":
        prio = 4
    else:
        prio = 3
    tags = [{"success": "white_check_mark", "warning": "warning",
             "error": "rotating_light"}.get(e["level"], "information_source")]
    if e["kind"] == "news":
        tags = ["newspaper", "warning"]
    elif e["kind"] == "digest":
        tags = ["bar_chart"]
        prio = 2                                    # informational: no sound
    elif e["kind"] == "setup":
        trend = "chart_with_downwards_trend" if " SHORT" in e["title"] else "chart_with_upwards_trend"
        prio = setup_priority(e, c)
        tags = (["rotating_light", trend] if prio == 5 else ["star", trend] if prio == 4 else [trend])
    elif "halted" in low:
        tags = ["octagonal_sign"]
    elif "resumed" in low:
        tags = ["arrow_forward"]
    return {"title": title[:120],
            "message": (text or "Open Trade Companion for details.")[:1500 if e["kind"] == "digest" else 400],
            "priority": prio, "tags": tags}


class Refused(RuntimeError):
    """A provider answered but said no. pause = seconds to leave it alone."""
    def __init__(self, msg, pause=60):
        super().__init__(msg)
        self.pause = pause


async def _ntfy(body, c):
    headers = {"Authorization": "Bearer " + c["token"]} if c["token"] else {}
    async with httpx.AsyncClient(timeout=10) as cl:
        r = await cl.post(c["server"], json=body, headers=headers)
    if r.status_code >= 300:
        txt = r.text[:160]
        if r.status_code == 429 and ("daily" in txt.lower() or "42908" in txt or "quota" in txt.lower()):
            raise Refused(f"ntfy daily message quota reached for this server's IP (resets 00:00 UTC): {txt}", _next_midnight_utc() - time.time())
        if r.status_code == 429:
            raise Refused(f"ntfy rate limit: {txt}", 120)
        raise Refused(f"ntfy {r.status_code}: {txt}", 300 if r.status_code in (401, 403) else 60)


def _tg_text(body):
    prio = body.get("priority", 3)
    tags = body.get("tags") or []
    icon = {5: "\U0001F6A8", 4: "\u2B50", 3: "\U0001F514"}.get(prio, "\U0001F515")
    if "chart_with_upwards_trend" in tags:
        icon += "\U0001F4C8"
    elif "chart_with_downwards_trend" in tags:
        icon += "\U0001F4C9"
    return f"{icon} <b>{html.escape(str(body.get('title', '')))}</b>\n{html.escape(str(body.get('message', '')))}"[:4000]


async def _telegram(body, c):
    payload = {"chat_id": c["tg_chat"], "text": _tg_text(body), "parse_mode": "HTML", "disable_web_page_preview": True,
               "disable_notification": body.get("priority", 3) <= 2}          # priority 1-2 arrive silently
    async with httpx.AsyncClient(timeout=15) as cl:
        r = await cl.post(f"{c['tg_api']}/bot{c['tg_token']}/sendMessage", json=payload)
    if r.status_code >= 300:
        wait = 30
        try:
            wait = int((r.json().get("parameters") or {}).get("retry_after", 30))
        except Exception:
            pass
        raise Refused(f"telegram {r.status_code}: {r.text[:120]}", wait if r.status_code == 429 else (600 if r.status_code in (400, 401, 403, 404) else 60))


_SENDERS = {"ntfy": _ntfy, "telegram": _telegram}


def _order(c, prio, h, now):
    """Providers to try, in order, for one message."""
    route = c["route"]
    avail = [p for p in PROVIDERS if configured(p, c)]
    if route in ("ntfy", "telegram"):
        lst = [p for p in avail if p == route]
    else:
        lst = avail
    if route == "auto" and "ntfy" in lst and "telegram" in lst and c["budget"] and "ntfy.sh" in c["server"] \
            and prio < 4 and _sent_today(h, "ntfy", now) >= c["budget"]:
        lst = ["telegram"]                    # close to the free ntfy.sh quota: keep the last messages for important alerts
    return [p for p in lst if h[p]["paused_until"] <= now] if lst else []


async def deliver(body, c=None, now=None):
    """Send one push through the configured route. Raises only if every provider failed or none is available."""
    c = c or cfg()
    now = now or time.time()
    _, h = _health()
    order = _order(c, body.get("priority", 3), h, now)
    if not order:
        why = [f"{p}: {h[p]['error'] or 'not configured'}" for p in PROVIDERS if c["route"] in ("auto", "both", p)]
        raise RuntimeError("no push provider available (" + "; ".join(why) + ")")
    errors, ok = [], False
    for p in order:
        b = dict(body, topic=c["topic"]) if p == "ntfy" else body
        try:
            await _SENDERS[p](b, c)
            _mark_ok(p, now)
            ok = True
            if c["route"] != "both":
                break
        except Refused as e:
            _mark_fail(p, e, e.pause, now)
            errors.append(str(e))
        except Exception as e:
            _mark_fail(p, e, 60, now)
            errors.append(f"{p}: {e}")
    if not ok:
        raise RuntimeError("; ".join(errors))


async def _post(body, c):
    await deliver(body, c)


async def send_test(priority=3, provider=None):
    """A test push. provider = ntfy or telegram sends through that one only, ignoring pauses (to see the real error)."""
    c = cfg()
    priority = max(1, min(5, int(priority)))
    names = {1: "minimum", 2: "quiet", 3: "normal", 4: "high", 5: "URGENT"}
    body = {"title": f"Trade Companion test: {names[priority]} alert",
            "message": f"Priority {priority}. Give this level its own sound in the ntfy app (Android notification channel).",
            "priority": priority, "tags": ["white_check_mark"]}
    if provider:
        if provider not in PROVIDERS:
            raise RuntimeError("provider must be ntfy or telegram")
        if not configured(provider, c):
            raise RuntimeError(("NTFY_TOPIC" if provider == "ntfy" else "TG_BOT_TOKEN and TG_CHAT_ID") + " is not set in backend/.env")
        try:
            await _SENDERS[provider](dict(body, topic=c["topic"]) if provider == "ntfy" else body, c)
        except Refused as e:
            _mark_fail(provider, e, e.pause)
            raise
        _mark_ok(provider)
        return
    if not enabled(c):
        raise RuntimeError("Push is not configured (set NTFY_TOPIC, or TG_BOT_TOKEN and TG_CHAT_ID, in backend/.env)")
    await deliver(body, c)


def _load_last():
    try:
        return int(json.loads(STATE.read_text())["last"])
    except Exception:
        return None


def _save_last(n):
    s = _state()
    s["last"] = n
    _save_state(s)


async def run():
    await asyncio.sleep(3)
    last = _load_last()
    if last is None:              # first start: do not replay old history
        last = events.last_id()
        _save_last(last)
    fail_since = None
    while True:
        rows = []
        try:
            rows = events.since(last, 50)
            if rows:
                c = cfg()
                todo = [e for e in rows if enabled(c) and should_push(e, c)]
                if len(todo) > 5:  # a burst: send four, then one summary
                    for e in todo[:4]:
                        await _post(policy(build(e, c), e), c)
                        await asyncio.sleep(0.3)
                    await deliver({"title": f"{len(todo) - 4} more events",
                                   "message": "Open Trade Companion > Activity to see them.",
                                   "priority": 3, "tags": ["information_source"]}, c)
                    last = rows[-1]["id"]
                    _save_last(last)
                else:
                    for e in rows:
                        if enabled(c) and should_push(e, c):
                            await _post(policy(build(e, c), e), c)
                            await asyncio.sleep(0.3)
                        last = e["id"]
                        _save_last(last)
            fail_since = None
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            fail_since = fail_since or time.time()
            print("push error:", ex)
            if time.time() - fail_since > 120 and rows:   # give up on a batch that keeps failing
                last = rows[-1]["id"]
                _save_last(last)
                fail_since = None
            await asyncio.sleep(5)
            continue
        await asyncio.sleep(1)
