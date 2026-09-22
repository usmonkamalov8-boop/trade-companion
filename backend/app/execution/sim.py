"""A small simulated Binance (spot + USD-M futures) with the same endpoints and error codes the engine uses.

Used for paper trading (real prices, fake money) and for the automated tests. It is a model, not the exchange: it fills limit
orders when the price reaches them, triggers conditional orders, nets positions, charges fees, enforces symbol filters and
margin, and cancels reduce-only / close-position orders when a position closes. Liquidation is not simulated."""
import time
from decimal import Decimal, ROUND_DOWN

from .binance import BinanceError, D, Sym, fmt

FUT_TAKER, FUT_MAKER, SPOT_FEE = D("0.0005"), D("0.0002"), D("0.001")


def _info(symbol, base, quote, tick, step, min_qty, min_notional, spot=False):
    f = [{"filterType": "PRICE_FILTER", "tickSize": tick}, {"filterType": "LOT_SIZE", "stepSize": step, "minQty": min_qty, "maxQty": "1000000"},
         {"filterType": "MARKET_LOT_SIZE", "stepSize": step, "minQty": min_qty, "maxQty": "1000000"}]
    f.append({"filterType": "NOTIONAL", "minNotional": min_notional} if spot else {"filterType": "MIN_NOTIONAL", "notional": min_notional})
    return {"symbol": symbol, "baseAsset": base, "quoteAsset": quote, "status": "TRADING", "filters": f}


DEFAULT_SYMBOLS = [("BTCUSDT", "BTC", "0.1", "0.001", "0.001", "100"), ("ETHUSDT", "ETH", "0.01", "0.001", "0.001", "20"),
                   ("SOLUSDT", "SOL", "0.001", "1", "1", "5"), ("DOGEUSDT", "DOGE", "0.00001", "1", "1", "5")]


SPOT_SYMBOLS = [("BTCUSDT", "BTC", "0.01", "0.00001", "0.00001", "5"), ("ETHUSDT", "ETH", "0.01", "0.0001", "0.0001", "5"),
                ("SOLUSDT", "SOL", "0.01", "0.001", "0.001", "5"), ("DOGEUSDT", "DOGE", "0.00001", "1", "1", "5")]


