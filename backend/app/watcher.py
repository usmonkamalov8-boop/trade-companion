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
    if not (C.BINANCE_KEY and C.BINANCE_SECRET):
        return
    try:
        pos = await bot.positions()
    except Exception as e:
        if _last["api_ok"] is not False:
            events.add("warning", "Binance API problem", str(e)[:200], "error")
        _last["api_ok"] = False
        return
    if _last["api_ok"] is False:
        events.add("system", "Binance connection restored", "", "success")
    _last["api_ok"] = True

    cur = {p["symbol"]: p for p in pos}
    prev = _last["positions"]
    _last["positions"] = cur
    if prev is None:          # first successful poll: just remember what is open
        return
    for sym, p in cur.items():
        old = prev.get(sym)
        if old is None:
            events.add("position", f"{sym} {p['side']} opened",
                       f"qty {p['qty']:g} @ {_px(p['entry'])}", "success")
        elif old["side"] != p["side"]:
            events.add("position", f"{sym} flipped to {p['side']}",
                       f"qty {p['qty']:g} @ {_px(p['entry'])}", "info")
        elif abs(p["qty"] - old["qty"]) > old["qty"] * 0.001:
            events.add("position", f"{sym} size changed",
                       f"{old['qty']:g} -> {p['qty']:g} (entry {_px(p['entry'])})", "info")
    for sym, old in prev.items():
        if sym not in cur:
            t = asyncio.create_task(_closed(sym, old))
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
    for sym, p in cur.items():
        if p["liq"] > 0 and p["mark"] > 0:
            dist = abs(p["liq"] - p["mark"]) / p["mark"] * 100
            if dist < 5 and sym not in _warned:
                _warned.add(sym)
                events.add("warning", f"{sym}: close to liquidation",
                           f"Price is {dist:.1f}% from the liquidation level ({_px(p['liq'])}).", "warning")
            elif dist > 8:
                _warned.discard(sym)


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
