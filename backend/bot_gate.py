# Copy this file into your bot folder (next to the crypto_bot code) and import it.
#
#   import bot_gate
#   if bot_gate.halted():                 # before opening any NEW trade
#       return
#   prof = bot_gate.cfg("hier")           # or "scalp"
#   if not prof.get("enabled", True):
#       return
#   risk = prof.get("risk_pct", 1.0)      # % risk per trade set from the app
#
# The app writes control.json; the bot only reads it.
# If the file lives somewhere else, set the CONTROL_FILE environment variable.
import json, os

_CANDIDATES = [
    os.getenv("CONTROL_FILE", ""),
    os.path.expanduser("~/trade_companion/backend/control.json"),
    os.path.expanduser("~/companion/control.json"),
]


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
