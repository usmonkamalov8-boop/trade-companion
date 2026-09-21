"""Server-side preferences, edited from the app's Settings. Environment variables only
provide the first-run defaults; after that prefs.json is the source of truth."""
import copy, json, os, time
from . import config as C

FILE = C.BASE / "prefs.json"
KINDS = ["position", "trade", "command", "service", "warning", "news", "setup", "risk", "profile", "system"]
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
MODULES = ["structure", "ob", "fvg", "sd", "sr", "fib", "trend", "liquidity", "volume", "ict", "poi"]
STYLES = ["scalp", "intraday", "swing"]
LEADS = [0, 5, 15, 30, 60, 120]
MARKETS = ["crypto", "forex"]
SCAN_SECONDS = [60, 120, 300]

_cache = {"mtime": None, "data": None}


def _env_tz():
    """CAL_TZ from .env (older installs) becomes the starting time zone; otherwise follow the phone."""
    z = os.getenv("CAL_TZ", "").strip()
    if z and z.upper() != "UTC":
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(z)
            return z
        except Exception:
            pass
    return "auto"


def defaults():
    on = {k.strip() for k in os.getenv("PUSH_KINDS", "position,trade,command,service,warning,news").split(",")}
    imp = os.getenv("CAL_IMPACT", "High").strip().lower()
    cur = [c.strip().upper() for c in os.getenv("CAL_CURRENCIES", "USD,EUR,GBP,JPY").split(",") if c.strip()]
    leads = [int(x) for x in os.getenv("CAL_LEADS", "60,15,0").split(",") if x.strip().isdigit()]
    return {
        "push": {"enabled": os.getenv("PUSH_ENABLED", "1").strip() != "0",
                 "detail": "minimal" if os.getenv("PUSH_DETAIL", "full").strip().lower() == "minimal" else "full",
                 "kinds": {k: (k in on or k == "setup") for k in KINDS}},
        "calendar": {"alerts": os.getenv("CAL_ALERTS", "1").strip() != "0",
                     "impact": "medium" if imp == "medium" else "high",
                     "currencies": [c for c in cur if c in CURRENCIES] or ["USD", "EUR", "GBP", "JPY"],
                     "leads": sorted({x for x in leads if x in LEADS} or {60, 15, 0}, reverse=True)},
        "general": {"timezone": _env_tz(), "tz_offset_min": None},
        "setups": {"enabled": True, "min_conf": 70, "styles": list(STYLES), "markets": list(MARKETS),
                   "on_zone": True, "scan_seconds": 60, "max_dist_atr": 3, "confirm_close": False,
                   "sound": {"enabled": True, "urgent_from": 85, "high_from": 70, "quiet_below": 50,
                             "urgent_needs_ready": True}},
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
    gen = p.get("general") or {}
    if isinstance(gen, dict):
        o = {}
        tzn = gen.get("timezone")
        if isinstance(tzn, str) and 0 < len(tzn) < 64:
            if tzn == "auto":
                o["timezone"] = "auto"
            else:
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(tzn)
                    o["timezone"] = tzn
                except Exception:
                    pass
        off = gen.get("tz_offset_min")
        if isinstance(off, (int, float)) and not isinstance(off, bool) and -840 <= int(off) <= 840:
            o["tz_offset_min"] = int(off)
        out["general"] = o
    st = p.get("setups") or {}
    if isinstance(st, dict):
        o = {}
        for k in ("enabled", "on_zone", "confirm_close"):
            if isinstance(st.get(k), bool):
                o[k] = st[k]
        if isinstance(st.get("max_dist_atr"), (int, float)) and not isinstance(st.get("max_dist_atr"), bool):
            o["max_dist_atr"] = max(0, min(20, int(st["max_dist_atr"])))
        if isinstance(st.get("min_conf"), (int, float)) and not isinstance(st.get("min_conf"), bool):
            o["min_conf"] = max(0, min(100, int(st["min_conf"])))
        if isinstance(st.get("styles"), list):
            sl = [x for x in STYLES if x in st["styles"]]
            if sl:
                o["styles"] = sl
        if isinstance(st.get("markets"), list):
            ml = [x for x in MARKETS if x in st["markets"]]
            if ml:
                o["markets"] = ml
        if st.get("scan_seconds") in SCAN_SECONDS:
            o["scan_seconds"] = st["scan_seconds"]
        sd = st.get("sound")
        if isinstance(sd, dict):
            so = {}
            for k in ("enabled", "urgent_needs_ready"):
                if isinstance(sd.get(k), bool):
                    so[k] = sd[k]
            for k in ("urgent_from", "high_from", "quiet_below"):
                if isinstance(sd.get(k), (int, float)) and not isinstance(sd.get(k), bool):
                    so[k] = max(0, min(100, int(sd[k])))
            o["sound"] = so
        out["setups"] = o
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
