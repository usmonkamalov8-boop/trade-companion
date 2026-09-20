"""Background push notifications through ntfy (https://ntfy.sh or your own ntfy server).

Every new row in the activity log (from the API, the watcher, the calendar or the bot) whose
category is enabled in the app's Settings is sent to your private topic. The ntfy Android app
shows the banner even when Trade Companion is closed."""
import asyncio, json, os, time
import httpx
from . import events, prefs, config as C

STATE = C.BASE / "push_state.json"
_TITLES = {"position": "Position update", "trade": "Trade update", "command": "Bot control action",
           "service": "Bot service change", "warning": "Alert", "news": "News alert",
           "risk": "Risk change", "profile": "Profile change", "system": "System message"}


def cfg():
    p = prefs.get()["push"]
    return {
        "topic": os.getenv("NTFY_TOPIC", "").strip(),
        "server": os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/"),
        "token": os.getenv("NTFY_TOKEN", "").strip(),
        "detail": p["detail"],
        "kinds": p["kinds"],
        "on": p["enabled"],
    }


def enabled(c=None):
    c = c or cfg()
    return c["on"] and bool(c["topic"])


def info():
    c = cfg()
    return {"enabled": enabled(c), "configured": bool(c["topic"]), "server": c["server"], "topic": c["topic"],
            "detail": c["detail"]}


def should_push(e, c):
    return bool(c["kinds"].get(e["kind"], False)) or e["level"] == "error"


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
    elif "halted" in low:
        tags = ["octagonal_sign"]
    elif "resumed" in low:
        tags = ["arrow_forward"]
    return {"topic": c["topic"], "title": title[:120],
            "message": (text or "Open Trade Companion for details.")[:400],
            "priority": prio, "tags": tags}


async def _post(body, c):
    headers = {"Authorization": "Bearer " + c["token"]} if c["token"] else {}
    async with httpx.AsyncClient(timeout=10) as cl:
        r = await cl.post(c["server"], json=body, headers=headers)
    if r.status_code >= 300:
        raise RuntimeError(f"ntfy {r.status_code}: {r.text[:120]}")


async def send_test():
    c = cfg()
    if not c["topic"]:
        raise RuntimeError("Push is not configured (set NTFY_TOPIC in backend/.env)")
    await _post({"topic": c["topic"], "title": "Trade Companion test",
                 "message": "If you see this with the app closed, background push works.",
                 "priority": 3, "tags": ["white_check_mark"]}, c)


def _load_last():
    try:
        return int(json.loads(STATE.read_text())["last"])
    except Exception:
        return None


def _save_last(n):
    STATE.write_text(json.dumps({"last": n}))


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
                        await _post(build(e, c), c)
                        await asyncio.sleep(0.3)
                    await _post({"topic": c["topic"], "title": f"{len(todo) - 4} more events",
                                 "message": "Open Trade Companion > Activity to see them.",
                                 "priority": 3, "tags": ["information_source"]}, c)
                    last = rows[-1]["id"]
                    _save_last(last)
                else:
                    for e in rows:
                        if enabled(c) and should_push(e, c):
                            await _post(build(e, c), c)
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
