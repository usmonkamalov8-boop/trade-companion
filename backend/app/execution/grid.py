"""Spot grid bot: planner, simulator, live engine and analytics.

Model (one order per cell): the range is split into n cells between n+1 price levels. Cell i buys at level i and sells at level i+1.
A cell is EMPTY (a buy order waits at its lower level) or FULL (a sell order waits at its upper level). At the start, cells whose
lower level is below the price are empty; the others are FULL, which needs base currency, so the bot buys it at market once.
When a buy fills, the cell becomes full (sell one level up); when a sell fills, it becomes empty again (buy one level down).
The live engine, the simulator and the planner all use this one model, so a simulation of the same prices matches the live result.

Fees: the buy fee is taken from the base currency received and the sell fee from the quote received (0.1% by default, 0.075% with
BNB). A cell therefore buys qb = ceil_to_step(qs / (1 - fee)) and sells qs (a whole number of steps), so what the buy leaves after
its fee always covers the sell; the tiny remainder accumulates as dust in the inventory."""
import asyncio, json, math, secrets, time
from decimal import Decimal

from . import store
from .binance import BinanceError, D, fmt
from .notify import esc


# ------------------------------------------------------------------ levels and plan
def make_levels(lower, upper, n, mode, sym):
    lo, hi = float(lower), float(upper)
    if mode == "geometric":
        raw = [lo * (hi / lo) ** (i / n) for i in range(n + 1)]
    else:
        raw = [lo + (hi - lo) * i / n for i in range(n + 1)]
    lv = [sym.price(D(x)) for x in raw]
    lv[0], lv[-1] = sym.price(D(lower)), sym.price(D(upper))
    return lv


def compute_plan(cfg, price, sym, fee_pct, reserve=0.005):
    """Pure calculation: levels, order size, which cells start empty or full, and what each cycle should earn."""
    price = D(price)
    n = int(cfg["grids"])
    err, warn = [], []
    if not (2 <= n <= 100):
        err.append("the number of grids must be between 2 and 100")
    if D(cfg["lower"]) >= D(cfg["upper"]):
        err.append("lower must be below upper")
    if err:
        return {"ok": False, "errors": err, "warnings": warn}
    levels = make_levels(cfg["lower"], cfg["upper"], n, cfg.get("mode", "arithmetic"), sym)
    if any(levels[i] >= levels[i + 1] for i in range(n)):
        return {"ok": False, "errors": ["too many grids for this price range: two levels would be the same price at this tick size"], "warnings": warn}
    if not (levels[0] < price < levels[-1]):
        return {"ok": False, "errors": [f"the price {fmt(price)} is outside the range {fmt(levels[0])} - {fmt(levels[-1])}: start the grid while the price is inside it"], "warnings": warn}
    k = max(i for i in range(n) if levels[i] < price)          # price sits in cell k (levels[k] < price < levels[k+1])
    empty, full = list(range(0, k + 1)), list(range(k + 1, n))
    invest = D(cfg["invest"])
    f = fee_pct / 100
    denom = (sum((levels[i] for i in empty), D(0)) + price * len(full) * D("1.001")) / (1 - D(str(f)))
    q = sym.qty(invest * (1 - D(str(reserve))) / denom)                 # q = quantity SOLD per cell
    qb = sym.qty_up(q / (1 - D(str(f)))) if q > 0 else D(0)             # quantity BOUGHT per cell (covers the sell after the fee)
    if q <= 0 or q < sym.min_qty:
        err.append(f"the investment is too small for {n} grids: each order would be below the minimum size {fmt(sym.min_qty)}")
    if q * levels[0] < sym.min_notional:
        err.append(f"each order at the lowest level would be worth {fmt(q * levels[0])}, below the exchange minimum {fmt(sym.min_notional)}: use fewer grids or more money")
    spacing = [float(levels[i + 1] / levels[i] - 1) * 100 for i in range(n)]
    net = [s - 2 * fee_pct - 0 for s in spacing]
    if min(net) <= 0:
        err.append(f"the smallest grid spacing ({min(spacing):.3f}%) does not cover the round-trip fee ({2 * fee_pct:.2f}%): use fewer grids")
    elif min(net) < 0.15:
        warn.append(f"the thinnest grid earns only {min(net):.2f}% per cycle after fees")
    cash_buys = float(qb * sum((levels[i] for i in empty), D(0)))
    base_qty = qb * len(full)
    inv_cost = float(base_qty * price)
    # what the whole grid is worth if the price runs to either edge of the range (the "worst" and "best" cases of holding it)
    ff = float(f)
    cash0 = float(invest) - float(qb * price) * len(full)
    at_lower = cash0 - float(qb) * sum(float(levels[i]) for i in empty) + float(qb) * (1 - ff) * n * float(levels[0]) - float(invest)
    at_upper = cash0 + sum(float(q) * float(levels[i + 1]) * (1 - ff) for i in full) - float(invest)
    if (cfg.get("stop_price") is not None) and D(cfg["stop_price"]) >= levels[0]:
        err.append("the stop price must be below the lower level")
    if (cfg.get("take_profit_price") is not None) and D(cfg["take_profit_price"]) <= levels[-1]:
        err.append("the take-profit price must be above the upper level")
    return {"ok": not err, "errors": err, "warnings": warn, "levels": [float(x) for x in levels], "n": n, "cell": k, "qty": float(q), "qty_str": fmt(q),
            "qty_buy": float(qb), "qty_buy_str": fmt(qb), "empty_cells": empty, "full_cells": full, "buy_orders": len(empty), "sell_orders": len(full), "cash_for_buys": cash_buys, "inventory_qty": float(base_qty),
            "inventory_cost": inv_cost, "invest": float(invest), "spacing_min_pct": min(spacing), "spacing_max_pct": max(spacing),
            "net_per_cycle_min_pct": min(net), "net_per_cycle_avg_pct": sum(net) / len(net), "fee_round_trip_pct": 2 * fee_pct,
            "per_cycle_profit_usdt": sum(float(q) * float(levels[i + 1]) * (1 - f) - float(qb) * float(levels[i]) for i in range(n)) / n,
            "price": float(price), "range_pct": float((levels[-1] / levels[0] - 1) * 100),
            "max_drawdown_at_lower_pct": float(1 - levels[0] / price) * 100, "pnl_if_price_at_lower": at_lower, "pnl_if_price_at_upper": at_upper}


