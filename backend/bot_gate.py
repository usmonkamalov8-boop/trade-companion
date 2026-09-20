# Copy this file into your bot folder (next to the crypto_bot code) and import it.
#
#   import bot_gate
#   if bot_gate.halted():                 # before opening any NEW trade
#       return
#   prof = bot_gate.cfg("hier")           # or "scalp"
#   if not prof.get("enabled", True):
#       return
#   bot_gate.event("trade", "Trade opened: BTCUSDT", "hier long", "success")   # shows in the app's Activity feed
#
# The app writes control.json; the bot only reads it.
# If the files live somewhere else, set the CONTROL_FILE environment variable.
import json, os, sqlite3, time

_CANDIDATES = [
    os.getenv("CONTROL_FILE", ""),
    os.path.expanduser("~/trade_companion/backend/control.json"),
    os.path.expanduser("~/companion/control.json"),
]
_SCHEMA = ("CREATE TABLE IF NOT EXISTS events ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, level TEXT, title TEXT, text TEXT)")


def _state():
    for p in _CANDIDATES:
        if not p:
            continue
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def halted():
    return bool(_state().get("halted", False))


def cfg(profile):
    return _state().get("profiles", {}).get(profile, {})


def _dir():
    for p in _CANDIDATES:
        if p and os.path.exists(p):
            return os.path.dirname(p)
    return os.path.expanduser("~/trade_companion/backend")


def event(kind, title, text="", level="info"):
    """Add an entry to the app's Activity feed. Never raises."""
    try:
        con = sqlite3.connect(os.path.join(_dir(), "events.db"), timeout=5)
        try:
            con.execute(_SCHEMA)
            con.execute("INSERT INTO events (ts, kind, level, title, text) VALUES (?,?,?,?,?)",
                        (time.time(), str(kind), str(level), str(title)[:120], str(text)[:400]))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
