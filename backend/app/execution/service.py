"""tcexec: the execution service. Runs beside the API (127.0.0.1 only) and owns the exchange keys.

EXEC_ENV=paper (default)  real prices, simulated money: nothing touches your Binance account
EXEC_ENV=live             real orders; requires the arm step (tc_exec.py arm) which also checks the key's permissions
EXEC_ENV=testnet          Binance testnet
The app talks to the API, which forwards /api/trade/* here with a shared token."""
import asyncio, json, os, secrets, time
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

from .. import config as C
from . import futures as F, grid as G, notify as N, signals as S, store
from .binance import BinanceError, Client, D

try:                                              # exec.env holds the exchange keys and the internal token
    from dotenv import load_dotenv
    load_dotenv(C.BASE / "exec.env", override=True)
except Exception:
    pass


def env(k, d=""):
    return os.getenv(k, d).strip()


class Runtime:
    def __init__(self):
        self.env = env("EXEC_ENV", "paper").lower()
        self.client = self.real = self.fut = self.grid = self.notifier = None
        self.stop = asyncio.Event()
        self.tasks = []
        self.started = time.time()
        self.blocked = None
        self.last = {}                            # loop name -> last successful run
        self.restrictions = None

    # ------------------------------------------------------------------ construction
    async def build(self):
        if self.env == "paper":
            from .sim import Sim
            self.real = Client(env="live")
            fut = (await self.real.call("fut", "GET", "/fapi/v1/exchangeInfo", signed=False))["symbols"]
            spot = (await self.real.call("spot", "GET", "/api/v3/exchangeInfo", signed=False))["symbols"]
            bal = env("PAPER_BALANCE", "10000")
            sim = Sim(fut_wallet=bal, spot_usdt=bal)
            sim.load_info(fut, spot)
            self.client = Client(env="paper", sim=sim)
            self.sim = sim
        else:
            self.client = Client(env("EXEC_BINANCE_KEY"), env("EXEC_BINANCE_SECRET"), env="testnet" if self.env == "testnet" else "live")
            await self.client.sync_time()
        tg = env("TG_BOT_TOKEN"), env("TG_CHAT_ID")
        self.notifier = N.Notifier(tg[0], tg[1], env("TG_ALLOWED_USER_ID") or None, env("TG_API", "https://api.telegram.org")) if all(tg) else N.NullNotifier()
        self.fut = F.Futures(self.client, self.notifier, env=self.env if self.env != "paper" else "paper")
        self.grid = G.GridEngine(self.client, self.notifier)

    async def check_mode(self):
        """One-way position mode is required (the engine does not manage hedge-mode positions)."""
        if self.env == "paper":
            return
        try:
            if await self.client.f_position_mode():
                self.blocked = "Binance futures is in Hedge mode. Switch it to One-way mode (Preferences > Position mode) and restart tcexec."
        except BinanceError as e:
            self.blocked = f"could not read the futures position mode: {e.msg}"

    # ------------------------------------------------------------------ switching paper/live/testnet from the app, without a service restart
    def _persist_env(self, value):
        """Write EXEC_ENV into exec.env so a later service restart keeps this choice instead of reverting to the old one."""
        p = C.BASE / "exec.env"
        lines, found = [], False
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("EXEC_ENV="):
                    lines.append(f"EXEC_ENV={value}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"EXEC_ENV={value}")
        p.write_text("\n".join(lines) + "\n")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    async def switch_env(self, mode, confirm=False, allow_any_ip=False):
        """Tear the current client/engines down and rebuild them for a different mode - no systemd restart needed.
        Going TO live needs confirm=true (the app's warning dialog) and a usable key; if the key check fails the
        engine is still left in live mode (armed stays false, so no real order can go out) rather than silently
        reverted, so the error is easy to see and fix. Leaving live always disarms."""
        mode = (mode or "").lower()
        if mode not in ("paper", "live", "testnet"):
            return {"ok": False, "error": "mode must be paper, live or testnet"}
        if mode == self.env:
            return {"ok": True, "unchanged": True, "env": self.env, "armed": bool(store.config().get("armed"))}
        if mode == "live":
            if not confirm:
                return {"ok": False, "error": "switching to live needs confirmation (the app's warning dialog sets this)"}
            if not (env("EXEC_BINANCE_KEY") and env("EXEC_BINANCE_SECRET")):
                return {"ok": False, "error": "no Binance key in exec.env - run tc_exec.py keys on the VPS first"}
        async with self.fut.lock:
            self.stop.set()
            for t in self.tasks:
                t.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.client.close()
            self.stop = asyncio.Event()
            self.blocked = None
            old_env, self.env = self.env, mode
            await self.build()
            await self.check_mode()
            self.start_loops()
        self._persist_env(mode)
        out = {"ok": True, "env": self.env}
        if mode == "live":
            chk = await arm_checks(allow_any_ip)
            store.save_config({"armed": chk["ok"]})
            out.update(armed=chk["ok"], problems=chk["problems"], warnings=chk["warnings"])
        else:
            store.save_config({"armed": False})
            out["armed"] = False
        store.event("warning" if mode == "live" else "info", "env", f"switched from {old_env} to {mode} (armed={out['armed']})")
        await self.notifier.send(f"<b>Trading engine switched to {mode.upper()}</b>" +
                                 (" Armed - real orders can now reach your Binance account." if out["armed"] else
                                  (" Not armed yet: " + "; ".join(out.get("problems", [])) if mode == "live" else "")), retries=2)
        return out

    # ------------------------------------------------------------------ loops
    async def loop(self, name, fn, every):
        while not self.stop.is_set():
            try:
                await fn()
                self.last[name] = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                store.event("warning", "loop", f"{name}: {type(e).__name__}: {str(e)[:200]}")
            try:
                await asyncio.wait_for(self.stop.wait(), every)
            except asyncio.TimeoutError:
                pass

    async def paper_feed(self):
        for mkt, path, table in (("fut", "/fapi/v1/ticker/price", self.sim.prices["fut"]), ("spot", "/api/v3/ticker/price", self.sim.prices["spot"])):
            rows = await self.real.call(mkt, "GET", path, signed=False)
            info = self.sim.fut_info if mkt == "fut" else self.sim.spot_info
            for r in rows:
                if r["symbol"] in info:
                    self.sim.set_price(mkt, r["symbol"], D(r["price"]))

    async def scan_signals(self):
        base, tok = env("COMPANION_URL", "http://127.0.0.1:8000"), env("COMPANION_TOKEN") or C.API_TOKEN
        if not tok:
            return
        await S.scan(self.fut, lambda style: S.fetch_rows(base, tok, style))

    def start_loops(self):
        L = self.loop
        self.tasks = [asyncio.create_task(L("reconcile", self.fut.reconcile, 4)),
                      asyncio.create_task(L("grids", self.grid.tick_all, max(3, store.config()["spot_grid"]["poll_s"]))),
                      asyncio.create_task(L("signals", self.scan_signals, 60)),
                      asyncio.create_task(L("time", self.client.sync_time, 600)),
                      asyncio.create_task(self.notifier.poll(self.on_telegram, self.stop))]
        if self.env == "paper":
            self.tasks.append(asyncio.create_task(L("paper_feed", self.paper_feed, 3)))

    async def shutdown(self):
        self.stop.set()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.close()

    # ------------------------------------------------------------------ telegram: buttons and a few risk-reducing commands
    async def on_telegram(self, kind, d):
        n = self.notifier
        if kind == "callback":
            parts = d["data"].split(":")
            if parts[0] in ("ok", "no") and len(parts) == 3:
                res = await (self.fut.approve(parts[1], "telegram", parts[2]) if parts[0] == "ok" else self.fut.reject(parts[1], "telegram", parts[2]))
                await n.answer(d["cb_id"], "Done" if res.get("ok") else str(res.get("error", "failed"))[:150])
            elif parts[0] == "kf" and len(parts) == 3:
                if parts[1] == "cancel":
                    store.kv_set("killcode:" + parts[2], None)
                    await n.answer(d["cb_id"], "Cancelled")
                    return
                k = store.kv_get("killcode:" + parts[2])
                if not k or k["level"] != parts[1] or time.time() > k["exp"]:
                    await n.answer(d["cb_id"], "That confirmation expired")
                    return
                store.kv_set("killcode:" + parts[2], None)
                await n.answer(d["cb_id"], f"{parts[1]} started")
                await self.kill(parts[1], "telegram")
            return
        cmd = d["text"]
        if cmd in ("/stop",):
            await self.kill("stop", "telegram")
        elif cmd in ("/flatten", "/panic"):
            lvl = cmd[1:]
            code = secrets.token_hex(4)
            store.kv_set("killcode:" + code, {"level": lvl, "exp": time.time() + 90})
            what = "close every position and cancel every order on the futures account" if lvl == "flatten" else "close everything, stop trading and switch the futures profile off"
            await n.send(f"<b>Confirm {lvl.upper()}</b>: this will {what}. Valid for 90 seconds.", buttons=N.kb([(f"Yes, {lvl} now", f"kf:{lvl}:{code}"), ("Cancel", f"kf:cancel:{code}")]))
        elif cmd == "/status":
            await n.send(await self.status_text())
        elif cmd in ("/start", "/help"):
            await n.send("Commands: /status, /stop (no new entries), /flatten (close everything, asks to confirm), /panic (asks to confirm). Trades are only placed from a proposal's Take button.")

    async def kill(self, level, via):
        out = await self.fut.kill(level, via)
        if level in ("flatten", "panic"):                     # grids: orders are cancelled, the coins they hold are kept (selling is your call)
            g = await self.grid.stop_all(f"kill switch {level}", sell=False)
            out["grids_stopped"] = len(g)
        return out

    async def status_text(self):
        try:
            s = await self.fut.snapshot()
        except Exception as e:
            return f"Exchange not reachable: {N.esc(e)}"
        pos = "; ".join(f"{p['symbol']} {p['side']} {p['qty']} ({p['upnl']:+.2f}){'' if p['protected'] else ' NO STOP'}" for p in s["positions"]) or "no positions"
        gs = [g for g in self.grid.summary() if g["status"] == "running"]
        return (f"<b>{self.env.upper()}</b> equity {s['account']['equity']:.2f}, today {s['daily_pnl']:+.2f}\n{N.esc(pos)}\nGrids running: {len(gs)}"
                + ("\nNew entries STOPPED" if s["halted"] else ""))


RT = Runtime()


@asynccontextmanager
async def lifespan(app):
    store.init()
    await RT.build()
    await RT.check_mode()
    RT.start_loops()
    store.event("info", "service", f"tcexec started ({RT.env})")
    yield
    await RT.shutdown()


app = FastAPI(title="Trade Companion execution service", lifespan=lifespan)


def auth(x_exec_token: str = Header(default="")):
    tok = env("EXEC_TOKEN")
    if not tok or not secrets.compare_digest(x_exec_token.encode(), tok.encode()):
        raise HTTPException(401, "bad token")


def guard():
    if RT.blocked:
        raise HTTPException(409, RT.blocked)


R = Depends(auth)


def dumps(o):
    return json.loads(json.dumps(o, default=str))


# ------------------------------------------------------------------ status and configuration
@app.get("/health", dependencies=[R])
async def health():
    cfg = store.config()
    return dumps({"env": RT.env, "armed": bool(cfg["armed"]), "live": RT.env == "live", "halted": RT.fut.halted, "panic": bool(store.kv_get("panic")),
                  "mode": cfg["futures"]["mode"], "blocked": RT.blocked, "uptime_s": int(time.time() - RT.started), "loops": {k: int(time.time() - v) for k, v in RT.last.items()},
                  "telegram": {"configured": RT.notifier.configured, "ok": RT.notifier.ok, "error": RT.notifier.last_error}, "reconcile_error": RT.fut.last_error})


@app.get("/status", dependencies=[R])
async def status():
    out = await health()
    try:
        out["snapshot"] = dumps(await RT.fut.snapshot())
    except BinanceError as e:
        out["snapshot"] = None
        out["exchange_error"] = e.msg
    out["config"] = store.config()
    out["pending"] = store.q("SELECT id, ts, source, symbol, side, intent, expires_ts, price0 FROM proposals WHERE status='pending' AND expires_ts>?", (time.time(),))
    return dumps(out)


@app.get("/config", dependencies=[R])
async def get_config():
    return store.config()


@app.post("/config", dependencies=[R])
async def set_config(patch: dict = Body(...)):
    patch = {k: v for k, v in patch.items() if k != "armed"}           # arming has its own checked endpoint
    before = store.config()
    after = store.save_config(patch)
    store.event("info", "config", f"config changed: {json.dumps(store.clean(patch))[:300]}")
    return after


async def arm_checks(allow_any_ip=False):
    problems, warnings = [], []
    if RT.env != "live":
        problems.append(f"the service runs in {RT.env} mode: set EXEC_ENV=live in exec.env and restart tcexec")
        return {"ok": False, "problems": problems, "warnings": warnings}
    if not (env("EXEC_BINANCE_KEY") and env("EXEC_BINANCE_SECRET")):
        return {"ok": False, "problems": ["no Binance key in exec.env (run tc_exec.py keys)"], "warnings": warnings}
    if RT.blocked:
        problems.append(RT.blocked)
    try:
        r = await RT.client.api_restrictions()
        RT.restrictions = r
        if r.get("enableWithdrawals"):
            problems.append("this API key can WITHDRAW funds: create a key without withdrawal permission")
        if r.get("enableInternalTransfer") or r.get("permitsUniversalTransfer"):
            problems.append("this API key can transfer funds between accounts: turn that permission off")
        if not r.get("ipRestrict"):
            (warnings if allow_any_ip else problems).append("the key is not restricted to your server's IP: restrict it in Binance (API Management), or arm with allow_any_ip")
        if not r.get("enableFutures"):
            warnings.append("Futures trading is not enabled on this key (futures profile will fail)")
        if not r.get("enableSpotAndMarginTrading"):
            warnings.append("Spot trading is not enabled on this key (grid profile will fail)")
        if not r.get("enableReading"):
            problems.append("the key cannot read the account")
    except BinanceError as e:
        problems.append(f"could not check the key's permissions: {e.msg}")
    try:
        b = await RT.client.f_balance()
        warnings.append(f"futures wallet {float(b['wallet']):.2f} USDT")
    except BinanceError as e:
        warnings.append(f"could not read the futures balance: {e.msg}")
    return {"ok": not problems, "problems": problems, "warnings": warnings}


@app.post("/arm", dependencies=[R])
async def arm(body: dict = Body(...)):
    if body.get("phrase") != "ARM LIVE":
        raise HTTPException(400, 'type the phrase "ARM LIVE" to arm')
    chk = await arm_checks(bool(body.get("allow_any_ip")))
    if chk["ok"]:
        store.save_config({"armed": True})
        store.event("warning", "arm", "live trading ARMED")
        await RT.notifier.send("<b>Live trading is ARMED.</b> Orders can now reach your Binance account.")
    return dumps(chk)


@app.post("/disarm", dependencies=[R])
async def disarm():
    store.save_config({"armed": False})
    store.event("info", "arm", "live trading disarmed")
    return {"ok": True}


@app.get("/env/check", dependencies=[R])
async def env_check(mode: str = "live", allow_any_ip: bool = False):
    """What would happen switching to `mode`, without actually switching - used by the app before showing its warning dialog."""
    mode = mode.lower()
    if mode != "live":
        return {"ok": True}
    if not (env("EXEC_BINANCE_KEY") and env("EXEC_BINANCE_SECRET")):
        return {"ok": False, "problems": ["no Binance key in exec.env (run tc_exec.py keys on the VPS first)"], "warnings": []}
    if RT.env == "live":
        return dumps(await arm_checks(allow_any_ip))
    return {"ok": True, "note": "a key is present; its permissions are checked at the moment you actually switch"}


@app.post("/env", dependencies=[R])
async def env_switch(b: dict = Body(...)):
    return dumps(await RT.switch_env(b.get("mode", ""), bool(b.get("confirm")), bool(b.get("allow_any_ip"))))


@app.get("/arm/check", dependencies=[R])
async def arm_check(allow_any_ip: bool = False):
    return dumps(await arm_checks(allow_any_ip))


# ------------------------------------------------------------------ futures: tickets and management
@app.post("/order/preview", dependencies=[R])
async def order_preview(t: dict = Body(...)):
    guard()
    try:
        return dumps(await RT.fut.plan(dict(t, source="manual")))
    except BinanceError as e:
        raise HTTPException(400, e.msg)


@app.post("/order", dependencies=[R])
async def order(t: dict = Body(...)):
    guard()
    t = dict(t, source="manual")
    try:
        pl = await RT.fut.plan(t)
    except BinanceError as e:
        raise HTTPException(400, e.msg)
    return dumps(await RT.fut.execute(pl, t, None, via="manual"))


@app.post("/position/close", dependencies=[R])
async def position_close(b: dict = Body(...)):
    return dumps(await RT.fut.close_position(b["symbol"].upper(), float(b.get("pct", 100)), reason="manual"))


@app.post("/position/stop", dependencies=[R])
async def position_stop(b: dict = Body(...)):
    return dumps(await RT.fut.move_stop(b["symbol"].upper(), b["price"]))


@app.post("/orders/cancel", dependencies=[R])
async def orders_cancel(b: dict = Body(...)):
    return dumps(await RT.fut.cancel_orders(b["symbol"].upper()))


@app.post("/leverage", dependencies=[R])
async def leverage(b: dict = Body(...)):
    return dumps(await RT.fut.set_leverage(b["symbol"].upper(), int(b["leverage"]), b.get("margin_type")))


@app.get("/proposals", dependencies=[R])
async def proposals(status: str = "pending", limit: int = 30):
    if status == "pending":
        rows = store.q("SELECT * FROM proposals WHERE status='pending' AND expires_ts>? ORDER BY ts DESC", (time.time(),))
    else:
        rows = store.q("SELECT * FROM proposals ORDER BY ts DESC LIMIT ?", (limit,))
    for r in rows:
        r["intent"] = json.loads(r["intent"] or "{}")
        r.pop("nonce", None)
    return dumps(rows)


@app.post("/proposals/{pid}/approve", dependencies=[R])
async def proposal_approve(pid: str):
    guard()
    return dumps(await RT.fut.approve(pid, "app"))


@app.post("/proposals/{pid}/reject", dependencies=[R])
async def proposal_reject(pid: str):
    return dumps(await RT.fut.reject(pid, "app"))


@app.post("/kill", dependencies=[R])
async def kill(b: dict = Body(...)):
    return dumps(await RT.kill(b.get("level", ""), "app"))


@app.post("/resume", dependencies=[R])
async def resume(b: dict = Body(default={})):
    return dumps(await RT.fut.resume("app", bool(b.get("clear_panic"))))


@app.get("/wallet", dependencies=[R])
async def wallet():
    """Spot balances (with USDT valuation where a direct pair exists) and the futures account summary,
    kept separate the way an exchange's own wallet screen does."""
    spot_bal = await RT.client.s_account()
    rows = []
    for asset, bal in spot_bal.items():
        free, locked = float(bal["free"]), float(bal["locked"])
        total = free + locked
        if total <= 1e-12:
            continue
        value = total if asset == "USDT" else None
        if value is None:
            try:
                px = float(await RT.client.price("spot", asset + "USDT"))
                value = total * px
            except BinanceError:
                pass
        rows.append({"asset": asset, "free": free, "locked": locked, "total": total, "value_usdt": value})
    rows.sort(key=lambda r: -(r["value_usdt"] or 0))
    try:
        spot_open_orders = len(await RT.client.s_open_orders())
    except BinanceError:
        spot_open_orders = None
    fut = await RT.fut.account()
    return dumps({"spot": {"balances": rows, "total_value_usdt": sum((r["value_usdt"] or 0) for r in rows), "open_orders": spot_open_orders},
                  "futures": {"wallet": fut["wallet"], "available": fut["available"], "equity": fut["equity"], "upnl": fut["upnl"]}})


@app.get("/stats", dependencies=[R])
async def stats():
    f = await RT.fut.stats()
    g = RT.grid.stats()
    return dumps({"futures": f, "grid": g, "combined_pnl_total": f["pnl_total"] + g["total_profit"]})


@app.get("/trades", dependencies=[R])
async def trades(limit: int = 50):
    rows = store.q("SELECT * FROM trades WHERE status NOT IN ('failed','cancelled') ORDER BY ts DESC LIMIT ?", (limit,))
    closed = [r for r in rows if r["status"] == "closed"]
    wins = sum(1 for r in closed if (r["pnl"] or 0) > 0)
    return dumps({"rows": rows, "closed": len(closed), "win_rate": (wins / len(closed) * 100) if closed else None, "pnl_total": sum((r["pnl"] or 0) for r in closed),
                  "pnl_today": RT.fut.daily_pnl()})


@app.get("/events", dependencies=[R])
async def events(limit: int = 60):
    return dumps(store.events(limit))


@app.get("/symbols", dependencies=[R])
async def symbols(kind: str = "fut", q: str = ""):
    market = "fut" if kind == "fut" else "spot"
    try:
        await RT.client.sym(market, "BTCUSDT")
        names = sorted(s for (m, s) in RT.client._info if m == market and s.endswith("USDT"))
    except BinanceError:
        names = []
    q = q.upper()
    return [n for n in names if q in n][:60]


@app.get("/price/{symbol}", dependencies=[R])
async def price(symbol: str, kind: str = "fut"):
    try:
        return {"symbol": symbol.upper(), "price": float(await RT.client.price("fut" if kind == "fut" else "spot", symbol.upper()))}
    except BinanceError as e:
        raise HTTPException(400, e.msg)


@app.post("/signals/scan", dependencies=[R])
async def signals_scan():
    base, tok = env("COMPANION_URL", "http://127.0.0.1:8000"), env("COMPANION_TOKEN") or C.API_TOKEN
    return dumps(await S.scan(RT.fut, lambda style: S.fetch_rows(base, tok, style)))


# ------------------------------------------------------------------ spot grid
@app.post("/grid/plan", dependencies=[R])
async def grid_plan(cfg: dict = Body(...)):
    try:
        return dumps(await RT.grid.plan(cfg))
    except BinanceError as e:
        raise HTTPException(400, e.msg)


@app.post("/grid/start", dependencies=[R])
async def grid_start(cfg: dict = Body(...)):
    guard()
    if RT.env == "live" and not store.config().get("armed"):
        raise HTTPException(409, "live trading is not armed")
    try:
        return dumps(await RT.grid.start(cfg))
    except BinanceError as e:
        raise HTTPException(400, e.msg)


@app.post("/grid/{gid}/stop", dependencies=[R])
async def grid_stop(gid: str, b: dict = Body(default={})):
    return dumps(await RT.grid.stop(gid, "user", bool(b.get("sell_inventory"))))


@app.get("/grids", dependencies=[R])
async def grids():
    return dumps(RT.grid.summary())


@app.get("/grid/{gid}", dependencies=[R])
async def grid_detail(gid: str):
    return dumps(await RT.grid.analytics(gid))
