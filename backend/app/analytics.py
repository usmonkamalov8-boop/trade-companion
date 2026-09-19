"""Free, rule-based analytics: technical indicators, multi-timeframe scoring,
keyword sentiment. Pure Python (no numpy) so it stays light on a 1 GB VPS."""
import re

# ---------------------------------------------------------------- indicators


def ema(v, n):
    if len(v) < n:
        return []
    k = 2.0 / (n + 1)
    e = sum(v[:n]) / n
    out = [e]
    for x in v[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(c, n=14):
    if len(c) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd_hist(c):
    e12, e26 = ema(c, 12), ema(c, 26)
    if not e26:
        return None, None
    off = len(e12) - len(e26)
    line = [a - b for a, b in zip(e12[off:], e26)]
    sig = ema(line, 9)
    if len(sig) < 2:
        return None, None
    hist = [l - s for l, s in zip(line[len(line) - len(sig):], sig)]
    return hist[-1], hist[-2]


def atr(h, l, c, n=14):
    if len(c) < n + 1:
        return None
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(1, len(c))]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def bb_pos(c, n=20, k=2.0):
    """0 = lower band, 1 = upper band."""
    if len(c) < n:
        return None
    w = c[-n:]
    m = sum(w) / n
    sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    if sd == 0:
        return 0.5
    lo, hi = m - k * sd, m + k * sd
    return (c[-1] - lo) / (hi - lo)


def levels(h, l, price, look=3, span=90):
    H, L = h[-span:], l[-span:]
    hs, ls = [], []
    for i in range(look, len(H) - look):
        if H[i] == max(H[i - look:i + look + 1]):
            hs.append(H[i])
        if L[i] == min(L[i - look:i + look + 1]):
            ls.append(L[i])
    above = [x for x in hs if x > price]
    below = [x for x in ls if x < price]
    res = min(above) if above else max(H)
    sup = max(below) if below else min(L)
    return sup, res


# ------------------------------------------------------------------- scoring


def bias_label(score):
    if score >= 40:
        return "Bullish"
    if score >= 15:
        return "Mild bullish"
    if score > -15:
        return "Neutral"
    if score > -40:
        return "Mild bearish"
    return "Bearish"


def tf_view(c):
    cl, h, l = c["c"], c["h"], c["l"]
    if len(cl) < 35:
        return None
    px = cl[-1]
    e20, e50, e200 = ema(cl, 20), ema(cl, 50), ema(cl, 200)
    r = rsi(cl)
    mh, mh_prev = macd_hist(cl)
    a = atr(h, l, cl)
    raw, cap = 0, 0
    if e20:
        cap += 10
        raw += 10 if px > e20[-1] else -10
    if e20 and e50:
        cap += 15
        raw += 15 if e20[-1] > e50[-1] else -15
    if e50 and e200:
        cap += 15
        raw += 15 if e50[-1] > e200[-1] else -15
    if mh is not None:
        cap += 15
        raw += 10 if mh > 0 else -10
        raw += 5 if mh > mh_prev else -5
    if r is not None:
        cap += 10
        raw += 10 if r > 55 else (-10 if r < 45 else 0)
        if r > 75:
            raw -= 10
        elif r < 25:
            raw += 10
    score = max(-100, min(100, round(100 * raw / cap))) if cap else 0
    sup, res = levels(h, l, px)
    return {
        "price": px, "score": score, "bias": bias_label(score),
        "ema20": e20[-1] if e20 else None, "ema50": e50[-1] if e50 else None,
        "ema200": e200[-1] if e200 else None, "rsi": r,
        "macd_hist": mh, "macd_rising": (mh is not None and mh > mh_prev),
        "atr": a, "atr_pct": (a / px * 100) if a else None,
        "bb": bb_pos(cl), "support": sup, "resistance": res,
    }


WEIGHTS = {"1h": 0.3, "4h": 0.4, "1d": 0.3}


def _dec(px):
    if px >= 1000:
        return 1
    if px >= 100:
        return 2
    if px >= 10:
        return 3
    if px >= 1:
        return 4
    return 5


def fmt(x, dec=None):
    if x is None:
        return "-"
    d = _dec(abs(x)) if dec is None else dec
    return f"{x:,.{d}f}"


def asset_view(name, label, tfs, kind, dec=None):
    views = {}
    for k, c in tfs.items():
        v = tf_view(c)
        if v:
            views[k] = v
    if not views:
        return None
    tw = sum(WEIGHTS[k] for k in views)
    score = round(sum(views[k]["score"] * WEIGHTS[k] for k in views) / tw)
    h1 = tfs["1h"]["c"]
    price = h1[-1]
    if kind == "crypto" and len(h1) > 25:
        change = (price - h1[-25]) / h1[-25] * 100
    else:
        d1 = tfs["1d"]["c"]
        change = (d1[-1] - d1[-2]) / d1[-2] * 100 if len(d1) > 1 else 0.0
    lv = views.get("4h") or views.get("1h") or next(iter(views.values()))
    ref = views.get("1h") or lv
    out = {
        "name": name, "label": label, "kind": kind, "dec": dec,
        "price": price, "price_str": fmt(price, dec), "change_pct": round(change, 2),
        "score": score, "bias": bias_label(score),
        "rsi": round(ref["rsi"]) if ref["rsi"] is not None else None,
        "atr_pct": round(ref["atr_pct"], 2) if ref["atr_pct"] else None,
        "support": lv["support"], "resistance": lv["resistance"],
        "support_str": fmt(lv["support"], dec), "resistance_str": fmt(lv["resistance"], dec),
        "tf": {k: {"score": v["score"], "bias": v["bias"],
                   "rsi": round(v["rsi"]) if v["rsi"] is not None else None}
               for k, v in views.items()},
        "_views": views,
    }
    out["notes"] = make_notes(out, kind)
    return out


