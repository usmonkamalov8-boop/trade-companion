"""Background watcher: turns changes on Binance / systemd / control.json into activity events."""
import asyncio, json
from . import bot, events, config as C

known = {"halted": None, "profiles": None}   # what the API last wrote; used to spot outside edits
_last = {"service": None, "positions": None, "api_ok": None}
_warned = set()
_tasks = set()


def sync_known():
    st = bot.load()
    known["halted"] = st["halted"]
    known["profiles"] = json.dumps(st["profiles"], sort_keys=True)


def _px(x):
    return f"{x:,.1f}" if abs(x) >= 1000 else f"{x:,.4f}".rstrip("0").rstrip(".")


async def _service_step():
    st = await asyncio.to_thread(bot.service_state)
    prev = _last["service"]
    if prev is not None and st != prev:
        level = "success" if st == "active" else ("error" if st == "failed" else "warning")
        events.add("service", f"Bot service {st}", f"{C.BOT_SERVICE}: {prev} -> {st}", level)
    _last["service"] = st


def _control_step():
    """Report changes made to control.json by something other than the API."""
    st = bot.load()
    if known["halted"] is None:
        sync_known()
        return
    if st["halted"] != known["halted"]:
        events.add("command", "Bot halted" if st["halted"] else "Bot resumed",
                   "Changed outside the app (control.json).", "warning" if st["halted"] else "success")
    now_profiles = json.dumps(st["profiles"], sort_keys=True)
    if now_profiles != known["profiles"]:
        old = json.loads(known["profiles"]) if known["profiles"] else {}
        for name, cfg in st["profiles"].items():
            if cfg != old.get(name):
                events.add("profile", f"Profile {name} changed", "Changed outside the app (control.json).", "info")
    sync_known()


async def _closed(sym, old):
    await asyncio.sleep(4)  # give Binance a moment to book the realized PnL
    try:
        pnl = await bot.realized_recent(sym, 15)
    except Exception:
        pnl = None
    text = f"{old['side']} {old['qty']:g} @ {_px(old['entry'])}"
    if pnl is not None:
        text += f", realized {pnl:+.2f} USDT"
    level = "info" if pnl is None else ("success" if pnl >= 0 else "warning")
    events.add("position", f"{sym} closed", text, level)


async def _positions_step():
    """Disabled: this used to poll Binance directly every 5s on the OLD bot's own key, on top of whatever
    tcexec (the execution engine) already polls on its own connection - pure redundant load on the same IP,
    and part of what drove Binance's 429 ("too many requests"). tcexec now reports positions and
    open/close/liquidation events on its own schedule (see futures.py's reconcile(), which now also carries
    the liquidation-proximity warning this used to do here). Kept as a no-op, not deleted, so run()'s loop
    doesn't need restructuring."""
    return


async def run():
    await asyncio.sleep(2)
    events.add("system", "Companion backend started", "", "info")
    sync_known()
    while True:
        try:
            await _service_step()
            _control_step()
            await _positions_step()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("watcher error:", e)
        await asyncio.sleep(5)