class Sim:
    def __init__(self, fut_wallet="10000", spot_usdt="10000", symbols=None):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.fut_info = {s[0]: _info(s[0], s[1], "USDT", s[2], s[3], s[4], s[5]) for s in self.symbols}
        self.spot_info = {s[0]: _info(s[0], s[1], "USDT", s[2], s[3], s[4], s[5], spot=True) for s in (SPOT_SYMBOLS if symbols is None else symbols)}
        self.prices = {"fut": {}, "spot": {}}
        self.f_wallet = D(fut_wallet)
        self.f_pos, self.f_lev, self.f_margin = {}, {}, {}
        self.f_orders, self.f_algo, self.f_trades = {}, {}, []
        self.s_bal = {"USDT": {"free": D(spot_usdt), "locked": D(0)}}
        self.s_orders, self.s_trades = {}, []
        self.klines = {}
        self.hedge = False
        self.fail = {}                       # (METHOD, path) -> list of BinanceError raised one by one
        self.calls = []
        self._id = 1000
        self._tid = 0
        self.restrictions = {"ipRestrict": True, "enableWithdrawals": False, "enableInternalTransfer": False, "enableFutures": True,
                             "enableSpotAndMarginTrading": True, "enableReading": True}

    def load_info(self, fut_symbols, spot_symbols):
        """Use the real exchange rules (from public exchangeInfo) so paper trading rounds and rejects like the real thing."""
        self.fut_info = {x["symbol"]: x for x in fut_symbols if x.get("quoteAsset") == "USDT" and x.get("status") == "TRADING"}
        self.spot_info = {x["symbol"]: x for x in spot_symbols if x.get("quoteAsset") == "USDT" and x.get("status") == "TRADING"}

    # ------------------------------------------------------------------ helpers
    def nid(self):
        self._id += 1
        return self._id

    def sym(self, market, symbol):
        info = (self.fut_info if market == "fut" else self.spot_info).get(symbol)
        if not info:
            raise BinanceError(400, -1121, "Invalid symbol.")
        return Sym(info)

    def px(self, market, symbol):
        p = self.prices[market].get(symbol)
        if p is None:
            raise BinanceError(400, -1121, f"no price for {symbol}")
        return p

    def _filters(self, market, sy, price, qty, kind, reduce=False):
        if D(price) % sy.tick != 0 and kind != "MARKET":
            raise BinanceError(400, -1013, "Filter failure: PRICE_FILTER")
        if D(qty) % (sy.mstep if kind == "MARKET" else sy.step) != 0:
            raise BinanceError(400, -1013, "Filter failure: LOT_SIZE")
        if D(qty) < (sy.mmin_qty if kind == "MARKET" else sy.min_qty) or D(qty) <= 0:
            raise BinanceError(400, -1013, "Filter failure: LOT_SIZE")
        if not reduce and D(qty) * D(price) < sy.min_notional:
            raise BinanceError(400, -1013, "Filter failure: NOTIONAL" if market == "spot" else "Filter failure: MIN_NOTIONAL")

    # ------------------------------------------------------------------ dispatch
    async def handle(self, market, method, path, p):
        self.calls.append((market, method, path, dict(p)))
        q = self.fail.get((method, path))
        if q:
            e = q.pop(0)
            if not q:
                del self.fail[(method, path)]
            raise e
        if market == "spot":
            return self._spot(method, path, p)
        return self._fut(method, path, p)

    # ------------------------------------------------------------------ price movement
    def set_price(self, market, symbol, price):
        """Move the market to `price`, filling everything the price passes through, in path order."""
        new = D(price)
        old = self.prices[market].get(symbol)
        self.prices[market][symbol] = new
        if old is None or old == new:
            return
        rising = new > old
        if market == "fut":
            # limit orders
            hits = [o for o in self.f_orders.values() if o["symbol"] == symbol and o["status"] == "NEW" and o["type"] == "LIMIT"
                    and ((o["side"] == "BUY" and D(o["price"]) >= min(old, new) and D(o["price"]) <= max(old, new) and not rising)
                         or (o["side"] == "SELL" and D(o["price"]) >= min(old, new) and D(o["price"]) <= max(old, new) and rising))]
            for o in sorted(hits, key=lambda o: D(o["price"]), reverse=not rising):
                if o["status"] == "NEW":
                    self._f_fill(o, D(o["price"]), maker=True)
            for a in [a for a in self.f_algo.values() if a["symbol"] == symbol and a["algoStatus"] == "NEW"]:
                trig = D(a["triggerPrice"])
                stop = a["orderType"] in ("STOP_MARKET", "STOP")
                fire = ((a["side"] == "SELL" and stop and new <= trig) or (a["side"] == "BUY" and stop and new >= trig)
                        or (a["side"] == "SELL" and not stop and new >= trig) or (a["side"] == "BUY" and not stop and new <= trig))
                if fire and a["algoStatus"] == "NEW":
                    self._f_trigger(a, new)
        else:
            hits = [o for o in self.s_orders.values() if o["symbol"] == symbol and o["status"] == "NEW"
                    and ((o["side"] == "BUY" and not rising and min(old, new) <= D(o["price"]) <= max(old, new))
                         or (o["side"] == "SELL" and rising and min(old, new) <= D(o["price"]) <= max(old, new)))]
            for o in sorted(hits, key=lambda o: D(o["price"]), reverse=not rising):
                if o["status"] == "NEW":
                    self._s_fill(o, D(o["price"]))

    def walk(self, market, symbol, prices):
        for p in prices:
            self.set_price(market, symbol, p)

    # ------------------------------------------------------------------ futures
    def _f_upnl(self):
        t = D(0)
        for s, pos in self.f_pos.items():
            if pos["amt"] != 0:
                t += (self.prices["fut"].get(s, pos["entry"]) - pos["entry"]) * pos["amt"]
        return t

    def _f_margin_used(self):
        return sum((abs(pos["amt"]) * pos["entry"] / D(self.f_lev.get(s, 20)) for s, pos in self.f_pos.items() if pos["amt"] != 0), D(0))

    def _f_fill(self, o, price, maker=False):
        sy = self.sym("fut", o["symbol"])
        qty = D(o["origQty"])
        side = 1 if o["side"] == "BUY" else -1
        pos = self.f_pos.setdefault(o["symbol"], {"amt": D(0), "entry": D(0)})
        fee = qty * price * (FUT_MAKER if maker else FUT_TAKER)
        realized = D(0)
        old = pos["amt"]
        if old == 0 or (old > 0) == (side > 0):
            need = qty * price / D(self.f_lev.get(o["symbol"], 20))
            avail = self.f_wallet + self._f_upnl() - self._f_margin_used()
            if need > avail and not o.get("_rest"):
                raise BinanceError(400, -2019, "Margin is insufficient.")
            pos["entry"] = (abs(old) * pos["entry"] + qty * price) / (abs(old) + qty)
            pos["amt"] = old + side * qty
        else:
            closed = min(abs(old), qty)
            realized = (price - pos["entry"]) * closed * (1 if old > 0 else -1)
            rest = qty - closed
            pos["amt"] = old + side * closed
            if rest > 0:                              # flips: the rest opens a new position
                pos["entry"], pos["amt"] = price, side * rest
            elif pos["amt"] == 0:
                pos["entry"] = D(0)
        self.f_wallet += realized - fee
        o.update(status="FILLED", executedQty=fmt(qty), avgPrice=fmt(price), cumQuote=fmt(qty * price), updateTime=int(time.time() * 1000))
        self._tid += 1
        self.f_trades.append({"id": self._tid, "orderId": o["orderId"], "symbol": o["symbol"], "side": o["side"], "price": fmt(price), "qty": fmt(qty),
                              "commission": fmt(fee), "realizedPnl": fmt(realized), "maker": maker, "time": int(time.time() * 1000)})
        if self.f_pos[o["symbol"]]["amt"] == 0:
            self._f_position_closed(o["symbol"])
        return o

    def _f_position_closed(self, symbol):
        for o in self.f_orders.values():
            if o["symbol"] == symbol and o["status"] == "NEW" and o.get("reduceOnly"):
                o["status"] = "CANCELED"
        for a in self.f_algo.values():
            if a["symbol"] == symbol and a["algoStatus"] == "NEW" and (a.get("closePosition") or a.get("reduceOnly")):
                a["algoStatus"] = "CANCELED"

    def _f_trigger(self, a, price):
        pos = self.f_pos.get(a["symbol"], {"amt": D(0)})
        a["algoStatus"] = "TRIGGERED"
        if pos["amt"] == 0:
            a["algoStatus"] = "CANCELED"
            return
        qty = abs(pos["amt"]) if a.get("closePosition") else min(abs(pos["amt"]), D(a["quantity"]))
        o = {"orderId": self.nid(), "symbol": a["symbol"], "side": a["side"], "type": "MARKET", "origQty": fmt(qty), "status": "NEW",
             "reduceOnly": True, "clientOrderId": a["clientAlgoId"] + "-t", "price": "0"}
        self.f_orders[o["orderId"]] = o
        self._f_fill(o, price)
        a["algoStatus"] = "FINISHED"

    def _fut(self, method, path, p):
        if path == "/fapi/v1/time":
            return {"serverTime": int(time.time() * 1000)}
        if path == "/fapi/v1/exchangeInfo":
            return {"symbols": list(self.fut_info.values())}
        if path == "/fapi/v1/ticker/price":
            return {"symbol": p["symbol"], "price": fmt(self.px("fut", p["symbol"]))}
        if path == "/fapi/v1/klines":
            return self._klines("fut", p)
        if path == "/fapi/v2/balance":
            up = self._f_upnl()
            return [{"asset": "USDT", "balance": fmt(self.f_wallet), "availableBalance": fmt(max(D(0), self.f_wallet + up - self._f_margin_used())),
                     "crossUnPnl": fmt(up)}]
        if path == "/fapi/v1/positionSide/dual":
            if method == "GET":
                return {"dualSidePosition": self.hedge}
            self.hedge = str(p["dualSidePosition"]).lower() == "true"
            return {"code": 200, "msg": "success"}
        if path == "/fapi/v2/positionRisk":
            out = []
            for s in self.fut_info:
                pos = self.f_pos.get(s, {"amt": D(0), "entry": D(0)})
                mark = self.prices["fut"].get(s, D(0))
                lev = self.f_lev.get(s, 20)
                liq = pos["entry"] * (1 - 1 / D(lev) + D("0.005")) if pos["amt"] > 0 else (pos["entry"] * (1 + 1 / D(lev) - D("0.005")) if pos["amt"] < 0 else D(0))
                out.append({"symbol": s, "positionAmt": fmt(pos["amt"]), "entryPrice": fmt(pos["entry"]), "markPrice": fmt(mark),
                            "unRealizedProfit": fmt((mark - pos["entry"]) * pos["amt"] if pos["amt"] else 0), "liquidationPrice": fmt(liq),
                            "leverage": str(lev), "marginType": self.f_margin.get(s, "cross").lower().replace("crossed", "cross"),
                            "positionSide": "BOTH", "notional": fmt(pos["amt"] * mark)})
            return out
        if path == "/fapi/v1/openOrders":
            return [dict(o) for o in self.f_orders.values() if o["status"] == "NEW" and (not p.get("symbol") or o["symbol"] == p["symbol"])]
        if path == "/fapi/v1/openAlgoOrders":
            return [dict(a) for a in self.f_algo.values() if a["algoStatus"] == "NEW" and (not p.get("symbol") or a["symbol"] == p["symbol"])]
        if path == "/fapi/v1/leverage":
            if not 1 <= int(p["leverage"]) <= 125:
                raise BinanceError(400, -4028, "Leverage is not valid")
            self.f_lev[p["symbol"]] = int(p["leverage"])
            return {"leverage": int(p["leverage"]), "maxNotionalValue": "1000000", "symbol": p["symbol"]}
        if path == "/fapi/v1/marginType":
            cur = self.f_margin.get(p["symbol"], "CROSSED")
            if cur == p["marginType"]:
                raise BinanceError(400, -4046, "No need to change margin type.")
            if any(o["symbol"] == p["symbol"] and o["status"] == "NEW" for o in self.f_orders.values()):
                raise BinanceError(400, -4048, "Margin type cannot be changed if there exists open orders.")
            if self.f_pos.get(p["symbol"], {"amt": 0})["amt"] != 0:
                raise BinanceError(400, -4047, "Margin type cannot be changed if there exists position.")
            self.f_margin[p["symbol"]] = p["marginType"]
            return {"code": 200, "msg": "success"}
        if path == "/fapi/v1/order" and method == "POST":
            return self._f_new(p)
        if path == "/fapi/v1/order" and method == "GET":
            for o in self.f_orders.values():
                if o["symbol"] == p["symbol"] and (o["clientOrderId"] == p.get("origClientOrderId") or str(o["orderId"]) == str(p.get("orderId"))):
                    return dict(o)
            raise BinanceError(400, -2013, "Order does not exist.")
        if path == "/fapi/v1/order" and method == "DELETE":
            for o in self.f_orders.values():
                if o["symbol"] == p["symbol"] and o["status"] == "NEW" and (o["clientOrderId"] == p.get("origClientOrderId") or str(o["orderId"]) == str(p.get("orderId"))):
                    o["status"] = "CANCELED"
                    return dict(o)
            raise BinanceError(400, -2011, "Unknown order sent.")
        if path == "/fapi/v1/allOpenOrders":
            for o in self.f_orders.values():
                if o["symbol"] == p["symbol"] and o["status"] == "NEW":
                    o["status"] = "CANCELED"
            return {"code": 200, "msg": "The operation of cancel all open order is done."}
        if path == "/fapi/v1/algoOrder" and method == "POST":
            return self._f_new_algo(p)
        if path == "/fapi/v1/algoOrder" and method == "DELETE":
            for a in self.f_algo.values():
                if a["algoStatus"] == "NEW" and (str(a["algoId"]) == str(p.get("algoId")) or a["clientAlgoId"] == p.get("clientAlgoId")):
                    a["algoStatus"] = "CANCELED"
                    return {"algoId": a["algoId"], "clientAlgoId": a["clientAlgoId"], "code": "200", "msg": "success"}
            raise BinanceError(400, -2011, "Unknown order sent.")
        if path == "/fapi/v1/algoOpenOrders":
            for a in self.f_algo.values():
                if a["symbol"] == p["symbol"] and a["algoStatus"] == "NEW":
                    a["algoStatus"] = "CANCELED"
            return {"code": 200, "msg": "The operation of cancel all open order is done."}
        if path == "/fapi/v1/userTrades":
            return [t for t in self.f_trades if t["symbol"] == p["symbol"]][-int(p.get("limit", 200)):]
        raise BinanceError(404, -1102, f"sim: unknown futures endpoint {method} {path}")

    def _f_new(self, p):
        if p["type"] not in ("LIMIT", "MARKET"):
            raise BinanceError(400, -4120, "Order type not supported for this endpoint. Please use the Algo Order API endpoints instead.")
        sy = self.sym("fut", p["symbol"])
        cur = self.px("fut", p["symbol"])
        qty = D(p["quantity"])
        reduce = str(p.get("reduceOnly", "false")).lower() == "true"
        price = D(p["price"]) if p["type"] == "LIMIT" else cur
        self._filters("fut", sy, price, qty, p["type"], reduce)
        pos = self.f_pos.get(p["symbol"], {"amt": D(0)})
        side = 1 if p["side"] == "BUY" else -1
        if reduce and (pos["amt"] == 0 or (pos["amt"] > 0) == (side > 0) or qty > abs(pos["amt"])):
            raise BinanceError(400, -2022, "ReduceOnly Order is rejected.")
        cid = p.get("newClientOrderId") or f"sim{self.nid()}"
        if any(o["clientOrderId"] == cid and o["status"] == "NEW" for o in self.f_orders.values()):
            raise BinanceError(400, -4015, "Client order id is not valid.")
        o = {"orderId": self.nid(), "symbol": p["symbol"], "side": p["side"], "type": p["type"], "origQty": fmt(qty), "price": fmt(price) if p["type"] == "LIMIT" else "0",
             "status": "NEW", "clientOrderId": cid, "reduceOnly": reduce, "executedQty": "0", "avgPrice": "0", "timeInForce": p.get("timeInForce", "GTC"),
             "updateTime": int(time.time() * 1000)}
        self.f_orders[o["orderId"]] = o
        marketable = p["type"] == "MARKET" or (p["side"] == "BUY" and price >= cur) or (p["side"] == "SELL" and price <= cur)
        if not marketable:
            o["_rest"] = True                # margin for a resting order is reserved when it is placed
        if marketable:
            try:
                self._f_fill(o, cur, maker=False)
            except BinanceError:
                del self.f_orders[o["orderId"]]
                raise
        elif str(p.get("timeInForce", "GTC")) == "GTX":
            del self.f_orders[o["orderId"]]
            raise BinanceError(400, -5022, "Due to the order could not be executed as maker, the Post Only order will be rejected.")
        return dict(o)

    def _f_new_algo(self, p):
        if p.get("algoType") != "CONDITIONAL":
            raise BinanceError(400, -1102, "algoType required")
        sy = self.sym("fut", p["symbol"])
        cur = self.px("fut", p["symbol"])
        trig = D(p["triggerPrice"])
        if trig % sy.tick != 0:
            raise BinanceError(400, -1013, "Filter failure: PRICE_FILTER")
        stop = p["type"] in ("STOP_MARKET", "STOP")
        if ((p["side"] == "SELL" and stop) or (p["side"] == "BUY" and not stop)) and trig >= cur:
            raise BinanceError(400, -2021, "Order would immediately trigger.")
        if ((p["side"] == "BUY" and stop) or (p["side"] == "SELL" and not stop)) and trig <= cur:
            raise BinanceError(400, -2021, "Order would immediately trigger.")
        close = str(p.get("closePosition", "false")).lower() == "true"
        if close and p.get("quantity"):
            raise BinanceError(400, -1106, "quantity cannot be sent with closePosition")
        if not close and not p.get("quantity"):
            raise BinanceError(400, -1102, "quantity required")
        cid = p.get("clientAlgoId") or f"simalgo{self.nid()}"
        if any(a["clientAlgoId"] == cid and a["algoStatus"] == "NEW" for a in self.f_algo.values()):
            raise BinanceError(400, -4116, "ClientOrderId is duplicated.")
        a = {"algoId": self.nid(), "clientAlgoId": cid, "algoType": "CONDITIONAL", "orderType": p["type"], "symbol": p["symbol"], "side": p["side"],
             "positionSide": "BOTH", "quantity": p.get("quantity", "0"), "algoStatus": "NEW", "triggerPrice": fmt(trig), "closePosition": close,
             "reduceOnly": str(p.get("reduceOnly", "false")).lower() == "true", "workingType": p.get("workingType", "CONTRACT_PRICE"),
             "createTime": int(time.time() * 1000)}
        self.f_algo[a["algoId"]] = a
        return dict(a)

    # ------------------------------------------------------------------ spot
    def _bal(self, asset):
        return self.s_bal.setdefault(asset, {"free": D(0), "locked": D(0)})

    def _s_fill(self, o, price):
        sy = self.sym("spot", o["symbol"])
        qty = D(o["origQty"])
        base, quote = self._bal(sy.base), self._bal(sy.quote)
        if o["side"] == "BUY":
            locked = qty * D(o["price"]) if o["type"] != "MARKET" else D(0)
            quote["locked"] -= locked
            quote["free"] += locked - qty * price if o["type"] != "MARKET" else -(qty * price)
            fee = qty * SPOT_FEE
            base["free"] += qty - fee
            fee_asset = sy.base
        else:
            if o["type"] != "MARKET":
                base["locked"] -= qty
            else:
                base["free"] -= qty
            fee = qty * price * SPOT_FEE
            quote["free"] += qty * price - fee
            fee_asset = sy.quote
        o.update(status="FILLED", executedQty=fmt(qty), cummulativeQuoteQty=fmt(qty * price), updateTime=int(time.time() * 1000))
        self._tid += 1
        self.s_trades.append({"id": self._tid, "orderId": o["orderId"], "symbol": o["symbol"], "price": fmt(price), "qty": fmt(qty), "quoteQty": fmt(qty * price),
                              "commission": fmt(fee), "commissionAsset": fee_asset, "isBuyer": o["side"] == "BUY", "isMaker": o["type"] != "MARKET",
                              "time": int(time.time() * 1000)})

    def _spot(self, method, path, p):
        if path == "/api/v3/exchangeInfo":
            return {"symbols": [self.spot_info[p["symbol"]]] if p.get("symbol") in self.spot_info else list(self.spot_info.values())}
        if path == "/api/v3/ticker/price":
            return {"symbol": p["symbol"], "price": fmt(self.px("spot", p["symbol"]))}
        if path == "/api/v3/klines":
            return self._klines("spot", p)
        if path == "/sapi/v1/account/apiRestrictions":
            return dict(self.restrictions)
        if path == "/api/v3/account":
            return {"balances": [{"asset": a, "free": fmt(b["free"]), "locked": fmt(b["locked"])} for a, b in self.s_bal.items()]}
        if path == "/api/v3/order" and method == "POST":
            return self._s_new(p)
        if path == "/api/v3/order" and method == "GET":
            for o in self.s_orders.values():
                if o["symbol"] == p["symbol"] and (o["clientOrderId"] == p.get("origClientOrderId") or str(o["orderId"]) == str(p.get("orderId"))):
                    return dict(o)
            raise BinanceError(400, -2013, "Order does not exist.")
        if path == "/api/v3/order" and method == "DELETE":
            for o in self.s_orders.values():
                if o["symbol"] == p["symbol"] and o["status"] == "NEW" and (o["clientOrderId"] == p.get("origClientOrderId") or str(o["orderId"]) == str(p.get("orderId"))):
                    self._s_cancel(o)
                    return dict(o)
            raise BinanceError(400, -2011, "Unknown order sent.")
        if path == "/api/v3/openOrders" and method == "DELETE":
            out = []
            for o in self.s_orders.values():
                if o["symbol"] == p["symbol"] and o["status"] == "NEW":
                    self._s_cancel(o)
                    out.append(dict(o))
            return out
        if path == "/api/v3/openOrders":
            return [dict(o) for o in self.s_orders.values() if o["status"] == "NEW" and (not p.get("symbol") or o["symbol"] == p["symbol"])]
        if path == "/api/v3/myTrades":
            return [t for t in self.s_trades if t["symbol"] == p["symbol"]][-int(p.get("limit", 500)):]
        raise BinanceError(404, -1102, f"sim: unknown spot endpoint {method} {path}")

    def _s_cancel(self, o):
        sy = self.sym("spot", o["symbol"])
        if o["side"] == "BUY":
            b = self._bal(sy.quote)
            amt = D(o["origQty"]) * D(o["price"])
        else:
            b = self._bal(sy.base)
            amt = D(o["origQty"])
        b["locked"] -= amt
        b["free"] += amt
        o["status"] = "CANCELED"

    def _s_new(self, p):
        sy = self.sym("spot", p["symbol"])
        cur = self.px("spot", p["symbol"])
        typ = p["type"]
        if typ not in ("LIMIT", "MARKET", "LIMIT_MAKER"):
            raise BinanceError(400, -1116, "Invalid orderType.")
        qty = D(p["quantity"]) if p.get("quantity") else (D(p["quoteOrderQty"]) / cur).quantize(sy.step, rounding=ROUND_DOWN)
        price = D(p["price"]) if typ != "MARKET" else cur
        self._filters("spot", sy, price, qty, "MARKET" if typ == "MARKET" else "LIMIT")
        base, quote = self._bal(sy.base), self._bal(sy.quote)
        cid = p.get("newClientOrderId") or f"sims{self.nid()}"
        if any(o["clientOrderId"] == cid for o in self.s_orders.values()):
            raise BinanceError(400, -2010, "Duplicate clientOrderId.")
        need_q, need_b = qty * price, qty
        if p["side"] == "BUY" and quote["free"] < need_q or p["side"] == "SELL" and base["free"] < need_b:
            raise BinanceError(400, -2010, "Account has insufficient balance for requested action.")
        marketable = typ == "MARKET" or (p["side"] == "BUY" and price >= cur) or (p["side"] == "SELL" and price <= cur)
        if typ == "LIMIT_MAKER" and marketable:
            raise BinanceError(400, -2010, "Order would immediately match and take.")
        o = {"orderId": self.nid(), "symbol": p["symbol"], "side": p["side"], "type": typ, "origQty": fmt(qty), "price": fmt(price) if typ != "MARKET" else "0",
             "status": "NEW", "clientOrderId": cid, "executedQty": "0", "cummulativeQuoteQty": "0", "time": int(time.time() * 1000), "updateTime": int(time.time() * 1000)}
        self.s_orders[o["orderId"]] = o
        if marketable:
            if typ != "MARKET":
                (quote if p["side"] == "BUY" else base)["locked"] += need_q if p["side"] == "BUY" else need_b
                (quote if p["side"] == "BUY" else base)["free"] -= need_q if p["side"] == "BUY" else need_b
            self._s_fill(o, cur)
        else:
            if p["side"] == "BUY":
                quote["free"] -= need_q
                quote["locked"] += need_q
            else:
                base["free"] -= need_b
                base["locked"] += need_b
        return dict(o)

    def _klines(self, market, p):
        rows = self.klines.get((market, p["symbol"]), [])
        return [[int(r["t"] * 1000), str(r["o"]), str(r["h"]), str(r["l"]), str(r["c"]), str(r.get("v", 1))] for r in rows][-int(p.get("limit", 1000)):]
