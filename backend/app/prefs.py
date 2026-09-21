"""Server-side preferences, edited from the app's Settings. Environment variables only
provide the first-run defaults; after that prefs.json is the source of truth."""
import copy, json, os, time
from . import config as C

FILE = C.BASE / "prefs.json"
KINDS = ["position", "trade", "command", "service", "warning", "news", "risk", "profile", "system"]
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
MODULES = ["structure", "ob", "fvg", "sd", "sr", "fib", "trend", "liquidity", "volume", "ict", "poi"]
STYLES = ["scalp", "intraday", "swing"]
LEADS = [0, 5, 15, 30, 60, 120]

_cache = {"mtime": None, "data": None}


def defaults():
    on = {k.strip() for k in os.getenv("PUSH_KINDS", "position,trade,command,service,warning,news").split(",")}
    imp = os.getenv("CAL_IMPACT", "High").strip().lower()
    cur = [c.strip().upper() for c in os.getenv("CAL_CURRENCIES", "USD,EUR,GBP,JPY").split(",") if c.strip()]
    leads = [int(x) for x in os.getenv("CAL_LEADS", "60,15,0").split(",") if x.strip().isdigit()]
    return {
        "push": {"enabled": os.getenv("PUSH_ENABLED", "1").strip() != "0",
                 "detail": "minimal" if os.getenv("PUSH_DETAIL", "full").strip().lower() == "minimal" else "full",
                 "kinds": {k: k in on for k in KINDS}},
        "calendar": {"alerts": os.getenv("CAL_ALERTS", "1").strip() != "0",
                     "impact": "medium" if imp == "medium" else "high",
                     "currencies": [c for c in cur if c in CURRENCIES] or ["USD", "EUR", "GBP", "JPY"],
                     "leads": sorted({x for x in leads if x in LEADS} or {60, 15, 0}, reverse=True)},
        "analyst": {"style": "intraday", "modules": {m: True for m in MODULES}, "news_scoring": True, "journal": True},
    }


def _merge(base, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def get():
    try:
        mt = FILE.stat().st_mtime
    except OSError:
        mt = None
    if _cache["data"] is not None and _cache["mtime"] == mt:
        return _cache["data"]
    data = defaults()
    if mt is not None:
        try:
            _merge(data, _clean(json.loads(FILE.read_text())))
        except Exception:
            pass
    _cache["data"], _cache["mtime"] = data, mt
    return data


def _clean(p):
    """Keep only valid keys and values."""
    out = {}
    push = p.get("push") or {}
    if isinstance(push, dict):
        o = {}
        if isinstance(push.get("enabled"), bool):
            o["enabled"] = push["enabled"]
        if push.get("detail") in ("full", "minimal"):
            o["detail"] = push["detail"]
        if isinstance(push.get("kinds"), dict):
            o["kinds"] = {k: bool(v) for k, v in push["kinds"].items() if k in KINDS}
        out["push"] = o
    cal = p.get("calendar") or {}
    if isinstance(cal, dict):
        o = {}
        if isinstance(cal.get("alerts"), bool):
            o["alerts"] = cal["alerts"]
        if cal.get("impact") in ("high", "medium"):
            o["impact"] = cal["impact"]
        if isinstance(cal.get("currencies"), list):
            cur = [str(c).upper() for c in cal["currencies"] if str(c).upper() in CURRENCIES]
            if cur:
                o["currencies"] = cur
        if isinstance(cal.get("leads"), list):
            ld = sorted({int(x) for x in cal["leads"] if isinstance(x, (int, float)) and int(x) in LEADS}, reverse=True)
            if ld:
                o["leads"] = ld
        out["calendar"] = o
    an = p.get("analyst") or {}
    if isinstance(an, dict):
        o = {}
        if an.get("style") in STYLES:
            o["style"] = an["style"]
        if isinstance(an.get("modules"), dict):
            o["modules"] = {k: bool(v) for k, v in an["modules"].items() if k in MODULES}
        for k in ("news_scoring", "journal"):
            if isinstance(an.get(k), bool):
                o[k] = an[k]
        out["analyst"] = o
    return out


def save(patch):
    """Deep-merge a validated patch into the stored preferences and return the result."""
    try:
        cur = json.loads(FILE.read_text())
    except Exception:
        cur = {}
    _merge(cur, _clean(patch))
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2))
    os.replace(tmp, FILE)
    _cache["data"] = None
    return copy.deepcopy(get())
