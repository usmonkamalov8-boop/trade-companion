"""Binance REST client (spot + USD-M futures) and symbol filter helpers.

Facts this code relies on (checked against the Binance developer docs, Sept 2026):
- Futures conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, trailing) MUST use POST /fapi/v1/algoOrder with algoType=CONDITIONAL;
  the old /fapi/v1/order rejects them with -4120. Open ones: GET /fapi/v1/openAlgoOrders. Cancel: DELETE /fapi/v1/algoOrder,
  DELETE /fapi/v1/algoOpenOrders (per symbol).
- Regular futures orders: POST /fapi/v1/order (LIMIT, MARKET). Leverage: POST /fapi/v1/leverage. Margin: POST /fapi/v1/marginType.
- Key permissions: GET /sapi/v1/account/apiRestrictions (enableWithdrawals, ipRestrict, enableFutures, ...)."""
import asyncio, hashlib, hmac, json, time, urllib.parse
from decimal import Decimal, ROUND_DOWN, ROUND_UP

import httpx

BASES = {"live": {"spot": "https://api.binance.com", "fut": "https://fapi.binance.com"},
         "testnet": {"spot": "https://testnet.binance.vision", "fut": "https://testnet.binancefuture.com"}}


class BinanceError(Exception):
    def __init__(self, status, code, msg):
        super().__init__(f"Binance {status} {code}: {msg}")
        self.status, self.code, self.msg = status, code, msg


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def fmt(d):
    """Decimal -> plain string (no exponent), the form the API wants."""
    d = D(d)
    s = format(d.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".") or "0"


class Sym:
    """Trading rules of one symbol (tick, step, minimums)."""

    def __init__(self, info):
        self.symbol = info["symbol"]
        self.base, self.quote = info.get("baseAsset"), info.get("quoteAsset")
        self.status = info.get("status", "TRADING")
        f = {x["filterType"]: x for x in info.get("filters", [])}
        self.tick = D(f.get("PRICE_FILTER", {}).get("tickSize", "0.01"))
        lot = f.get("LOT_SIZE", {})
        self.step, self.min_qty, self.max_qty = D(lot.get("stepSize", "0.001")), D(lot.get("minQty", "0")), D(lot.get("maxQty", "1e12"))
        mk = f.get("MARKET_LOT_SIZE", {})
        self.mstep, self.mmin_qty = D(mk.get("stepSize", str(self.step))), D(mk.get("minQty", str(self.min_qty)))
        mn = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        self.min_notional = D(mn.get("minNotional") or mn.get("notional") or "5")

    def price(self, p, up=False):
        q = (D(p) / self.tick).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
        return q * self.tick

    def qty(self, q, market=False):
        step = self.mstep if market else self.step
        return (D(q) / step).to_integral_value(rounding=ROUND_DOWN) * step

    def qty_up(self, q, market=False):
        step = self.mstep if market else self.step
        return (D(q) / step).to_integral_value(rounding=ROUND_UP) * step

    def check(self, price, qty, market=False):
        """Reasons an order of this size would be rejected by the exchange (empty list = fine)."""
        out = []
        q, p = D(qty), D(price)
        if q < (self.mmin_qty if market else self.min_qty) or q <= 0:
            out.append(f"quantity {fmt(q)} is below the minimum {fmt(self.mmin_qty if market else self.min_qty)}")
        if q > self.max_qty:
            out.append(f"quantity above the maximum {fmt(self.max_qty)}")
        if q * p < self.min_notional:
            out.append(f"order value {fmt(q * p)} is below the minimum {fmt(self.min_notional)}")
        return out


