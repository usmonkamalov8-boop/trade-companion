"""USD-M futures engine: plan -> (confirm) -> enter -> protect on the exchange -> reconcile -> report. Plus the kill switch.

Rules the code holds itself to:
- One-way position mode only (refuses to arm in hedge mode).
- Every position must have a STOP_MARKET (closePosition) on the exchange. If the stop cannot be placed the position is closed at
  once (setting on_unprotected=close) instead of being left naked.
- Orders carry client ids, so a retry after a timeout looks the order up instead of sending it twice.
- Everything that changes orders runs under one lock; the kill switch does not wait for it for long."""
import asyncio, json, secrets, time
from decimal import Decimal

from . import risk, store
from .binance import BinanceError, D, fmt
from .notify import esc, kb


def day_key(ts=None):
    return time.strftime("%Y-%m-%d", time.gmtime(ts or time.time()))


def fl(x, nd=6):
    try:
        return round(float(x), nd)
    except Exception:
        return None


class Futures:
    def __init__(self, client, notifier, env="live", clock=time.time):
        self.c, self.n, self.env, self.clock = client, notifier, env, clock
        self.lock = asyncio.Lock()
        self.fail_count = 0
        self.last_ok = 0.0
        self.unprotected = {}                 # symbol -> first time seen without a stop
        self.alerted = set()
        self.last_error = None

    # ------------------------------------------------------------------ state
    @property
    def halted(self):
        return bool(store.kv_get("halted", False))

    def live_ok(self):
        """Paper mode may always trade; live needs the arm step."""
        return self.env != "live" or bool(store.config().get("armed"))

    async def account(self):
        b = await self.c.f_balance()
        wallet, upnl = float(b["wallet"]), float(b["upnl"])
        eq = wallet + upnl
        k = "eq0:" + day_key(self.clock())
        if store.kv_get(k) is None:
            store.kv_set(k, eq)
        return {"wallet": wallet, "equity": eq, "available": float(b["available"]), "upnl": upnl, "day_start": store.kv_get(k, eq)}

    def _open_trades(self, statuses=("pending_entry", "open", "submitting")):
        ph = ",".join("?" * len(statuses))
        return store.q(f"SELECT * FROM trades WHERE status IN ({ph})", statuses)

    def daily_pnl(self):
        t0 = time.mktime(time.strptime(day_key(self.clock()), "%Y-%m-%d")) - time.timezone
        r = store.q("SELECT COALESCE(SUM(pnl),0) AS s FROM trades WHERE status='closed' AND close_ts>=?", (t0,))
        return float(r[0]["s"])

    async def context(self, symbol, acc=None):
        acc = acc or await self.account()
        pos = await self.c.f_positions()
        opn = self._open_trades()
        t0 = time.mktime(time.strptime(day_key(self.clock()), "%Y-%m-%d")) - time.timezone
        today = store.q("SELECT COUNT(*) AS n FROM trades WHERE ts>=? AND status NOT IN ('failed','cancelled')", (t0,))[0]["n"]
        last = {r["symbol"]: r["ts"] for r in store.q("SELECT symbol, MAX(ts) AS ts FROM trades WHERE status NOT IN ('failed','cancelled') GROUP BY symbol")}
        held = {p["symbol"] for p in pos} | {t["symbol"] for t in opn}
        return {"equity": acc["equity"], "available": acc["available"], "halted": self.halted, "open_positions": len(pos),
                "pending_entries": sum(1 for t in opn if t["status"] in ("pending_entry", "submitting")), "trades_today": today,
                "daily_pnl": self.daily_pnl(), "day_start_equity": acc["day_start"], "last_trade_ts": last, "now": self.clock(),
                "same_symbol_open": symbol in held}

    # ------------------------------------------------------------------ planning
    async def plan(self, intent):
        """Resolve an intent (a manual ticket or a signal) into exact numbers and run the risk rules. Sends nothing to the exchange."""
        cfg = store.config()["futures"]
        symbol = intent["symbol"].upper()
        intent = dict(intent, symbol=symbol)
        sym = await self.c.sym("fut", symbol)
        cur = await self.c.price("fut", symbol)
        lev = int(intent.get("leverage") or cfg["default_leverage"])
        mt = intent.get("margin_type") or cfg["margin_type"]
        et = intent.get("entry_type") or cfg["entry_type"]
        price = sym.price(D(intent["price"])) if et == "LIMIT" and intent.get("price") else cur
        if et == "LIMIT" and not intent.get("price"):
            et = "MARKET"
        acc = await self.account()
        qty, how = risk.resolve_qty(intent, price, acc["equity"], sym, lev)
        raw_qty = qty
        qty = sym.qty(qty, market=(et == "MARKET"))
        stop = fl(sym.price(D(intent["stop"]))) if intent.get("stop") else None
        tp = fl(sym.price(D(intent["tp"]))) if intent.get("tp") else None
        p = {"symbol": symbol, "side": intent["side"], "entry_type": et, "price": float(price), "cur_price": float(cur), "qty": qty, "qty_f": float(qty),
             "notional": float(qty * price), "margin_needed": float(qty * price) / lev, "leverage": lev, "margin_type": mt, "stop": stop, "tp": tp,
             "sizing": how, "trail_pct": intent.get("trail_pct"), "filter_errors": sym.check(price, qty, market=(et == "MARKET")) if qty > 0 else []}
        if raw_qty > 0 and qty == 0:
            p["filter_errors"] = [f"size rounds down to zero: the exchange's step for {symbol} is {fmt(sym.step)}"]
        ctx = await self.context(symbol, acc)
        res = risk.check(cfg, dict(intent, stop=stop, tp=tp), p, ctx)
        p.update(res)
        p["qty"] = p["qty_f"]
        p["equity"] = acc["equity"]
        return p

    # ------------------------------------------------------------------ proposals (manual mode)
    async def propose(self, intent, source="signal"):
        cfg = store.config()["futures"]
        intent = dict(intent, source=source)
        if not cfg["enabled"]:
            return {"created": False, "reasons": ["the futures profile is switched off"]}
        pl = await self.plan(intent)
        if not pl["ok"]:
            store.event("info", "signal", f"{intent['symbol']} {intent['side']} skipped: " + "; ".join(pl["violations"]))
            return {"created": False, "reasons": pl["violations"], "plan": pl}
        if cfg["mode"] == "auto" and source == "signal":
            r = await self.execute(pl, intent, None, via="auto")
            return {"created": False, "auto": True, **r}
        pid, nonce = secrets.token_hex(4), secrets.token_hex(3)
        exp = self.clock() + cfg["confirm_timeout_min"] * 60
        intent["_plan"] = {k: pl.get(k) for k in ("qty", "notional", "margin_needed", "leverage", "margin_type", "risk_amount", "risk_pct", "rr", "stop_pct", "entry_type", "price", "stop", "tp", "warnings")}
        store.x("INSERT INTO proposals (id, ts, source, symbol, side, intent, status, nonce, expires_ts, price0) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, self.clock(), source, pl["symbol"], pl["side"], json.dumps(intent), "pending", nonce, exp, pl["cur_price"]))
        msg = await self.n.send(self.proposal_text(pl, pid, cfg["confirm_timeout_min"]), buttons=kb([("Take the trade", f"ok:{pid}:{nonce}"), ("Skip", f"no:{pid}:{nonce}")]))
        if msg:
            store.x("UPDATE proposals SET msg_id=? WHERE id=?", (msg, pid))
        return {"created": True, "id": pid, "plan": pl, "expires_ts": exp}

    def proposal_text(self, pl, pid, minutes):
        arrow = "LONG" if pl["side"] == "LONG" else "SHORT"
        lines = [f"<b>Trade proposal {esc(pl['symbol'])} {arrow}</b>",
                 f"{'Limit' if pl['entry_type'] == 'LIMIT' else 'Market'} entry {esc(fmt(pl['price']))} (now {esc(fmt(pl['cur_price']))}), size {esc(fmt(pl['qty']))}, "
                 f"value {pl['notional']:.0f} USDT, {pl['leverage']}x {pl['margin_type'].lower()}",
                 f"Stop {esc(fmt(pl['stop']))}" + (f" ({pl.get('stop_pct', 0):.2f}% away)" if pl.get("stop_pct") else "") + f"   Target {esc(fmt(pl['tp']))}" + (f" ({pl['rr']:.2f}R)" if pl.get("rr") else ""),
                 f"Risk if stopped: {pl.get('risk_amount', 0):.2f} USDT ({pl.get('risk_pct', 0):.2f}% of {pl['equity']:.0f})"]
        if pl.get("warnings"):
            lines.append("Note: " + esc("; ".join(pl["warnings"])))
        lines.append(f"Valid for {minutes} min. Nothing is placed until you press Take.")
        return "\n".join(lines)

    async def approve(self, pid, via="app", nonce=None):
        r = store.q("SELECT * FROM proposals WHERE id=?", (pid,))
        if not r:
            return {"ok": False, "error": "unknown proposal"}
        p = r[0]
        if nonce is not None and nonce != p["nonce"]:
            return {"ok": False, "error": "bad confirmation code"}
        if p["status"] != "pending":
            return {"ok": False, "error": f"proposal already {p['status']}"}
        if self.clock() > p["expires_ts"]:
            store.x("UPDATE proposals SET status='expired' WHERE id=?", (pid,))
            await self.n.edit(p["msg_id"], f"Proposal {esc(p['symbol'])} expired.")
            return {"ok": False, "error": "the proposal expired"}
        cfg = store.config()["futures"]
        intent = json.loads(p["intent"])
        pl = await self.plan(dict(intent, override=False))
        drift = abs(pl["cur_price"] - p["price0"]) / p["price0"] * 100
        why = list(pl["violations"])
        if drift > cfg["max_drift_pct"]:
            why.append(f"price moved {drift:.2f}% since the proposal (limit {cfg['max_drift_pct']}%)")
        if why:
            store.x("UPDATE proposals SET status='rejected', result=?, decided_by=?, decided_ts=? WHERE id=?", (json.dumps(why), via, self.clock(), pid))
            await self.n.edit(p["msg_id"], f"Proposal {esc(p['symbol'])} refused at approval: {esc('; '.join(why))}")
            return {"ok": False, "error": "; ".join(why)}
        res = await self.execute(pl, intent, pid, via=via)
        store.x("UPDATE proposals SET status=?, result=?, decided_by=?, decided_ts=? WHERE id=?",
                ("executed" if res.get("ok") else "failed", json.dumps(res, default=str), via, self.clock(), pid))
        await self.n.edit(p["msg_id"], f"Proposal {esc(p['symbol'])}: " + ("placed" if res.get("ok") else "failed: " + esc(res.get("error", ""))))
        return res

    async def reject(self, pid, via="app", nonce=None):
        r = store.q("SELECT * FROM proposals WHERE id=?", (pid,))
        if not r or r[0]["status"] != "pending" or (nonce is not None and nonce != r[0]["nonce"]):
            return {"ok": False, "error": "not pending"}
        store.x("UPDATE proposals SET status='skipped', decided_by=?, decided_ts=? WHERE id=?", (via, self.clock(), pid))
        await self.n.edit(r[0]["msg_id"], f"Proposal {esc(r[0]['symbol'])} skipped.")
        return {"ok": True}

    async def expire_proposals(self):
        for p in store.q("SELECT * FROM proposals WHERE status='pending' AND expires_ts<?", (self.clock(),)):
            store.x("UPDATE proposals SET status='expired' WHERE id=?", (p["id"],))
            await self.n.edit(p["msg_id"], f"Proposal {esc(p['symbol'])} expired without an answer.")

    # ------------------------------------------------------------------ execution
    async def execute(self, pl, intent, proposal_id, via="manual"):
        if not pl["ok"]:
            return {"ok": False, "error": "; ".join(pl["violations"])}
        if not self.live_ok():
            return {"ok": False, "error": "live trading is not armed (tc_exec.py arm)"}
        if self.halted:
            return {"ok": False, "error": "new entries are stopped (kill switch)"}
        async with self.lock:
            tid = "t" + time.strftime("%y%m%d%H%M%S", time.gmtime(self.clock())) + secrets.token_hex(2)
            store.x("INSERT INTO trades (id, ts, proposal_id, symbol, side, qty, entry_type, entry_price, stop, tp, leverage, margin, status, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, self.clock(), proposal_id, pl["symbol"], pl["side"], pl["qty"], pl["entry_type"], pl["price"], pl["stop"], pl["tp"], pl["leverage"],
                     pl["margin_type"], "submitting", json.dumps({"via": via, "trail_pct": pl.get("trail_pct")})))
            sym = pl["symbol"]
            try:
                try:
                    await self.c.f_set_margin(sym, pl["margin_type"])
                except BinanceError as e:
                    if e.code not in (-4047, -4048):
                        raise
                await self.c.f_set_leverage(sym, pl["leverage"])
                s = await self.c.sym("fut", sym)
                params = {"symbol": sym, "side": "BUY" if pl["side"] == "LONG" else "SELL", "type": pl["entry_type"], "quantity": s.qty(D(pl["qty"]), market=pl["entry_type"] == "MARKET"),
                          "newClientOrderId": tid + "e", "newOrderRespType": "RESULT"}
                if pl["entry_type"] == "LIMIT":
                    params.update(price=s.price(D(pl["price"])), timeInForce="GTC")
                try:
                    o = await self.c.f_new_order(**params)
                except BinanceError as e:
                    if e.code == -1001 or e.status == 0:                 # unknown outcome: look the order up before deciding
                        o = await self._lookup(sym, tid + "e")
                        if o is None:
                            raise
                    else:
                        raise
            except BinanceError as e:
                store.x("UPDATE trades SET status='failed', close_reason=? WHERE id=?", (str(e)[:200], tid))
                await self.n.send(f"<b>Order not placed</b> {esc(sym)} {esc(pl['side'])}\n{esc(e.msg or e)}")
                return {"ok": False, "error": e.msg or str(e), "trade_id": tid}
            filled = D(o.get("executedQty", 0))
            avg = float(o["avgPrice"]) if o.get("avgPrice") and float(o["avgPrice"]) > 0 else pl["price"]
            if o.get("status") == "FILLED" or (pl["entry_type"] == "MARKET" and filled > 0):
                store.x("UPDATE trades SET status='open', entry_avg=? WHERE id=?", (avg, tid))
                await self.n.send(f"<b>Entered {esc(sym)} {esc(pl['side'])}</b> {esc(fmt(filled))} @ {esc(fmt(avg))} ({pl['leverage']}x)\nStop {esc(fmt(pl['stop']))}  Target {esc(fmt(pl['tp']))}", silent=True)
                ok, note = await self.protect(tid)
                return {"ok": True, "trade_id": tid, "status": "open", "protected": ok, "note": note}
            store.x("UPDATE trades SET status='pending_entry' WHERE id=?", (tid,))
            await self.n.send(f"<b>Limit order placed</b> {esc(sym)} {esc(pl['side'])} {esc(fmt(pl['qty']))} @ {esc(fmt(pl['price']))}\nThe stop and target are placed when it fills.", silent=True)
            return {"ok": True, "trade_id": tid, "status": "pending_entry"}

    async def _lookup(self, symbol, cid):
        try:
            return await self.c.f_query(symbol, cid)
        except BinanceError:
            return None

    async def protect(self, tid):
        """Place the stop (and target) on the exchange for an open trade. If the stop cannot be placed the position is closed."""
        t = store.q("SELECT * FROM trades WHERE id=?", (tid,))[0]
        cfg = store.config()["futures"]
        sym, long = t["symbol"], t["side"] == "LONG"
        exit_side = "SELL" if long else "BUY"
        s = await self.c.sym("fut", sym)
        meta = json.loads(t["meta"] or "{}")
        notes, stop_ok = [], t["stop"] is None
        try:
            have = await self.c.f_open_algo(sym)
        except BinanceError:
            have = []
        has = lambda *types: any(a["orderType"] in types for a in have)
        if t["stop"] is not None and has("STOP_MARKET", "STOP"):
            stop_ok, t = True, dict(t, stop=None)                   # already there: only add what is missing
        if t["stop"] is not None:
            for i in range(3):
                try:
                    a = await self.c.f_new_algo(symbol=sym, side=exit_side, type="STOP_MARKET", triggerPrice=s.price(D(t["stop"])), closePosition="true",
                                                workingType=cfg["stop_working_type"], clientAlgoId=tid + "s" + (str(i) if i else ""))
                    meta["sl_algo"], stop_ok = a["algoId"], True
                    break
                except BinanceError as e:
                    if e.code == -2021:                                  # price is already through the stop
                        notes.append("price already beyond the stop")
                        await self.close_position(sym, 100, reason="stop already crossed", trade_id=tid)
                        return False, "closed: the price was already beyond the stop"
                    notes.append(f"stop attempt {i + 1}: {e.msg}")
                    await asyncio.sleep(0.4)
        if not stop_ok:
            if cfg["on_unprotected"] == "close":
                await self.n.send(f"<b>Could not place the stop for {esc(sym)}</b>: closing the position now.\n{esc('; '.join(notes))}", retries=3)
                await self.close_position(sym, 100, reason="stop could not be placed", trade_id=tid)
                return False, "closed: stop could not be placed"
            await self.n.send(f"<b>WARNING {esc(sym)} has no stop</b> and the setting is alert-only.\n{esc('; '.join(notes))}", retries=3)
        if t["tp"] is not None and not has("TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
            try:
                a = await self.c.f_new_algo(symbol=sym, side=exit_side, type="TAKE_PROFIT_MARKET", triggerPrice=s.price(D(t["tp"])), closePosition="true",
                                            workingType=cfg["stop_working_type"], clientAlgoId=tid + "p")
                meta["tp_algo"] = a["algoId"]
            except BinanceError as e:
                notes.append(f"target not placed: {e.msg}")
        trail = meta.get("trail_pct")
        if trail and not has("TRAILING_STOP_MARKET"):
            try:
                pos = [p for p in await self.c.f_positions() if p["symbol"] == sym]
                if pos:
                    a = await self.c.f_new_algo(symbol=sym, side=exit_side, type="TRAILING_STOP_MARKET", quantity=s.qty(abs(D(pos[0]["positionAmt"])), market=True),
                                                reduceOnly="true", callbackRate=max(0.1, min(10, float(trail))), clientAlgoId=tid + "t")
                    meta["trail_algo"] = a["algoId"]
            except BinanceError as e:
                notes.append(f"trailing stop not placed: {e.msg}")
        store.x("UPDATE trades SET meta=? WHERE id=?", (json.dumps(meta), tid))
        if notes:
            await self.n.send(f"{esc(sym)} protection notes: {esc('; '.join(notes))}")
        return stop_ok, "; ".join(notes)

    # ------------------------------------------------------------------ manual management
    async def close_position(self, symbol, pct=100, reason="manual", trade_id=None):
        pos = [p for p in await self.c.f_positions() if p["symbol"] == symbol]
        if not pos:
            return {"ok": False, "error": "no open position"}
        amt = D(pos[0]["positionAmt"])
        s = await self.c.sym("fut", symbol)
        q = s.qty(abs(amt) * D(pct) / 100, market=True) if pct < 100 else abs(amt)
        if q <= 0:
            return {"ok": False, "error": "size too small to close that share"}
        try:
            o = await self.c.f_new_order(symbol=symbol, side="SELL" if amt > 0 else "BUY", type="MARKET", quantity=q, reduceOnly="true", newOrderRespType="RESULT",
                                         newClientOrderId=(trade_id or "m") + "x" + secrets.token_hex(2))
        except BinanceError as e:
            await self.n.send(f"<b>Close failed</b> {esc(symbol)}: {esc(e.msg)}", retries=3)
            return {"ok": False, "error": e.msg}
        if pct >= 100:
            store.x("UPDATE trades SET close_reason=? WHERE symbol=? AND status IN ('open','pending_entry')", (reason, symbol))
            await self.c.f_cancel_all(symbol)
        await self.n.send(f"Closed {esc(symbol)} {pct}% ({esc(reason)}) @ {esc(o.get('avgPrice'))}", silent=True)
        return {"ok": True, "order": o}

    async def cancel_orders(self, symbol):
        errs = await self.c.f_cancel_all(symbol)
        return {"ok": errs == 0, "errors": errs}

    async def move_stop(self, symbol, price):
        pos = [p for p in await self.c.f_positions() if p["symbol"] == symbol]
        if not pos:
            return {"ok": False, "error": "no open position"}
        long = D(pos[0]["positionAmt"]) > 0
        s = await self.c.sym("fut", symbol)
        px = s.price(D(price))
        cur = await self.c.price("fut", symbol)
        if (long and px >= cur) or (not long and px <= cur):
            return {"ok": False, "error": "the new stop would trigger immediately (wrong side of the price)"}
        async with self.lock:
            old = [a for a in await self.c.f_open_algo(symbol) if a["orderType"] == "STOP_MARKET"]
            try:
                new = await self.c.f_new_algo(symbol=symbol, side="SELL" if long else "BUY", type="STOP_MARKET", triggerPrice=px, closePosition="true",
                                              workingType=store.config()["futures"]["stop_working_type"], clientAlgoId="mv" + secrets.token_hex(5))
            except BinanceError as e:
                return {"ok": False, "error": e.msg}
            for a in old:                                             # the new stop is in place before the old one goes
                try:
                    await self.c.f_cancel_algo(algoId=a["algoId"])
                except BinanceError:
                    pass
            tr = store.q("SELECT id, meta FROM trades WHERE symbol=? AND status='open'", (symbol,))
            if tr:
                m = json.loads(tr[0]["meta"] or "{}")
                m["sl_algo"] = new["algoId"]
                store.x("UPDATE trades SET stop=?, meta=? WHERE id=?", (float(px), json.dumps(m), tr[0]["id"]))
        return {"ok": True, "stop": float(px)}

    async def set_leverage(self, symbol, lev, margin_type=None):
        cfg = store.config()["futures"]
        if lev > cfg["max_leverage"]:
            return {"ok": False, "error": f"above your leverage cap of {cfg['max_leverage']}x"}
        out = {}
        try:
            if margin_type:
                out["margin"] = (await self.c.f_set_margin(symbol, margin_type)).get("msg")
            await self.c.f_set_leverage(symbol, lev)
        except BinanceError as e:
            return {"ok": False, "error": e.msg}
        return {"ok": True, **out}

    # ------------------------------------------------------------------ reconcile loop
    async def reconcile(self):
        """Compare our records with the exchange and repair: fills of limit entries, missing stops, closed positions."""
        try:
            pos = {p["symbol"]: p for p in await self.c.f_positions()}
            orders = await self.c.f_open_orders()
            algos = await self.c.f_open_algo()
            self.fail_count, self.last_ok, self.last_error = 0, self.clock(), None
        except Exception as e:
            self.fail_count += 1
            self.last_error = str(e)[:160]
            if self.fail_count == 12:
                await self.n.send("<b>Exchange unreachable</b> for about a minute. Stops already on the exchange stay active.")
            return
        open_ids = {o["clientOrderId"] for o in orders}
        for t in self._open_trades(("pending_entry", "open")):
            sym = t["symbol"]
            p = pos.get(sym)
            if t["status"] == "pending_entry":
                filled = D(0)
                if t["id"] + "e" not in open_ids:
                    o = await self._lookup(sym, t["id"] + "e")
                    if o is None or o.get("status") in ("CANCELED", "EXPIRED", "REJECTED") and D(o.get("executedQty", 0)) == 0:
                        store.x("UPDATE trades SET status='cancelled', close_ts=?, close_reason='entry order gone' WHERE id=?", (self.clock(), t["id"]))
                        continue
                    filled = D(o.get("executedQty", 0))
                elif p:
                    filled = abs(D(p["positionAmt"]))
                if filled > 0 and not p:                                  # it filled and was already stopped out or closed
                    store.x("UPDATE trades SET status='open' WHERE id=?", (t["id"],))
                    await self._closed(dict(t, status="open"))
                    continue
                if filled > 0 and p:
                    store.x("UPDATE trades SET status='open', entry_avg=? WHERE id=?", (float(p["entryPrice"]), t["id"]))
                    await self.n.send(f"<b>Entry filled {esc(sym)} {esc(t['side'])}</b> @ {esc(p['entryPrice'])}", silent=True)
                    await self.protect(t["id"])
                    if t["id"] + "e" in open_ids:
                        pass                                              # partial fill: the rest stays resting, the close-position stop covers it
                    continue
                if self.clock() - t["ts"] > 4 * 3600:                     # a limit entry that never filled
                    try:
                        await self.c.f_cancel_order(sym, origClientOrderId=t["id"] + "e")
                    except BinanceError:
                        pass
                    store.x("UPDATE trades SET status='cancelled', close_ts=?, close_reason='entry expired (4 h)' WHERE id=?", (self.clock(), t["id"]))
                    await self.n.send(f"Limit entry {esc(sym)} expired after 4 hours and was cancelled.", silent=True)
                continue
            # status open
            if not p:
                await self._closed(t)
                continue
            has_stop = any(a["symbol"] == sym and a["orderType"] in ("STOP_MARKET", "STOP", "TRAILING_STOP_MARKET") for a in algos)
            if not has_stop and t["stop"] is not None:
                first = self.unprotected.setdefault(sym, self.clock())
                if self.clock() - first >= store.config()["futures"]["protect_grace_s"]:
                    self.unprotected.pop(sym, None)
                    await self.n.send(f"<b>{esc(sym)} lost its stop</b>: placing it again.", retries=3)
                    await self.protect(t["id"])
            else:
                self.unprotected.pop(sym, None)
        for sym, p in pos.items():
            if not any(t["symbol"] == sym for t in self._open_trades(("open", "pending_entry"))):
                if sym not in self.alerted:
                    self.alerted.add(sym)
                    stop = any(a["symbol"] == sym and a["orderType"] in ("STOP_MARKET", "STOP") for a in algos)
                    await self.n.send(f"Position on {esc(sym)} that this engine did not open ({esc(p['positionAmt'])} @ {esc(p['entryPrice'])})."
                                      + ("" if stop else " <b>It has no stop.</b>") + " It is not managed here; the kill switch still closes it.")
            else:
                self.alerted.discard(sym)
        await self.expire_proposals()

    async def _closed(self, t):
        sym = t["symbol"]
        try:
            await self.c.f_cancel_all(sym)
        except Exception:
            pass
        pnl = fees = 0.0
        exit_px = None
        try:
            tr = await self.c.f_user_trades(sym, int(t["ts"] * 1000) - 5000)
            for x in tr:
                pnl += float(x["realizedPnl"])
                fees += float(x["commission"])
            outs = [x for x in tr if x["side"] == ("SELL" if t["side"] == "LONG" else "BUY")]
            if outs:
                exit_px = float(outs[-1]["price"])
        except Exception:
            pass
        net = pnl - fees
        reason = "manual/other"
        if exit_px and t["stop"] and t["tp"]:
            reason = "stop" if abs(exit_px - t["stop"]) <= abs(exit_px - t["tp"]) else "target"
        elif exit_px and t["stop"]:
            reason = "stop" if abs(exit_px - t["stop"]) / exit_px < 0.002 else reason
        store.x("UPDATE trades SET status='closed', close_ts=?, exit_avg=?, pnl=?, fees=?, close_reason=COALESCE(NULLIF(close_reason,''), ?) WHERE id=?",
                (self.clock(), exit_px, net, fees, reason, t["id"]))
        await self.n.send(f"<b>Closed {esc(sym)} {esc(t['side'])}</b> ({esc(reason)}) result {net:+.2f} USDT (fees {fees:.2f})", silent=(net >= 0))

    # ------------------------------------------------------------------ kill switch
    async def kill(self, level, via="app"):
        if level not in ("stop", "flatten", "panic"):
            return {"ok": False, "error": "level must be stop, flatten or panic"}
        out = {"ok": True, "level": level}
        if level in ("stop", "flatten", "panic"):         # flatten also stops entries: otherwise a signal could reopen at once
            store.kv_set("halted", True)
        if level in ("flatten", "panic"):
            out["flatten"] = await self.flatten()
        if level == "panic":
            store.save_config({"futures": {"enabled": False, "mode": "manual"}})
            store.kv_set("panic", self.clock())
        store.event("warning", "kill", f"kill switch {level} via {via}: {json.dumps(out, default=str)[:300]}")
        left = (out.get("flatten") or {}).get("left")
        await self.n.send(f"<b>KILL SWITCH: {esc(level)}</b> (via {esc(via)})\n" +
                          ("New entries stopped." if level == "stop" else f"Closed: {esc(', '.join((out['flatten'] or {}).get('closed', [])) or 'nothing open')}") +
                          (f"\n<b>STILL OPEN: {esc(', '.join(left))}</b>" if left else ""), retries=3)
        return out

    async def resume(self, via="app", clear_panic=False):
        if store.kv_get("panic") and not clear_panic:
            return {"ok": False, "error": "panic was pressed: confirm to clear it, then switch the futures profile on again in settings"}
        store.kv_set("halted", False)
        if clear_panic:
            store.kv_set("panic", None)
        store.event("info", "kill", f"resumed via {via}")
        await self.n.send(f"New entries allowed again (via {esc(via)}).", silent=True)
        return {"ok": True}

    async def flatten(self):
        """Cancel every order and close every position on the whole futures account. Repeats until flat or out of attempts."""
        got = False
        try:
            await asyncio.wait_for(self.lock.acquire(), 4)
            got = True
        except asyncio.TimeoutError:
            pass                                      # closing risk matters more than order: go ahead without the lock
        rep = {"closed": [], "left": [], "errors": []}
        try:
            for attempt in range(3):
                try:
                    pos = await self.c.f_positions()
                    orders = await self.c.f_open_orders()
                    algos = await self.c.f_open_algo()
                except BinanceError as e:
                    rep["errors"].append(e.msg)
                    await asyncio.sleep(1)
                    continue
                syms = sorted({p["symbol"] for p in pos} | {o["symbol"] for o in orders} | {a["symbol"] for a in algos})
                if not syms:
                    break
                for sy in syms:
                    try:
                        await self.c.call("fut", "DELETE", "/fapi/v1/allOpenOrders", {"symbol": sy})      # entries and targets first; stops stay until flat
                    except BinanceError as e:
                        rep["errors"].append(f"{sy}: {e.msg}")
                for p in pos:
                    amt = D(p["positionAmt"])
                    try:
                        await self.c.f_new_order(symbol=p["symbol"], side="SELL" if amt > 0 else "BUY", type="MARKET", quantity=abs(amt), reduceOnly="true",
                                                 newClientOrderId="k" + secrets.token_hex(6))
                        if p["symbol"] not in rep["closed"]:
                            rep["closed"].append(p["symbol"])
                    except BinanceError as e:
                        rep["errors"].append(f"{p['symbol']}: {e.msg}")
                for sy in syms:
                    try:
                        await self.c.call("fut", "DELETE", "/fapi/v1/algoOpenOrders", {"symbol": sy})
                    except BinanceError as e:
                        rep["errors"].append(f"{sy}: {e.msg}")
            try:
                rep["left"] = [p["symbol"] for p in await self.c.f_positions()]
            except BinanceError as e:
                rep["errors"].append(e.msg)
                rep["left"] = ["unknown (could not read positions)"]
        finally:
            if got:
                self.lock.release()
        for t in self._open_trades(("pending_entry", "open", "submitting")):
            if t["symbol"] not in rep["left"]:
                store.x("UPDATE trades SET close_reason='kill switch' WHERE id=?", (t["id"],))
        return rep

    # ------------------------------------------------------------------ views for the app
    async def snapshot(self):
        acc = await self.account()
        pos = await self.c.f_positions()
        orders = await self.c.f_open_orders()
        algos = await self.c.f_open_algo()
        trades = {t["symbol"]: t for t in self._open_trades(("open", "pending_entry"))}
        rows = []
        for p in pos:
            amt = float(p["positionAmt"])
            sl = next((float(a["triggerPrice"]) for a in algos if a["symbol"] == p["symbol"] and a["orderType"] in ("STOP_MARKET", "STOP")), None)
            tp = next((float(a["triggerPrice"]) for a in algos if a["symbol"] == p["symbol"] and a["orderType"] in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")), None)
            rows.append({"symbol": p["symbol"], "side": "LONG" if amt > 0 else "SHORT", "qty": abs(amt), "entry": float(p["entryPrice"]), "mark": float(p["markPrice"]),
                         "upnl": float(p["unRealizedProfit"]), "leverage": int(float(p["leverage"])), "margin": p["marginType"], "liq": float(p["liquidationPrice"] or 0),
                         "stop": sl, "tp": tp, "protected": sl is not None, "managed": p["symbol"] in trades, "trade_id": (trades.get(p["symbol"]) or {}).get("id")})
        return {"account": acc, "positions": rows, "orders": [{"symbol": o["symbol"], "side": o["side"], "type": o["type"], "qty": o["origQty"], "price": o["price"],
                                                                "reduce_only": o.get("reduceOnly"), "id": o["orderId"]} for o in orders],
                "algo": [{"symbol": a["symbol"], "side": a["side"], "type": a["orderType"], "trigger": a["triggerPrice"], "id": a["algoId"]} for a in algos],
                "halted": self.halted, "daily_pnl": self.daily_pnl(), "last_ok": self.last_ok, "error": self.last_error}