def make_notes(a, kind):
    notes = []
    v = a["_views"]
    dec = a["dec"]
    signs = [1 if x["score"] >= 15 else (-1 if x["score"] <= -15 else 0) for x in v.values()]
    if len(signs) >= 3 and all(s == 1 for s in signs):
        notes.append("1H, 4H and 1D are all aligned bullish.")
    elif len(signs) >= 3 and all(s == -1 for s in signs):
        notes.append("1H, 4H and 1D are all aligned bearish.")
    elif 1 in signs and -1 in signs:
        notes.append("Timeframes conflict (" + ", ".join(
            f"{k.upper()} {x['bias'].lower()}" for k, x in v.items()) + "). Wait for alignment.")
    d1 = v.get("1d")
    if d1 and d1["ema50"] and d1["ema200"]:
        notes.append("Daily trend is up (EMA50 above EMA200)." if d1["ema50"] > d1["ema200"]
                     else "Daily trend is down (EMA50 below EMA200).")
    h4 = v.get("4h")
    if h4 and h4["macd_hist"] is not None:
        up = h4["macd_hist"] > 0
        notes.append(("4H MACD positive" if up else "4H MACD negative")
                     + (" and rising." if h4["macd_rising"] else " and fading."))
    for k in ("1h", "4h"):
        x = v.get(k)
        if x and x["rsi"] is not None:
            if x["rsi"] >= 72:
                notes.append(f"{k.upper()} RSI {x['rsi']:.0f}: overbought, chasing longs is risky.")
            elif x["rsi"] <= 28:
                notes.append(f"{k.upper()} RSI {x['rsi']:.0f}: oversold, watch for a bounce.")
    h1 = v.get("1h")
    if h1:
        if h1["bb"] is not None:
            if h1["bb"] > 1.0:
                notes.append("1H price is above the upper Bollinger band (stretched).")
            elif h1["bb"] < 0.0:
                notes.append("1H price is below the lower Bollinger band (stretched).")
        if h1["atr_pct"]:
            hot = 1.2 if kind == "crypto" else 0.25
            notes.append(f"1H ATR {h1['atr_pct']:.2f}% ("
                         + ("elevated volatility)." if h1["atr_pct"] > hot else "normal volatility)."))
        px, atr_ = a["price"], h1["atr"]
        if atr_:
            sup, res = a["support"], a["resistance"]
            if res and 0 < res - px <= 1.5 * atr_:
                notes.append(f"Price is close to resistance {fmt(res, dec)}.")
            if sup and 0 < px - sup <= 1.5 * atr_:
                notes.append(f"Price is close to support {fmt(sup, dec)}.")
            if a["score"] >= 40 and (h1["rsi"] or 50) < 68 and sup and px - sup <= 3 * atr_:
                notes.append(f"Watch: pullback zone in an uptrend near {fmt(sup, dec)}; "
                             f"the idea fails on a close below it.")
            if a["score"] <= -40 and (h1["rsi"] or 50) > 32 and res and res - px <= 3 * atr_:
                notes.append(f"Watch: rally zone in a downtrend near {fmt(res, dec)}; "
                             f"the idea fails on a close above it.")
    return notes


# ----------------------------------------------------------------- sentiment

_BULL_PREFIX = ("surg", "rall", "soar", "jump", "gain", "climb", "rebound", "recover",
                "breakout", "approv", "adopt", "inflow", "upgrad", "bullish", "optimis",
                "boost", "outperform", "record")
_BULL_WORDS = {"rise", "rises", "rising", "rose", "up", "high", "highs", "buy", "beats", "strong", "hawkish"}
_BEAR_PREFIX = ("plung", "crash", "drop", "fall", "fell", "slump", "tumbl", "declin",
                "selloff", "sell-off", "liquidat", "hack", "exploit", "outflow", "downgrad",
                "bearish", "warn", "recession", "tariff", "fraud", "lawsuit", "weak", "slid", "sink")
_BEAR_WORDS = {"ban", "bans", "banned", "fear", "down", "low", "lows", "misses", "risk-off", "dovish"}


def headline_score(title):
    words = re.findall(r"[a-z][a-z\-]*", title.lower())
    b = sum(1 for w in words if w in _BULL_WORDS or w.startswith(_BULL_PREFIX))
    s = sum(1 for w in words if w in _BEAR_WORDS or w.startswith(_BEAR_PREFIX))
    return (b > s) - (b < s)


def news_tone(items, n=20):
    xs = [i.get("sent", 0) for i in items[:n]]
    if not xs:
        return 0.0, "no headlines"
    m = sum(xs) / len(xs)
    if m > 0.15:
        return m, "leaning bullish"
    if m < -0.15:
        return m, "leaning bearish"
    return m, "mixed"


def fng_label(v):
    if v is None:
        return "n/a"
    if v >= 75:
        return "Extreme greed"
    if v >= 55:
        return "Greed"
    if v > 45:
        return "Neutral"
    if v > 25:
        return "Fear"
    return "Extreme fear"