# ------------------------------------------------------------------ simulation
def simulate(plan, candles, fee_pct, cfg=None):
    """Replay candles through the same cell model. plan comes from compute_plan; candles are dicts with o, h, l, c, t."""
    lv, n, qs, qb = plan["levels"], plan["n"], plan["qty"], plan["qty_buy"]
    f = fee_pct / 100
    price0 = candles[0]["o"]
    full = set(i for i in range(n) if lv[i] >= price0)
    cash = plan["invest"] - qb * price0 * len(full)
    base = qb * (1 - f) * len(full)
    buys = sells = cycles = 0
    profit = 0.0
    fee_paid = qb * price0 * len(full) * f                 # value of the base fee on the initial purchase
    peak, worst = plan["invest"], 0.0
    max_inv_val = base * price0
    in_range = 0
    stop_p, tp_p = (cfg or {}).get("stop_price"), (cfg or {}).get("take_profit_price")
    stopped = None
    for c in candles:
        path = [c["o"], c["l"], c["h"], c["c"]] if c["c"] >= c["o"] else [c["o"], c["h"], c["l"], c["c"]]
        for a, b in zip(path, path[1:]):
            if b < a:                                       # falling: empty cells buy at their lower level
                for i in sorted((i for i in range(n) if i not in full and b <= lv[i] <= a), key=lambda i: -lv[i]):
                    cash -= qb * lv[i]
                    base += qb * (1 - f)
                    fee_paid += qb * lv[i] * f
                    full.add(i)
                    buys += 1
            elif b > a:                                     # rising: full cells sell at their upper level
                for i in sorted((i for i in full if a <= lv[i + 1] <= b), key=lambda i: lv[i + 1]):
                    rev = qs * lv[i + 1] * (1 - f)
                    cash += rev
                    base -= qs
                    fee_paid += qs * lv[i + 1] * f
                    full.discard(i)
                    sells += 1
                    cycles += 1
                    profit += rev - qb * lv[i]
        last = c["c"]
        if lv[0] <= c["l"] and c["h"] <= lv[-1]:
            in_range += 1
        val = cash + base * last
        peak = max(peak, val)
        worst = max(worst, peak - val)
        max_inv_val = max(max_inv_val, base * last)
        if stop_p and c["l"] <= stop_p:
            cash += base * stop_p * (1 - f)
            base, stopped = 0.0, "stop"
            break
        if tp_p and c["h"] >= tp_p:
            cash += base * tp_p * (1 - f)
            base, stopped = 0.0, "take_profit"
            break
    last = candles[-1]["c"]
    total = cash + base * last - plan["invest"]
    days = max((candles[-1]["t"] - candles[0]["t"]) / 86400 + (candles[1]["t"] - candles[0]["t"]) / 86400 if len(candles) > 1 else 1, 1e-9)
    hold = plan["invest"] / price0 * (last - price0)
    return {"cycles": cycles, "buys": buys, "sells": sells, "grid_profit": profit, "fees": fee_paid, "total_pnl": total, "total_return_pct": total / plan["invest"] * 100,
            "hold_pnl": hold, "hold_return_pct": hold / plan["invest"] * 100, "vs_hold": total - hold, "days": days, "cycles_per_day": cycles / days,
            "apr_pct": total / plan["invest"] * 100 / days * 365, "max_drawdown": worst, "max_drawdown_pct": worst / plan["invest"] * 100,
            "time_in_range_pct": in_range / len(candles) * 100, "end_price": last, "start_price": price0, "inventory_qty_end": base,
            "max_inventory_value": max_inv_val, "stopped": stopped}


