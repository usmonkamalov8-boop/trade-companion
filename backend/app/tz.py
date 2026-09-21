"""The user's time zone in one place. Alerts, reports, market hours and the economic calendar all
format times through this module, so they follow the zone chosen in Settings.

Settings > Time zone is either "auto" (the phone reports its UTC offset whenever the app opens) or an
IANA name such as Asia/Dubai. Market rules stay in New York time (forex closes Friday 17:00 and reopens
Sunday 17:00 there, ICT kill zones are New York hours); this module converts them for display."""
import os, time
from datetime import datetime, timedelta, timezone
from . import prefs

try:
    from zoneinfo import ZoneInfo
except Exception:                                   # pragma: no cover
    ZoneInfo = None


def _named(name):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def valid(name):
    return name == "auto" or _named(name) is not None


def ny_zone():
    return _named("America/New_York") or timezone(timedelta(hours=-5))


def zone():
    g = prefs.get()["general"]
    name = g.get("timezone", "auto")
    if name != "auto":
        z = _named(name)
        if z:
            return z
    off = g.get("tz_offset_min")
    if name == "auto" and isinstance(off, int):
        return timezone(timedelta(minutes=off))
    env = os.getenv("CAL_TZ", "").strip()
    if env and env.upper() != "UTC":
        z = _named(env)
        if z:
            return z
    return timezone.utc


def label(d):
    """'UTC+4', 'UTC+5:30', 'UTC' for an aware datetime."""
    off = d.utcoffset().total_seconds() / 60 if d.utcoffset() else 0
    if off == 0:
        return "UTC"
    sign, off = ("+" if off > 0 else "-"), abs(int(off))
    h, m = divmod(off, 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def local(ts):
    d = datetime.fromtimestamp(ts, zone())
    return d, label(d)


def label_now():
    return label(datetime.now(zone()))


def hm(ts):
    return local(ts)[0].strftime("%H:%M")


def day(ts):
    return local(ts)[0].strftime("%a %d %b")


def stamp(ts=None):
    d, lab = local(ts or time.time())
    return f"{d:%d %b %Y %H:%M} {lab}"


def offset_now():
    d = datetime.now(zone())
    return int(d.utcoffset().total_seconds() // 60) if d.utcoffset() else 0


def zone_title():
    g = prefs.get()["general"]
    return "Automatic (this phone)" if g.get("timezone", "auto") == "auto" else g["timezone"]


def _hmd(d, ref):
    """HH:MM with a +1 / -1 day marker relative to the reference date."""
    diff = (d.date() - ref).days
    return d.strftime("%H:%M") + (f" ({diff:+d}d)" if diff else "")


def sessions(ts=None):
    """ICT sessions (defined in New York time) converted to the user's time zone, for the current New York day."""
    ny, z = ny_zone(), zone()
    now = datetime.fromtimestamp(ts or time.time(), ny)
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ref = now.astimezone(z).date()
    wins = (("Asian range", -4, 0), ("London kill zone", 2, 5), ("New York AM kill zone", 7, 10), ("New York PM session", 13.5, 16))
    out = []
    for name, a, b in wins:
        la = (d0 + timedelta(hours=a)).astimezone(z)
        lb = (d0 + timedelta(hours=b)).astimezone(z)
        out.append({"name": name, "start": _hmd(la, ref), "end": _hmd(lb, ref)})
    return out


def market_hours(ts=None):
    """Weekly spot forex and gold hours (Sunday 17:00 to Friday 17:00 New York) in the user's time zone."""
    ny, z = ny_zone(), zone()
    now = datetime.fromtimestamp(ts or time.time(), ny)
    d0 = (now - timedelta(days=(now.weekday() + 1) % 7)).replace(hour=17, minute=0, second=0, microsecond=0)
    lo, lc = d0.astimezone(z), (d0 + timedelta(days=5)).astimezone(z)
    return f"opens {lo:%a %H:%M}, closes {lc:%a %H:%M} ({label(lo)})"


def info():
    ny, z = ny_zone(), zone()
    now = datetime.now(z)
    return {"zone": zone_title(), "label": label(now), "offset_min": offset_now(), "now": now.strftime("%H:%M"),
            "date": now.strftime("%a %d %b %Y"), "ny_now": datetime.now(ny).strftime("%H:%M"),
            "sessions": sessions(), "forex_hours": market_hours()}
