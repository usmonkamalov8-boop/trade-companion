"""The user's time zone in one place. Alerts, reports, market hours and the economic calendar all
format times through this module, so they follow the zone chosen in Settings.

Settings > Time zone is either "auto" (the phone reports its UTC offset whenever the app opens) or an
IANA name such as Asia/Dubai. Market rules stay in New York time (forex closes Friday 17:00 and reopens
Sunday 17:00 there, ICT kill zones are New York hours); this module converts them for display."""
import os, time
from datetime import datetime, timedelta, timezone, tzinfo
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


class _NyRules(tzinfo):
    """America/New_York without a tz database: US daylight saving rules (second Sunday of March 02:00 to the first
    Sunday of November 02:00). Only used when tzdata is missing, so the forex weekend guard stays correct."""

    def _range(self, year):
        m = datetime(year, 3, 8)
        n = datetime(year, 11, 1)
        start = (m + timedelta(days=(6 - m.weekday()) % 7)).replace(hour=2)
        end = (n + timedelta(days=(6 - n.weekday()) % 7)).replace(hour=2)
        return start, end                       # local wall-clock times

    def utcoffset(self, dt):
        start, end = self._range(dt.year)
        naive = dt.replace(tzinfo=None)
        if end - timedelta(hours=1) <= naive < end:          # the repeated hour in November: fold=1 is the second pass
            return timedelta(hours=-5) if dt.fold else timedelta(hours=-4)
        return timedelta(hours=-4) if start <= naive < end else timedelta(hours=-5)

    def dst(self, dt):
        return timedelta(hours=1) if self.utcoffset(dt) == timedelta(hours=-4) else timedelta(0)

    def tzname(self, dt):
        return "EDT" if self.dst(dt) else "EST"

    def fromutc(self, dt):
        start, end = self._range(dt.year)
        naive = dt.replace(tzinfo=None)
        edt = (start + timedelta(hours=5)) <= naive < (end + timedelta(hours=4))      # the transitions, in UTC
        res = naive + timedelta(hours=-4 if edt else -5)
        fold = 1 if (not edt and end - timedelta(hours=1) <= res < end) else 0
        return res.replace(tzinfo=self, fold=fold)


def ny_zone():
    return _named("America/New_York") or _NyRules()


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


def tzdata_ok():
    return _named("America/New_York") is not None


def info():
    ny, z = ny_zone(), zone()
    now = datetime.now(z)
    return {"tzdata_ok": tzdata_ok(), "zone": zone_title(), "label": label(now), "offset_min": offset_now(), "now": now.strftime("%H:%M"),
            "date": now.strftime("%a %d %b %Y"), "ny_now": datetime.now(ny).strftime("%H:%M"),
            "sessions": sessions(), "forex_hours": market_hours()}