class Client:
    def __init__(self, key="", secret="", env="live", sim=None, timeout=15):
        self.key, self.secret, self.env, self.sim = key, secret, env, sim
        self.base = BASES.get(env, BASES["live"])
        self.offset = 0
        self.timeout = timeout
        self.paused_until = 0.0
        self.last_error = None
        self._info = {}
        self._info_ts = {}
        self._http = None

    # ------------------------------------------------------------------ transport
    async def _send(self, market, method, path, params, signed):
        if self.sim is not None:
            return await self.sim.handle(market, method, path, dict(params or {}))
        if time.time() < self.paused_until:
            raise BinanceError(429, -1003, f"rate limited, retry in {int(self.paused_until - time.time())} s")
        p = {k: (fmt(v) if isinstance(v, Decimal) else v) for k, v in (params or {}).items() if v is not None}
        if signed:
            if not (self.key and self.secret):
                raise BinanceError(0, -2014, "no API key configured")
            p["timestamp"] = int(time.time() * 1000) + self.offset
            p["recvWindow"] = 10000
        q = urllib.parse.urlencode(p)
        if signed:
            q += "&signature=" + hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        headers = {"X-MBX-APIKEY": self.key} if self.key else {}
        tries = 3 if method == "GET" else 1                 # never repeat an order by accident
        for i in range(tries):
            try:
                r = await self._http.request(method, f"{self.base[market]}{path}" + (f"?{q}" if q else ""), headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if i == tries - 1:
                    raise BinanceError(0, -1001, f"network error: {type(e).__name__}")
                await asyncio.sleep(0.5 * (i + 1))
                continue
            if r.status_code in (418, 429):
                wait = int(r.headers.get("retry-after", "30") or 30)
                self.paused_until = time.time() + min(wait, 900)
                raise BinanceError(r.status_code, -1003, f"rate limited / banned, retry after {wait} s")
            if r.status_code >= 500 and method == "GET" and i < tries - 1:
                await asyncio.sleep(0.5 * (i + 1))
                continue
            try:
                data = r.json()
            except Exception:
                data = {"msg": r.text[:200]}
            if r.status_code >= 400 or (isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0):
                err = BinanceError(r.status_code, (data or {}).get("code", -1), (data or {}).get("msg", ""))
                self.last_error = str(err)
                raise err
            return data

    async def call(self, market, method, path, params=None, signed=True):
        return await self._send(market, method, path, params, signed)

    async def sync_time(self):
        try:
            t = await self.call("fut", "GET", "/fapi/v1/time", signed=False)
            self.offset = int(t["serverTime"]) - int(time.time() * 1000)
        except Exception:
            pass

    async def close(self):
        if self._http is not None:
            await self._http.aclose()

    # ------------------------------------------------------------------ symbols
    async def sym(self, market, symbol, max_age=3600):
        key = (market, symbol)
        if key in self._info and time.time() - self._info_ts.get(market, 0) < max_age:
            return self._info[key]
        path = "/fapi/v1/exchangeInfo" if market == "fut" else "/api/v3/exchangeInfo"
        # Always fetch the FULL exchange symbol list for this market, unfiltered - previously spot
        # passed {"symbol": symbol} here, which Binance's spot exchangeInfo endpoint honors by
        # returning only that one symbol, so the spot side of the cache could never hold more than
        # whatever symbol last primed it (always "BTCUSDT" from service.py's /symbols endpoint).
        # Futures already fetched unfiltered, which is why only spot was ever stuck on one pair.
        data = await self.call(market, "GET", path, None, signed=False)
        for s in data["symbols"]:
            self._info[(market, s["symbol"])] = Sym(s)
        self._info_ts[market] = time.time()
        if key not in self._info:
            raise BinanceError(400, -1121, f"invalid symbol {symbol}")
        return self._info[key]

    async def price(self, market, symbol):
        path = "/fapi/v1/ticker/price" if market == "fut" else "/api/v3/ticker/price"
        d = await self.call(market, "GET", path, {"symbol": symbol}, signed=False)
        return D(d["price"])

    async def klines(self, market, symbol, interval="1h", limit=1000, start=None, end=None):
        path = "/fapi/v1/klines" if market == "fut" else "/api/v3/klines"
        rows = await self.call(market, "GET", path, {"symbol": symbol, "interval": interval, "limit": limit, "startTime": start, "endTime": end}, signed=False)
        return [{"t": r[0] / 1000, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]

    # ------------------------------------------------------------------ account / permissions
    async def api_restrictions(self):
        return await self.call("spot", "GET", "/sapi/v1/account/apiRestrictions")

    async def f_balance(self):
        rows = await self.call("fut", "GET", "/fapi/v2/balance")
        u = next((r for r in rows if r["asset"] == "USDT"), {})
        return {"wallet": D(u.get("balance", 0)), "available": D(u.get("availableBalance", 0)), "upnl": D(u.get("crossUnPnl", 0))}

    async def f_position_mode(self):
        d = await self.call("fut", "GET", "/fapi/v1/positionSide/dual")
        return bool(d.get("dualSidePosition"))

    async def f_positions(self, all_rows=False):
        rows = await self.call("fut", "GET", "/fapi/v2/positionRisk")
        return rows if all_rows else [r for r in rows if D(r.get("positionAmt", 0)) != 0]

    async def f_open_orders(self, symbol=None):
        return await self.call("fut", "GET", "/fapi/v1/openOrders", {"symbol": symbol} if symbol else None)

    async def f_open_algo(self, symbol=None):
        return await self.call("fut", "GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol} if symbol else None)

    async def f_new_order(self, **p):
        return await self.call("fut", "POST", "/fapi/v1/order", p)

    async def f_new_algo(self, **p):
        p.setdefault("algoType", "CONDITIONAL")
        return await self.call("fut", "POST", "/fapi/v1/algoOrder", p)

    async def f_cancel_order(self, symbol, **ids):
        return await self.call("fut", "DELETE", "/fapi/v1/order", dict(symbol=symbol, **ids))

    async def f_cancel_algo(self, **ids):
        return await self.call("fut", "DELETE", "/fapi/v1/algoOrder", ids)

    async def f_cancel_all(self, symbol):
        """Every open order of the symbol, regular and conditional. Returns the number of errors (0 = clean)."""
        errs = 0
        for path in ("/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"):
            try:
                await self.call("fut", "DELETE", path, {"symbol": symbol})
            except BinanceError:
                errs += 1
        return errs

    async def f_query(self, symbol, client_id):
        return await self.call("fut", "GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id})

    async def f_set_leverage(self, symbol, lev):
        return await self.call("fut", "POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})

    async def f_set_margin(self, symbol, margin_type):
        try:
            return await self.call("fut", "POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type})
        except BinanceError as e:
            if e.code == -4046:                       # "No need to change margin type": already that type
                return {"code": 200, "msg": "unchanged"}
            raise

    async def f_user_trades(self, symbol, start_ms=None, limit=200):
        return await self.call("fut", "GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": start_ms, "limit": limit})

    # ------------------------------------------------------------------ spot
    async def s_account(self):
        d = await self.call("spot", "GET", "/api/v3/account")
        return {b["asset"]: {"free": D(b["free"]), "locked": D(b["locked"])} for b in d["balances"]}

    async def s_new_order(self, **p):
        return await self.call("spot", "POST", "/api/v3/order", p)

    async def s_cancel(self, symbol, **ids):
        return await self.call("spot", "DELETE", "/api/v3/order", dict(symbol=symbol, **ids))

    async def s_cancel_all(self, symbol):
        return await self.call("spot", "DELETE", "/api/v3/openOrders", {"symbol": symbol})

    async def s_open_orders(self, symbol=None):
        return await self.call("spot", "GET", "/api/v3/openOrders", {"symbol": symbol} if symbol else None)

    async def s_query(self, symbol, client_id):
        return await self.call("spot", "GET", "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_id})

    async def s_my_trades(self, symbol, start_ms=None, limit=500):
        return await self.call("spot", "GET", "/api/v3/myTrades", {"symbol": symbol, "startTime": start_ms, "limit": limit})