def suggest(candles, fee_pct, price):
    """Range and grid-count suggestions from recent candles (5th to 95th percentile of closes, widened by half an average candle)."""
    cl = sorted(c["c"] for c in candles)
    if len(cl) < 20:
        return {}
    lo, hi = cl[int(len(cl) * 0.05)], cl[int(len(cl) * 0.95) - 1]
    avg = sum((c["h"] - c["l"]) for c in candles) / len(candles)
    lo, hi = lo - avg / 2, hi + avg / 2
    span = (hi / lo - 1) * 100
    n_max = max(2, int(span / (2 * fee_pct * 2.5)))               # each cell earns at least 2.5x the round-trip fee
    daily = {}
    for c in candles:
        daily.setdefault(int(c["t"] // 86400), []).append(c)
    rng = [(max(x["h"] for x in v) / min(x["l"] for x in v) - 1) * 100 for v in daily.values() if len(v) >= 6]
    return {"lower": lo, "upper": hi, "range_pct": span, "max_useful_grids": min(100, n_max), "suggested_grids": max(2, min(100, n_max // 2, 40)),
            "avg_daily_range_pct": sum(rng) / len(rng) if rng else None, "price_inside": lo < price < hi}


# ------------------------------------------------------------------ live engine
class GridEngine:
    def __init__(self, client, notifier, clock=time.time):
        self.c, self.n, self.clock = client, notifier, clock
        self.lock = asyncio.Lock()

    @property
    def paused(self):
        return bool(store.kv_get("halted", False))

    def fee(self):
        return float(store.config()["spot_grid"]["fee_pct"])

    async def plan(self, cfg, with_history=True):
        sym = await self.c.sym("spot", cfg["symbol"])
        price = await self.c.price("spot", cfg["symbol"])
        p = compute_plan(cfg, price, sym, self.fee())
        p["symbol"] = cfg["symbol"]
        if with_history:
            try:
                out = {}
                for label, days in (("30d", 30), ("90d", 90)):
                    cs = await self.c.klines("spot", cfg["symbol"], "1h", min(1000, days * 24))
                    if len(cs) >= 48:
                        if label == "30d":
                            p["suggest"] = suggest(cs, self.fee(), float(price))
                            p["history_days"] = len(cs) / 24
                        if p.get("ok"):
                            # replay the same range and grid count from the first candle whose open price was inside the range
                            lo, hi = float(p["levels"][0]), float(p["levels"][-1])
                            j0 = next((j for j, c in enumerate(cs) if lo < c["o"] < hi), None)
                            if j0 is None or len(cs) - j0 < 24:
                                out[label] = {"note": "the price was outside this range for almost the whole period"}
                            else:
                                p2 = compute_plan(dict(cfg), cs[j0]["o"], sym, self.fee())
                                out[label] = dict(simulate(p2, cs[j0:], self.fee(), cfg), started_after_days=j0 / 24) if p2.get("ok") else {"note": "; ".join(p2["errors"])[:120]}
                p["simulation"] = out
            except BinanceError as e:
                p["simulation_error"] = e.msg
        return p

    async def start(self, cfg):
        gc = store.config()["spot_grid"]
        if not gc["enabled"]:
            return {"ok": False, "error": "the grid profile is switched off"}
        if self.paused:
            return {"ok": False, "error": "the kill switch is on (stop): resume first"}
        running = store.q("SELECT id, symbol FROM grids WHERE status='running'")
        if len(running) >= gc["max_grids"]:
            return {"ok": False, "error": f"{len(running)} grids already run (max {gc['max_grids']})"}
        if any(r["symbol"] == cfg["symbol"] for r in running):
            return {"ok": False, "error": f"a grid already runs on {cfg['symbol']}"}
        async with self.lock:
            sym = await self.c.sym("spot", cfg["symbol"])
            price = await self.c.price("spot", cfg["symbol"])
            pl = compute_plan(cfg, price, sym, self.fee())
            if not pl["ok"]:
                return {"ok": False, "error": "; ".join(pl["errors"])}
            acct = await self.c.s_account()
            quote_free = float(acct.get(sym.quote, {"free": 0})["free"])
            need = pl["invest"] * 1.001
            if quote_free < need:
                return {"ok": False, "error": f"needs {need:.2f} {sym.quote} free in the spot wallet, only {quote_free:.2f} available"}
            gid = secrets.token_hex(3)
            q, qb = D(pl["qty_str"]), D(pl["qty_buy_str"])
            state = {"cash_flow": 0.0, "base_held": 0.0, "buys": 0, "sells": 0, "cycles": 0, "profit": 0.0, "fees": 0.0, "errors": 0, "seq": 0, "qs": pl["qty"], "qb": pl["qty_buy"]}
            store.x("INSERT INTO grids (id, ts, symbol, cfg, status, inventory, invest, start_price, start_ts, state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (gid, self.clock(), cfg["symbol"], json.dumps(cfg), "starting", 0, pl["invest"], pl["price"], self.clock(), json.dumps(state)))
            f = self.fee() / 100
            try:
                if pl["full_cells"]:                               # the base currency for the sell orders is bought at market
                    Q = sym.qty(qb * len(pl["full_cells"]), market=True)
                    o = await self.c.s_new_order(symbol=cfg["symbol"], side="BUY", type="MARKET", quantity=Q, newClientOrderId=f"g{gid}init", newOrderRespType="FULL")
                    ex = D(o.get("executedQty", 0))
                    spent = D(o.get("cummulativeQuoteQty", 0))
                    if ex <= 0:
                        raise BinanceError(0, -1, "the initial market buy did not fill")
                    state["cash_flow"] -= float(spent)
                    state["base_held"] += float(ex) * (1 - f)
                    state["fees"] += float(ex) * f * pl["price"]
                cells = []
                levels = [D(x) for x in pl["levels"]]
                for i in pl["empty_cells"]:
                    cells.append((i, "BUY", levels[i], qb))
                for i in pl["full_cells"]:
                    cells.append((i, "SELL", levels[i + 1], q))
                for i, side, price_l, qty in cells:
                    store.x("INSERT INTO grid_orders (gid, level, side, price, qty, client_id, status, ts) VALUES (?,?,?,?,?,?,?,?)",
                            (gid, i, side, float(price_l), float(qty), f"g{gid}c{i}{side[0].lower()}0", "queued", self.clock()))
                store.x("UPDATE grids SET status='running', state=? WHERE id=?", (json.dumps(state), gid))
            except BinanceError as e:
                store.x("UPDATE grids SET status='failed', state=? WHERE id=?", (json.dumps(dict(state, error=e.msg)), gid))
                await self.n.send(f"<b>Grid {esc(cfg['symbol'])} could not start</b>: {esc(e.msg)}")
                return {"ok": False, "error": e.msg, "grid_id": gid}
        async with self.lock:
            await self._place_queued(gid)
        await self.n.send(f"<b>Grid started {esc(cfg['symbol'])}</b> {esc(fmt(pl['levels'][0]))} - {esc(fmt(pl['levels'][-1]))}, {pl['n']} grids, "
                          f"{pl['buy_orders']} buy / {pl['sell_orders']} sell orders, {pl['qty']} per sell order, investment {pl['invest']:.0f}", silent=True)
        return {"ok": True, "grid_id": gid, "plan": pl}

    async def _place_queued(self, gid):
        g = store.q("SELECT * FROM grids WHERE id=?", (gid,))[0]
        for o in store.q("SELECT * FROM grid_orders WHERE gid=? AND status='queued' ORDER BY id", (gid,)):
            try:
                sym = await self.c.sym("spot", g["symbol"])
                r = await self.c.s_new_order(symbol=g["symbol"], side=o["side"], type="LIMIT", timeInForce="GTC", quantity=sym.qty(D(repr(o["qty"]))),
                                             price=sym.price(D(repr(o["price"]))), newClientOrderId=o["client_id"], newOrderRespType="ACK")
                store.x("UPDATE grid_orders SET status='open', order_id=? WHERE id=?", (str(r["orderId"]), o["id"]))
            except BinanceError as e:
                if e.code == -2010 and "Duplicate" in e.msg:
                    store.x("UPDATE grid_orders SET status='open' WHERE id=?", (o["id"],))
                    continue
                st = json.loads(g["state"] or "{}")
                st["errors"] = st.get("errors", 0) + 1
                st["last_error"] = e.msg
                store.x("UPDATE grids SET state=? WHERE id=?", (json.dumps(st), gid))
                if st["errors"] in (3, 20):
                    await self.n.send(f"Grid {esc(g['symbol'])}: an order could not be placed ({esc(e.msg)}). Will retry.")
                break                                             # retry on the next tick

    async def tick_all(self):
        for g in store.q("SELECT id FROM grids WHERE status='running'"):
            try:
                await self.tick(g["id"])
            except Exception as e:
                store.event("warning", "grid", f"tick {g['id']}: {e}")

    async def tick(self, gid):
        async with self.lock:
            await self._tick(gid)

    async def _tick(self, gid):
        g = store.q("SELECT * FROM grids WHERE id=?", (gid,))[0]
        if g["status"] != "running":
            return
        cfg, st = json.loads(g["cfg"]), json.loads(g["state"] or "{}")
        sym = await self.c.sym("spot", g["symbol"])
        open_ids = {o["clientOrderId"] for o in await self.c.s_open_orders(g["symbol"])}
        price = float(await self.c.price("spot", g["symbol"]))
        f = self.fee() / 100
        st["last_price"] = price
        plan_levels = [float(x) for x in make_levels(cfg["lower"], cfg["upper"], int(cfg["grids"]), cfg.get("mode", "arithmetic"), sym)]
        # 1) detect fills
        for o in store.q("SELECT * FROM grid_orders WHERE gid=? AND status='open' ORDER BY id", (gid,)):
            if o["client_id"] in open_ids:
                continue
            try:
                r = await self.c.s_query(g["symbol"], o["client_id"])
            except BinanceError:
                continue
            if r["status"] == "FILLED":
                ex = float(r["executedQty"])
                avg = float(r["cummulativeQuoteQty"]) / ex if ex else o["price"]
                store.x("UPDATE grid_orders SET status='filled', fill_ts=?, fill_price=? WHERE id=?", (self.clock(), avg, o["id"]))
                i = o["level"]
                st["seq"] = st.get("seq", 0) + 1
                if o["side"] == "BUY":
                    st["cash_flow"] -= ex * avg
                    st["base_held"] += ex * (1 - f)
                    st["fees"] += ex * avg * f
                    st["buys"] += 1
                    store.x("INSERT INTO grid_orders (gid, level, side, price, qty, client_id, status, ts) VALUES (?,?,?,?,?,?,?,?)",
                            (gid, i, "SELL", plan_levels[i + 1], st["qs"], f"g{gid}c{i}s{st['seq']}", "queued", self.clock()))
                else:
                    rev = ex * avg * (1 - f)
                    st["cash_flow"] += rev
                    st["base_held"] -= ex
                    st["fees"] += ex * avg * f
                    st["sells"] += 1
                    q0 = st["qb"]
                    prof = rev - q0 * plan_levels[i]
                    st["cycles"] += 1
                    st["profit"] += prof
                    store.x("INSERT INTO grid_cycles (gid, ts, level, buy_price, sell_price, qty, profit, fees) VALUES (?,?,?,?,?,?,?,?)",
                            (gid, self.clock(), i, plan_levels[i], avg, ex, prof, ex * avg * f))
                    store.x("INSERT INTO grid_orders (gid, level, side, price, qty, client_id, status, ts) VALUES (?,?,?,?,?,?,?,?)",
                            (gid, i, "BUY", plan_levels[i], float(q0), f"g{gid}c{i}b{st['seq']}", "queued", self.clock()))
            elif r["status"] in ("CANCELED", "EXPIRED", "REJECTED"):
                store.x("UPDATE grid_orders SET status='canceled' WHERE id=?", (o["id"],))
                if True:
                    st["seq"] = st.get("seq", 0) + 1
                    store.x("INSERT INTO grid_orders (gid, level, side, price, qty, client_id, status, ts) VALUES (?,?,?,?,?,?,?,?)",
                            (gid, o["level"], o["side"], o["price"], o["qty"], f"g{gid}c{o['level']}{o['side'][0].lower()}{st['seq']}", "queued", self.clock()))
                    store.event("info", "grid", f"grid {gid} order at {o['price']} was cancelled outside the bot: placed again")
        store.x("UPDATE grids SET state=? WHERE id=?", (json.dumps(st), gid))
        # 2) place counter orders (unless the kill switch paused the grid)
        if not self.paused:
            await self._place_queued(gid)
        # 3) stop-loss / take-profit of the whole grid
        if cfg.get("stop_price") and price <= float(cfg["stop_price"]):
            await self._stop(gid, "stop-loss price reached", sell=cfg.get("sell_on_stop", True))
        elif cfg.get("take_profit_price") and price >= float(cfg["take_profit_price"]):
            await self._stop(gid, "take-profit price reached", sell=True)

    async def stop(self, gid, reason="user", sell=False):
        async with self.lock:
            return await self._stop(gid, reason, sell)

    async def _stop(self, gid, reason="user", sell=False):
        if True:
            r = store.q("SELECT * FROM grids WHERE id=?", (gid,))
            if not r or r[0]["status"] not in ("running", "starting"):
                return {"ok": False, "error": "grid is not running"}
            g = r[0]
            st = json.loads(g["state"] or "{}")
            errs = 0
            for o in store.q("SELECT * FROM grid_orders WHERE gid=? AND status IN ('open','queued')", (gid,)):
                if o["status"] == "open":
                    try:
                        await self.c.s_cancel(g["symbol"], origClientOrderId=o["client_id"])
                    except BinanceError as e:
                        if e.code != -2011:                       # -2011: it had just filled or was already gone
                            errs += 1
                store.x("UPDATE grid_orders SET status='canceled' WHERE id=?", (o["id"],))
            sold = None
            held = st.get("base_held", 0.0)
            if sell and held > 0:
                try:
                    sym = await self.c.sym("spot", g["symbol"])
                    acct = await self.c.s_account()
                    qty = sym.qty(min(D(repr(held)), acct.get(sym.base, {"free": D(0)})["free"]), market=True)
                    if qty > 0:
                        o = await self.c.s_new_order(symbol=g["symbol"], side="SELL", type="MARKET", quantity=qty, newOrderRespType="FULL", newClientOrderId=f"g{gid}exit")
                        got = float(o.get("cummulativeQuoteQty", 0))
                        f = self.fee() / 100
                        st["cash_flow"] += got * (1 - f)
                        st["base_held"] -= float(qty)
                        sold = float(qty)
                except BinanceError as e:
                    await self.n.send(f"Grid {esc(g['symbol'])}: orders cancelled but the market sell of the inventory failed ({esc(e.msg)}). The inventory is kept.")
            store.x("UPDATE grids SET status='stopped', stop_ts=?, state=? WHERE id=?", (self.clock(), json.dumps(dict(st, stop_reason=reason)), gid))
        px = float(await self.c.price("spot", g["symbol"]))
        pnl = st.get("cash_flow", 0) + st.get("base_held", 0) * px
        await self.n.send(f"<b>Grid stopped {esc(g['symbol'])}</b> ({esc(reason)}). Result {pnl:+.2f} USDT, grid profit {st.get('profit', 0):+.2f}. "
                          + (f"Sold {sold} at market." if sold else (f"Inventory kept: {st.get('base_held', 0):.6g}." if st.get("base_held", 0) > 0 else "")), silent=False)
        return {"ok": True, "cancel_errors": errs, "sold": sold, "inventory": st.get("base_held", 0.0) if not sold else st.get("base_held", 0.0)}

    async def stop_all(self, reason="kill switch", sell=False):
        out = []
        for g in store.q("SELECT id FROM grids WHERE status IN ('running','starting')"):
            out.append(await self.stop(g["id"], reason, sell))
        return out

    # ------------------------------------------------------------------ analytics
    async def analytics(self, gid):
        r = store.q("SELECT * FROM grids WHERE id=?", (gid,))
        if not r:
            return {"ok": False, "error": "unknown grid"}
        g = r[0]
        cfg, st = json.loads(g["cfg"]), json.loads(g["state"] or "{}")
        try:
            price = float(await self.c.price("spot", g["symbol"]))
        except BinanceError:
            price = st.get("last_price") or g["start_price"]
        invest = g["invest"]
        end = g["stop_ts"] or self.clock()
        days = max((end - g["start_ts"]) / 86400, 1e-9)
        total = st.get("cash_flow", 0) + st.get("base_held", 0) * price
        lo, hi = float(cfg["lower"]), float(cfg["upper"])
        hold = invest / g["start_price"] * (price - g["start_price"])
        cyc = store.q("SELECT * FROM grid_cycles WHERE gid=? ORDER BY id", (gid,))
        daily = {}
        for c in cyc:
            k = time.strftime("%Y-%m-%d", time.gmtime(c["ts"]))
            daily[k] = daily.get(k, 0) + c["profit"]
        orders = store.q("SELECT level, side, price, qty, status FROM grid_orders WHERE gid=? AND status IN ('open','queued') ORDER BY price", (gid,))
        for o in orders:
            o["distance_pct"] = (o["price"] / price - 1) * 100
        return {"ok": True, "id": gid, "symbol": g["symbol"], "status": g["status"], "cfg": cfg, "price": price, "start_price": g["start_price"], "invest": invest,
                "running_days": days, "grid_profit": st.get("profit", 0.0), "cycles": st.get("cycles", 0), "buys": st.get("buys", 0), "sells": st.get("sells", 0),
                "fees": st.get("fees", 0.0), "total_pnl": total, "total_return_pct": total / invest * 100 if invest else 0,
                "apr_pct": (total / invest * 100 / days * 365) if invest and days >= 1 else None, "profit_per_cycle": (st.get("profit", 0.0) / st["cycles"]) if st.get("cycles") else None,
                "cycles_per_day": (st.get("cycles", 0) / days) if days >= 1 / 24 else None, "inventory_qty": st.get("base_held", 0.0), "inventory_value": st.get("base_held", 0.0) * price,
                "cash": invest + st.get("cash_flow", 0), "hold_pnl": hold, "vs_hold": total - hold,
                "range": {"lower": lo, "upper": hi, "position_pct": (price - lo) / (hi - lo) * 100 if hi > lo else None,
                          "status": "below the range" if price < lo else ("above the range" if price > hi else "inside the range")},
                "daily_profit": [{"day": k, "profit": v} for k, v in sorted(daily.items())], "open_orders": orders, "last_cycles": cyc[-20:][::-1],
                "errors": st.get("errors", 0), "last_error": st.get("last_error"), "stop_reason": st.get("stop_reason")}

    def summary(self):
        out = []
        for g in store.q("SELECT * FROM grids ORDER BY ts DESC LIMIT 30"):
            st = json.loads(g["state"] or "{}")
            cfg = json.loads(g["cfg"])
            out.append({"id": g["id"], "symbol": g["symbol"], "status": g["status"], "lower": cfg["lower"], "upper": cfg["upper"], "grids": cfg["grids"], "invest": g["invest"],
                        "cycles": st.get("cycles", 0), "grid_profit": st.get("profit", 0.0), "started": g["start_ts"], "last_price": st.get("last_price")})
        return out
