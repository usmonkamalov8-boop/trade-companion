"""Free public data sources: Binance futures (no key needed for market data),
Yahoo Finance chart endpoint, alternative.me Fear & Greed, RSS feeds."""
import asyncio, time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import httpx
from . import config as C
from .analytics import headline_score

UA = {"User-Agent": "Mozilla/5.0"}
_cache = {}
_sem = asyncio.Semaphore(6)


async def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = await fn()
    _cache[key] = (time.time(), val)
    return val


# ------------------------------------------------------------------ candles


async def validate_futures_pair(pair):
    """Checks a symbol exists and is currently trading on Binance USDT-M Futures - the same market the
    analysis itself pulls candles from, so a symbol that passes here is one the screener can actually analyze.
    Raises ValueError with a message safe to show the user; returns nothing on success."""
    async def go():
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.get("https://fapi.binance.com/fapi/v1/exchangeInfo", params={"symbol": pair})
        if r.status_code == 400:
            raise ValueError(f"{pair} isn't a Binance Futures pair")
        r.raise_for_status()
        info = r.json()
        rows = info.get("symbols") or []
        if not rows:
            raise ValueError(f"{pair} isn't a Binance Futures pair")
        if rows[0].get("status") != "TRADING":
            raise ValueError(f"{pair} exists but isn't currently trading ({rows[0].get('status')})")
        return True
    try:
        await _cached(f"validate:{pair}", 30, go)
    except ValueError:
        raise
    except httpx.HTTPError as e:
        raise ValueError(f"could not reach Binance to check {pair}: {e}")


async def binance_klines(pair, interval, limit=300):
    async def go():
        async with _sem, httpx.AsyncClient(timeout=15) as cl:
            r = await cl.get("https://fapi.binance.com/fapi/v1/klines",
                             params={"symbol": pair, "interval": interval, "limit": limit})
        r.raise_for_status()
        rows = r.json()
        return {"t": [x[0] // 1000 for x in rows], "o": [float(x[1]) for x in rows],
                "h": [float(x[2]) for x in rows], "l": [float(x[3]) for x in rows],
                "c": [float(x[4]) for x in rows], "v": [float(x[5]) for x in rows]}
    return await _cached(f"k:{pair}:{interval}", 60, go)


async def yahoo(sym, interval, rng):
    async def go():
        async with _sem, httpx.AsyncClient(timeout=15) as cl:
            r = await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": interval, "range": rng}, headers=UA)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        out = {k: [] for k in "tohlcv"}
        for i, t in enumerate(res.get("timestamp") or []):
            vals = [q["open"][i], q["high"][i], q["low"][i], q["close"][i]]
            if any(x is None for x in vals):
                continue
            out["t"].append(t)
            for k, x in zip("ohlc", vals):
                out[k].append(x)
            out["v"].append(0)
        if len(out["c"]) < 30:
            raise ValueError(f"not enough data for {sym}")
        return out
    return await _cached(f"y:{sym}:{interval}:{rng}", 240, go)


def resample(c, n):
    """Group every n bars, aligned to the newest bar."""
    out = {k: [] for k in "tohlcv"}
    total = len(c["c"])
    for i in range(total % n, total - n + 1, n):
        sl = slice(i, i + n)
        out["t"].append(c["t"][i])
        out["o"].append(c["o"][i])
        out["h"].append(max(c["h"][sl]))
        out["l"].append(min(c["l"][sl]))
        out["c"].append(c["c"][i + n - 1])
        out["v"].append(sum(c["v"][sl]))
    return out


async def crypto_tfs(name):
    pair = name + "USDT"
    a, b, c = await asyncio.gather(binance_klines(pair, "1h"),
                                   binance_klines(pair, "4h"),
                                   binance_klines(pair, "1d"))
    return {"1h": a, "4h": b, "1d": c}


async def forex_tfs(name):
    sym = C.FOREX[name][0]
    h, d = await asyncio.gather(yahoo(sym, "60m", "1mo"), yahoo(sym, "1d", "1y"))
    return {"1h": h, "4h": resample(h, 4), "1d": d}


# --------------------------------------------------------------- sentiment


async def funding():
    async def go():
        async with httpx.AsyncClient(timeout=15) as cl:
            f = (await cl.get("https://fapi.binance.com/fapi/v1/premiumIndex")).json()
        return {x["symbol"]: float(x["lastFundingRate"]) * 100
                for x in f if x["symbol"] in C.PAIRS}
    try:
        return await _cached("funding", 60, go)
    except Exception:
        return {}


async def fear_greed():
    async def go():
        async with httpx.AsyncClient(timeout=10) as cl:
            d = (await cl.get("https://api.alternative.me/fng/?limit=1")).json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    try:
        return await _cached("fng", 900, go)
    except Exception:
        return None


# -------------------------------------------------------------------- news


def _ts(s):
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        return 0


async def _feed(cl, url):
    try:
        r = await cl.get(url, headers=UA, follow_redirects=True)
        root = ET.fromstring(r.content)
        src = (root.findtext("channel/title") or url).strip()
        items = []
        for i in list(root.iter("item"))[:15]:
            title = (i.findtext("title") or "").strip()
            if not title:
                continue
            items.append({"title": title, "link": (i.findtext("link") or "").strip(),
                          "published": i.findtext("pubDate") or "",
                          "ts": _ts(i.findtext("pubDate") or ""),
                          "source": src, "sent": headline_score(title)})
        return items
    except Exception:
        return []


async def news(cat):
    async def go():
        async with httpx.AsyncClient(timeout=15) as cl:
            res = await asyncio.gather(*[_feed(cl, u) for u in C.FEEDS[cat]])
        items = [i for r in res for i in r]
        items.sort(key=lambda i: i["ts"], reverse=True)
        return items[:40]
    return await _cached("news:" + cat, 300, go)


# ---------------------------------------------------------- generic multi-timeframe fetch

BINANCE_TF = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}


async def get_tfs(name, kind, tfs):
    """Candles for the requested timeframes: {tf: candles}. Missing timeframes are left out."""
    out = {}
    if kind == "crypto":
        pair = name + "USDT"

        async def one(tf):
            try:
                out[tf] = await binance_klines(pair, BINANCE_TF[tf], 400)
            except Exception:
                pass

        await asyncio.gather(*[one(tf) for tf in tfs])
        return out
    sym = C.FOREX[name][0]
    need = {}
    if "5m" in tfs:
        need["5m"] = ("5m", "5d")
    if "15m" in tfs:
        need["15m"] = ("15m", "1mo")
    if "1h" in tfs or "4h" in tfs:
        need["60m"] = ("60m", "3mo")
    if "1d" in tfs:
        need["1d"] = ("1d", "2y")
    if "1w" in tfs:
        need["1wk"] = ("1wk", "5y")
    raw = {}

    async def one(key, iv, rng):
        try:
            raw[key] = await yahoo(sym, iv, rng)
        except Exception:
            pass

    await asyncio.gather(*[one(k, iv, rng) for k, (iv, rng) in need.items()])
    if "5m" in raw:
        out["5m"] = raw["5m"]
    if "15m" in raw:
        out["15m"] = raw["15m"]
    if "60m" in raw:
        if "1h" in tfs:
            out["1h"] = raw["60m"]
        if "4h" in tfs:
            out["4h"] = resample(raw["60m"], 4)
    if "1d" in raw:
        out["1d"] = raw["1d"]
    if "1wk" in raw:
        out["1w"] = raw["1wk"]
    return {k: v for k, v in out.items() if len(v["c"]) >= 40}
