"""Multi-strategy, multi-timeframe analysis (free, rule-based).

Concepts covered: market structure (BOS / CHoCH), Order Blocks (+ breakers), Fair Value Gaps,
Supply & Demand zones, structural Support/Resistance, Trendlines / channels / breakouts and
dynamic levels, Fibonacci retracement / extension with premium-discount (ICT OTE), liquidity
(equal highs/lows, sweeps), ICT context (kill zones, previous day/week levels, daily open),
Points of Interest (confluence of the above) and Top-Down alignment. Setups are built for
three styles: scalp, intraday and swing.

Everything is a mechanical approximation of discretionary concepts. It is analysis, not advice."""
from datetime import datetime, timezone
from . import analytics as A

STYLES = {
    "scalp": {"ctx": "4h", "bias": "1h", "setup": "15m", "trigger": "5m", "label": "Scalping", "reach": 4.0},
    "intraday": {"ctx": "1d", "bias": "4h", "setup": "1h", "trigger": "15m", "label": "Intraday", "reach": 6.0},
    "swing": {"ctx": "1M", "bias": "1w", "setup": "1d", "trigger": "4h", "label": "Swing", "reach": 8.0},
}
ALL_TFS = ["1M", "1w", "1d", "4h", "1h", "15m", "5m"]          # monthly down to the 5-minute micro chart
TF_LABEL = {"1M": "MN", "1w": "1W", "1d": "1D", "4h": "4H", "1h": "1H", "15m": "15m", "5m": "5m"}
# how much each timeframe counts in the top-down alignment, per style
TD_W = {
    "scalp": {"1M": 0.03, "1w": 0.05, "1d": 0.12, "4h": 0.20, "1h": 0.30, "15m": 0.20, "5m": 0.10},
    "intraday": {"1M": 0.05, "1w": 0.10, "1d": 0.20, "4h": 0.30, "1h": 0.20, "15m": 0.10, "5m": 0.05},
    "swing": {"1M": 0.15, "1w": 0.25, "1d": 0.30, "4h": 0.20, "1h": 0.07, "15m": 0.03, "5m": 0.0},
}


def tfl(tf):
    return TF_LABEL.get(tf, tf)

MODULES = ("structure", "ob", "fvg", "sd", "sr", "fib", "trend", "liquidity", "ict", "poi")
ROLE_W = {"ctx": 0.2, "bias": 0.4, "setup": 0.25, "trigger": 0.15}


# ------------------------------------------------------------------ primitives


def _atr_list(c, n=14):
    h, l, cl = c["h"], c["l"], c["c"]
    m = len(cl)
    if m < n + 2:
        return [max(h[i] - l[i], 1e-12) for i in range(m)]
    trs = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - cl[i - 1]), abs(l[i] - cl[i - 1])) for i in range(1, m)]
    a = sum(trs[1:n + 1]) / n
    out = [a] * (n + 1)
    for i in range(n + 1, m):
        a = (a * (n - 1) + trs[i]) / n
        out.append(a)
    return out


def raw_pivots(c, k):
    h, l, o, cl = c["h"], c["l"], c["o"], c["c"]
    out = []
    for i in range(k, len(h) - k):
        is_h = h[i] > max(h[i - k:i]) and h[i] >= max(h[i + 1:i + k + 1])
        is_l = l[i] < min(l[i - k:i]) and l[i] <= min(l[i + 1:i + k + 1])
        if is_h and is_l:
            is_h, is_l = (cl[i] >= o[i]), (cl[i] < o[i])
        if is_h:
            out.append((i, h[i], "H"))
        elif is_l:
            out.append((i, l[i], "L"))
    return out


def alternate(piv):
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == "H" and p[1] > out[-1][1]) or (p[2] == "L" and p[1] < out[-1][1]):
                out[-1] = p
        else:
            out.append(p)
    return out


def swing_trend(alt):
    hs = [p for p in alt if p[2] == "H"][-2:]
    ls = [p for p in alt if p[2] == "L"][-2:]
    if len(hs) == 2 and len(ls) == 2:
        if hs[1][1] > hs[0][1] and ls[1][1] > ls[0][1]:
            return 1, "HH + HL"
        if hs[1][1] < hs[0][1] and ls[1][1] < ls[0][1]:
            return -1, "LH + LL"
    return 0, "range"


def structure(c, k):
    """Break of Structure / Change of Character from closes beyond confirmed swing points."""
    cl = c["c"]
    piv = raw_pivots(c, k)
    events, trend, last_h, last_l, pi = [], 0, None, None, 0
    for i in range(len(cl)):
        while pi < len(piv) and piv[pi][0] + k <= i:
            idx, price, typ = piv[pi]
            pi += 1
            if typ == "H":
                last_h = (idx, price)
            else:
                last_l = (idx, price)
        if last_h is not None and cl[i] > last_h[1]:
            events.append({"type": "CHoCH" if trend == -1 else "BOS", "dir": 1, "idx": i,
                           "level": last_h[1], "pivot_idx": last_h[0]})
            trend, last_h = 1, None
        elif last_l is not None and cl[i] < last_l[1]:
            events.append({"type": "CHoCH" if trend == 1 else "BOS", "dir": -1, "idx": i,
                           "level": last_l[1], "pivot_idx": last_l[0]})
            trend, last_l = -1, None
    return {"trend": trend, "events": events, "raw": piv, "alt": alternate(piv)}


def order_blocks(c, st, atr):
    """Last opposite candle before the impulse that broke structure. Returns (active, breakers)."""
    o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
    n = len(cl)
    active, breakers = [], []
    for ev in st["events"][-10:]:
        i, p, d = ev["idx"], ev["pivot_idx"], ev["dir"]
        lo = max(p, i - 30)
        if d == 1:
            origin = min(range(lo, i + 1), key=lambda x: l[x])
            win = [x for x in range(max(0, origin - 2), min(n, origin + 3)) if cl[x] < o[x]]
            idx = min(win, key=lambda x: l[x]) if win else origin
            move = max(cl[origin:i + 1]) - min(l[origin], l[idx])
        else:
            origin = max(range(lo, i + 1), key=lambda x: h[x])
            win = [x for x in range(max(0, origin - 2), min(n, origin + 3)) if cl[x] > o[x]]
            idx = max(win, key=lambda x: h[x]) if win else origin
            move = max(h[origin], h[idx]) - min(cl[origin:i + 1])
        a = atr[origin] or 1e-12
        if move < 1.0 * a:
            continue
        zl, zh = l[idx], h[idx]
        tested, dead = False, None
        for j in range(i + 1, n):
            if d == 1:
                if l[j] <= zh:
                    tested = True
                if cl[j] < zl:
                    dead = j
                    break
            else:
                if h[j] >= zl:
                    tested = True
                if cl[j] > zh:
                    dead = j
                    break
        z = {"type": "OB", "dir": d, "low": zl, "high": zh, "idx": idx, "formed": i, "strength": move / a,
             "fresh": not tested, "src": ev["type"], "age": n - 1 - idx}
        if dead is None:
            active.append(z)
        elif n - 1 - dead <= 60:
            breakers.append({**z, "type": "Breaker", "dir": -d, "dead_idx": dead})
    return active[-5:], breakers[-3:]


def fvgs(c, atr, max_age=120):
    o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
    n = len(cl)
    out = []
    for i in range(max(2, n - max_age), n):
        a = atr[i] or 1e-12
        if l[i] - h[i - 2] > 0.12 * a and cl[i - 1] > o[i - 1]:
            zl, zh = h[i - 2], l[i]
            mn = min(l[i + 1:]) if i + 1 < n else None
            if mn is not None and mn <= zl:
                continue
            fill = 0.0
            if mn is not None and mn < zh:
                fill, zh = (zh - mn) / (zh - zl), mn
            out.append({"type": "FVG", "dir": 1, "low": zl, "high": zh, "idx": i - 1, "fill": fill,
                        "fresh": fill == 0.0, "age": n - 1 - i})
        elif l[i - 2] - h[i] > 0.12 * a and cl[i - 1] < o[i - 1]:
            zl, zh = h[i], l[i - 2]
            mx = max(h[i + 1:]) if i + 1 < n else None
            if mx is not None and mx >= zh:
                continue
            fill = 0.0
            if mx is not None and mx > zl:
                fill, zl = (mx - zl) / (zh - zl), mx
            out.append({"type": "FVG", "dir": -1, "low": zl, "high": zh, "idx": i - 1, "fill": fill,
                        "fresh": fill == 0.0, "age": n - 1 - i})
    return out[-6:]


def sd_zones(c, atr, max_age=150):
    """Base (small candles) followed by an impulsive departure = supply / demand zone."""
    o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
    n = len(cl)
    zones = []
    for j in range(max(4, n - max_age), n):
        a = atr[j - 1] or 1e-12
        rng, body = h[j] - l[j], abs(cl[j] - o[j])
        if rng < 1.5 * a or body < 0.55 * rng:
            continue
        if h[j - 1] - l[j - 1] > 0.8 * a:
            continue
        bs = j - 1
        while bs - 1 >= 0 and j - (bs - 1) <= 4 and (h[bs - 1] - l[bs - 1]) <= 0.8 * a:
            bs -= 1
        base_h, base_l = max(h[bs:j]), min(l[bs:j])
        if base_h - base_l > 1.6 * a:
            continue
        d = 1 if cl[j] > o[j] else -1
        pre = cl[bs - 1] - cl[max(0, bs - 4)] if bs >= 1 else 0.0
        if d == 1:
            prox = max(max(o[x], cl[x]) for x in range(bs, j))
            z = {"type": "Demand", "dir": 1, "low": base_l, "high": prox, "pattern": "DBR" if pre < 0 else "RBR"}
        else:
            prox = min(min(o[x], cl[x]) for x in range(bs, j))
            z = {"type": "Supply", "dir": -1, "low": prox, "high": base_h, "pattern": "RBD" if pre > 0 else "DBD"}
        tests, dead = 0, False
        inside = False
        for m in range(j + 1, n):
            hit = (l[m] <= z["high"]) if d == 1 else (h[m] >= z["low"])
            if hit and not inside:
                tests += 1
            inside = hit
            if (d == 1 and cl[m] < z["low"]) or (d == -1 and cl[m] > z["high"]):
                dead = True
                break
        if dead:
            continue
        z.update({"idx": bs, "formed": j, "strength": rng / a, "tests": tests, "fresh": tests == 0, "age": n - 1 - bs})
        zones.append(z)
    out = []
    for z in sorted(zones, key=lambda x: -x["formed"]):   # newest first, drop heavy overlaps
        if not any(q["dir"] == z["dir"] and min(q["high"], z["high"]) > max(q["low"], z["low"]) for q in out):
            out.append(z)
    return out[:6]


def sr_levels(piv, price, a):
    pts = sorted(((p[1], p[0], p[2]) for p in piv[-60:]))
    tol = max(0.35 * a, price * 0.0008)
    clusters = []
    for pr, idx, typ in pts:
        if clusters and pr - clusters[-1]["mean"] <= tol:
            cl_ = clusters[-1]
            cl_["pts"].append((pr, idx, typ))
            cl_["mean"] = sum(x[0] for x in cl_["pts"]) / len(cl_["pts"])
        else:
            clusters.append({"mean": pr, "pts": [(pr, idx, typ)]})
    out = []
    for cl_ in clusters:
        t = len(cl_["pts"])
        types = {x[2] for x in cl_["pts"]}
        out.append({"price": cl_["mean"], "touches": t, "flip": len(types) > 1, "last": max(x[1] for x in cl_["pts"]),
                    "strength": t + (1 if len(types) > 1 else 0)})
    return out


def _line(a, b):
    m = (b[1] - a[1]) / (b[0] - a[0])
    return lambda x: a[1] + m * (x - a[0]), m


def _fit_line(pts, cl, atr_now, ascending):
    n = len(cl)
    tol = 0.2 * atr_now
    best = None
    for bi in range(len(pts) - 1, 0, -1):
        if bi < len(pts) - 2:
            break
        for ai in range(bi - 1, -1, -1):
            a, b = pts[ai], pts[bi]
            if b[0] - a[0] < 6:
                continue
            if ascending and b[1] <= a[1]:
                continue
            if (not ascending) and b[1] >= a[1]:
                continue
            f, m = _line((a[0], a[1]), (b[0], b[1]))
            brk = None
            for x in range(b[0] + 1, n):
                if (ascending and cl[x] < f(x) - tol) or ((not ascending) and cl[x] > f(x) + tol):
                    brk = x
                    break
            if brk is not None and n - 1 - brk > 8:
                continue
            touches = sum(1 for p in pts if abs(p[1] - f(p[0])) <= tol * 1.5)
            cand = {"a": (a[0], a[1]), "b": (b[0], b[1]), "slope": m, "now": f(n - 1), "f": f, "touches": touches,
                    "broken": brk is not None, "break_idx": brk, "asc": ascending}
            if best is None or (cand["touches"], cand["b"][0]) > (best["touches"], best["b"][0]):
                best = cand
    return best


def trendlines(c, piv, atr_now):
    cl = c["c"]
    n = len(cl)
    lows = [p for p in piv if p[2] == "L"][-5:]
    highs = [p for p in piv if p[2] == "H"][-5:]
    out = {}
    sup = _fit_line(lows, cl, atr_now, True) if len(lows) >= 2 else None
    res = _fit_line(highs, cl, atr_now, False) if len(highs) >= 2 else None
    for key, tl, pts in (("support", sup, highs), ("resistance", res, lows)):
        if not tl:
            continue
        item = {k: v for k, v in tl.items() if k != "f"}
        item["pos_vs"] = cl[-1] - tl["now"]
        between = [p for p in pts if p[0] >= tl["a"][0]]
        if between:
            if key == "support":
                p_ = max(between, key=lambda p: p[1] - tl["f"](p[0]))
                off = p_[1] - tl["f"](p_[0])
            else:
                p_ = min(between, key=lambda p: p[1] - tl["f"](p[0]))
                off = p_[1] - tl["f"](p_[0])
            if abs(off) > 0.8 * atr_now:
                other = tl["now"] + off
                lo, hi = min(tl["now"], other), max(tl["now"], other)
                item["channel"] = {"low": lo, "high": hi, "pos": (cl[-1] - lo) / (hi - lo) if hi > lo else 0.5}
        out[key] = item
    return out


def fib_range(alt, c, atr_now):
    """Latest dealing range from the last swing leg, with retracements, extensions and premium/discount."""
    if len(alt) < 2:
        return None
    h, l, cl = c["h"], c["l"], c["c"]
    n = len(cl)
    p2 = alt[-1]
    rng = None
    for k in range(2, min(7, len(alt) + 1)):
        p1 = alt[-k]
        if p1[2] == p2[2]:
            continue
        if abs(p1[1] - p2[1]) >= 2.0 * atr_now:
            rng = (p1, p2)
            break
    if rng is None:
        return None
    p1, p2 = rng
    if p2[2] == "H":
        d, low, high = 1, p1[1], max(p2[1], max(h[p2[0]:]))
    else:
        d, high, low = -1, p1[1], min(p2[1], min(l[p2[0]:]))
    r = high - low
    px = cl[-1]
    if d == 1:
        retr = {x: high - x * r for x in (0.236, 0.382, 0.5, 0.618, 0.705, 0.786)}
        ext = {1.272: low + 1.272 * r, 1.618: low + 1.618 * r}
        ote = (high - 0.786 * r, high - 0.618 * r)
    else:
        retr = {x: low + x * r for x in (0.236, 0.382, 0.5, 0.618, 0.705, 0.786)}
        ext = {1.272: high - 1.272 * r, 1.618: high - 1.618 * r}
        ote = (low + 0.618 * r, low + 0.786 * r)
    pos = (px - low) / r if r else 0.5
    zone = "discount" if pos < 0.45 else ("premium" if pos > 0.55 else "equilibrium")
    at = None
    for x, v in retr.items():
        if abs(px - v) <= 0.3 * atr_now:
            at = x
    return {"dir": d, "high": high, "low": low, "retr": retr, "ext": ext, "ote": ote, "pos": pos, "zone": zone,
            "eq": low + 0.5 * r, "at": at, "in_ote": ote[0] - 0.1 * atr_now <= px <= ote[1] + 0.1 * atr_now}


def liquidity(alt, c, atr_now):
    h, l, cl = c["h"], c["l"], c["c"]
    n = len(cl)
    px = cl[-1]
    hs = [p for p in alt if p[2] == "H"][-10:]
    ls = [p for p in alt if p[2] == "L"][-10:]
    tol = 0.15 * atr_now

    def pools(pts):
        out = []
        for i, p in enumerate(pts):
            same = [q for q in pts if abs(q[1] - p[1]) <= tol]
            if len(same) >= 2 and not any(abs(o_ - p[1]) <= tol for o_ in out):
                out.append(p[1])
        return out

    sweeps = []
    for m in range(max(0, n - 12), n):
        for p in hs:
            if p[0] < m - 2 and h[m] > p[1] and cl[m] < p[1]:
                sweeps.append({"type": "BSL", "level": p[1], "idx": m, "extreme": h[m]})
        for p in ls:
            if p[0] < m - 2 and l[m] < p[1] and cl[m] > p[1]:
                sweeps.append({"type": "SSL", "level": p[1], "idx": m, "extreme": l[m]})
    uniq = {}
    for w in sweeps:
        uniq[(w["type"], round(w["level"], 8))] = w
    sweeps = sorted(uniq.values(), key=lambda w: w["idx"])
    return {"bsl": sorted(p[1] for p in hs if p[1] > px), "ssl": sorted((p[1] for p in ls if p[1] < px), reverse=True),
            "eqh": pools(hs), "eql": pools(ls), "sweeps": sweeps[-2:]}


def analyze_tf(c, tf):
    n = len(c["c"])
    if n < (18 if tf == "1M" else 30 if tf == "1w" else 40):
        return None
    k = 3 if tf in ("5m", "15m", "1h") else 2
    atr = _atr_list(c)
    a = atr[-1]
    px = c["c"][-1]
    st = structure(c, k)
    alt = st["alt"]
    sw, label = swing_trend(alt)
    trend = sw or st["trend"]
    obs, breakers = order_blocks(c, st, atr)
    ema = {x: (A.ema(c["c"], x) or [None])[-1] for x in (20, 50, 200)}
    win = atr[-60:]
    return {
        "tf": tf, "n": n, "price": px, "atr": a, "atr_pct": a / px * 100, "atr_ratio": a / (sum(win) / len(win)),
        "trend": trend, "trend_label": label if sw else ("structure " + ("up" if st["trend"] == 1 else "down" if st["trend"] == -1 else "flat")),
        "events": st["events"][-4:], "last_event": st["events"][-1] if st["events"] else None,
        "last_bos": next((e for e in reversed(st["events"]) if e["type"] == "BOS"), None),
        "last_choch": next((e for e in reversed(st["events"]) if e["type"] == "CHoCH"), None),
        "alt": alt, "obs": obs, "breakers": breakers, "fvgs": fvgs(c, atr), "sd": sd_zones(c, atr),
        "sr": sr_levels(st["raw"], px, a), "tl": trendlines(c, st["raw"], a), "fib": fib_range(alt, c, a),
        "liq": liquidity(alt, c, a), "ema": ema, "bars": n,
    }


# ---------------------------------------------------------------- ICT context


def session_info(ts=None, kind="crypto"):
    """ICT kill zones in New York time, plus a market-closed flag for forex weekends."""
    import time as _t
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(ts or _t.time(), ZoneInfo("America/New_York"))
    except Exception:
        d = datetime.fromtimestamp(ts or _t.time(), timezone.utc)
    h = d.hour + d.minute / 60
    if h >= 20:
        name, kill = "Asian range (kill zone)", True
    elif 2 <= h < 5:
        name, kill = "London kill zone", True
    elif 7 <= h < 10:
        name, kill = "New York AM kill zone", True
    elif 12 <= h < 13.5:
        name, kill = "New York lunch (low probability)", False
    elif 13.5 <= h < 16:
        name, kill = "New York PM session", False
    else:
        name, kill = "Between sessions", False
    wd = d.weekday()
    closed = kind == "forex" and (wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 17))
    return {"name": name, "kill": kill, "closed": closed, "ny_time": d.strftime("%H:%M")}


def ict_context(tfs, kind, ts=None):
    out = {"session": session_info(ts, kind)}
    d, w = tfs.get("1d"), tfs.get("1w")
    if d and len(d["c"]) >= 3:
        out.update({"pdh": d["h"][-2], "pdl": d["l"][-2], "dopen": d["o"][-1]})
    if w and len(w["c"]) >= 3:
        out.update({"pwh": w["h"][-2], "pwl": w["l"][-2], "wopen": w["o"][-1]})
    return out


# ------------------------------------------------------------- POI and setups


def _z(typ, tf, low, high, base, fresh=True, note=""):
    return {"type": typ, "tf": tf, "low": low, "high": high, "base": base, "fresh": fresh, "note": note}


def collect_zones(s, per, price, mods):
    zs = []
    side = "bullish" if s == 1 else "bearish"
    for role in ("setup", "bias"):
        a = per.get(role)
        if not a:
            continue
        tf, hb = tfl(a["tf"]), (0.5 if role == "bias" else 0.0)
        if mods.get("ob", True):
            for z in a["obs"]:
                if z["dir"] == s:
                    zs.append(_z("OB", tf, z["low"], z["high"],
                                 3.0 + (0.7 if z["src"] == "CHoCH" else 0) + (0.5 if z["fresh"] else 0)
                                 + min(1.0, z["strength"] / 8) + hb, z["fresh"], f"{side} OB after {z['src']}"))
            for z in a["breakers"]:
                if z["dir"] == s:
                    zs.append(_z("Breaker", tf, z["low"], z["high"], 2.2 + hb, False, f"{side} breaker block"))
        if mods.get("fvg", True):
            for z in a["fvgs"]:
                if z["dir"] == s:
                    zs.append(_z("FVG", tf, z["low"], z["high"], 2.0 + (0.5 if z["fresh"] else 0) + hb, z["fresh"],
                                 f"{side} FVG" + ("" if z["fresh"] else f" ({z['fill'] * 100:.0f}% filled)")))
        if mods.get("sd", True):
            for z in a["sd"]:
                if z["dir"] == s:
                    zs.append(_z("Demand" if s == 1 else "Supply", tf, z["low"], z["high"],
                                 2.5 + (0.5 if z["fresh"] else 0) + min(1.0, z["strength"] / 8) + hb, z["fresh"],
                                 f"{z['pattern']} {'fresh' if z['fresh'] else 'tested'}"))
        if mods.get("sr", True):
            for x in a["sr"]:
                ok = x["price"] < price if s == 1 else x["price"] > price
                if ok and x["strength"] >= 2:
                    zs.append(_z("S/R", tf, x["price"] - 0.15 * a["atr"], x["price"] + 0.15 * a["atr"],
                                 1.0 + min(1.5, 0.5 * x["strength"]) + hb, True,
                                 f"{'support' if s == 1 else 'resistance'} ({x['touches']} touches)"))
        if mods.get("trend", True):
            tl = a["tl"].get("support" if s == 1 else "resistance")
            if tl and not tl["broken"]:
                zs.append(_z("Trendline", tf, tl["now"] - 0.2 * a["atr"], tl["now"] + 0.2 * a["atr"],
                             1.2 + 0.3 * min(3, tl["touches"]) + hb, True, f"{tl['touches']}-touch trendline"))
        if mods.get("fib", True):
            f = a["fib"]
            if f and f["dir"] == s:
                zs.append(_z("Fib OTE", tf, f["ote"][0], f["ote"][1], 2.0 + hb, True, "0.618-0.786 retracement"))
    return zs


def _overlap(a, b, tol):
    return min(a["high"], b["high"]) >= max(a["low"], b["low"]) - tol


def rank_pois(s, zones, price, atr_setup, reach):
    cands = []
    for z in zones:
        if s == 1:
            if z["low"] > price:
                continue
            dist = max(0.0, price - z["high"])
        else:
            if z["high"] < price:
                continue
            dist = max(0.0, z["low"] - price)
        if dist > reach * atr_setup:
            continue
        cands.append({**z, "dist": dist})
    tol = 0.15 * atr_setup
    for z in cands:
        others = [o for o in cands if o is not z and o["type"] != z["type"] and _overlap(z, o, tol)]
        z["confluence"] = sorted({o["type"] for o in others})
        z["score"] = z["base"] + 0.5 * sum(sorted((o["base"] for o in others), reverse=True)[:3])
    cands.sort(key=lambda z: (-z["score"], z["dist"]))
    out = []
    for z in cands:
        if not any(_overlap(z, q, 0) and min(z["high"], q["high"]) - max(z["low"], q["low"]) > 0.5 * (z["high"] - z["low"])
                   for q in out):
            out.append(z)
    return out[:3]


def collect_targets(s, entry, per, ict, mods, atr_setup):
    c = []
    for role in ("setup", "bias", "ctx"):
        a = per.get(role)
        if not a:
            continue
        tf = tfl(a["tf"])
        for p in a["alt"][-8:]:
            if s == 1 and p[2] == "H" and p[1] > entry:
                c.append((p[1], f"{tf} swing high"))
            if s == -1 and p[2] == "L" and p[1] < entry:
                c.append((p[1], f"{tf} swing low"))
        if mods.get("sr", True):
            for x in a["sr"]:
                if x["strength"] >= 2 and ((x["price"] > entry) if s == 1 else (x["price"] < entry)):
                    c.append((x["price"], f"{tf} key {'resistance' if s == 1 else 'support'}"))
        if mods.get("sd", True):
            for z in a["sd"]:
                if z["dir"] == -s:
                    if s == 1 and z["low"] > entry:
                        c.append((z["low"], f"{tf} supply zone"))
                    if s == -1 and z["high"] < entry:
                        c.append((z["high"], f"{tf} demand zone"))
        if mods.get("liquidity", True) and role in ("setup", "bias"):
            for p in (a["liq"]["eqh"] if s == 1 else a["liq"]["eql"]):
                if (p > entry) if s == 1 else (p < entry):
                    c.append((p, f"{tf} equal {'highs' if s == 1 else 'lows'} (liquidity)"))
        f = a["fib"]
        if mods.get("fib", True) and role == "setup" and f and f["dir"] == s:
            for k, v in f["ext"].items():
                if (v > entry) if s == 1 else (v < entry):
                    c.append((v, f"fib {k} extension"))
    if mods.get("ict", True):
        for key, lab in (("pdh", "previous day high"), ("pwh", "previous week high")) if s == 1 else (("pdl", "previous day low"), ("pwl", "previous week low")):
            v = ict.get(key)
            if v is not None and ((v > entry) if s == 1 else (v < entry)):
                c.append((v, lab))
    c.sort(key=lambda x: s * x[0])
    out = []
    for p, lab in c:
        if not out or abs(p - out[-1][0]) > 0.3 * atr_setup:
            out.append((p, lab))
    return out


def _dirword(d):
    return "Bullish" if d == 1 else ("Bearish" if d == -1 else "Neutral")


def make_setup(name, style, per, ict, dec, mods, kind, per_all=None):
    cfg = STYLES[style]
    setup, bias, trig, ctx = per["setup"], per["bias"], per.get("trigger"), per.get("ctx")
    fmt = lambda x: A.fmt(x, dec)
    px, a = setup["price"], setup["atr"]
    per_all = per_all or {x["tf"]: x for x in per.values() if x}
    dirs = {t: x["trend"] for t, x in per_all.items()}
    w = TD_W[style]
    wsum = sum(w.get(t, 0.0) for t in dirs) or 1.0
    td = sum(w.get(t, 0.0) * d for t, d in dirs.items()) / wsum

    reason = ""
    range_mode = False
    if bias["trend"] != 0:
        s, reason = bias["trend"], f"{tfl(bias['tf'])} trend ({bias['trend_label']})"
    elif abs(td) >= 0.2:
        s, reason = (1 if td > 0 else -1), "top-down majority"
    else:
        f = setup["fib"]
        if f and f["zone"] != "equilibrium":
            s, range_mode = (1 if f["zone"] == "discount" else -1), True
            reason = f"{tfl(setup['tf'])} range: {f['zone']}"
        else:
            s = 0
    res = {"style": style, "label": cfg["label"], "roles": {r: cfg[r] for r in ROLE_W}, "topdown": td,
           "direction": "none", "status": "NO TRADE", "confidence": 0, "poi": None, "notes": [], "risk": {}}
    if s == 0:
        res["notes"] = ["Higher timeframes disagree and price is at equilibrium: no edge. Wait for structure."]
        return res
    align = sum(w.get(t, 0.0) * d * s for t, d in dirs.items()) / wsum
    res["direction"] = "long" if s == 1 else "short"
    res["reason"] = reason
    res["align"] = align
    notes = []

    zones = collect_zones(s, per, px, mods)
    pois = rank_pois(s, zones, px, a, cfg["reach"])
    fib = setup["fib"]
    sweeps = [w for w in setup["liq"]["sweeps"] if (w["type"] == "SSL" and s == 1) or (w["type"] == "BSL" and s == -1)]

    if not pois:
        res["status"] = "NO POI"
        res["notes"] = [f"{_dirword(s)} bias ({reason}) but no point of interest within {cfg['reach']:.0f} ATR on the "
                        f"{tfl(setup['tf'])} chart. Wait for price to retrace into a zone."]
        return res
    poi = pois[0]
    zl, zh = poi["low"], poi["high"]
    refined = False
    if zh - zl > 1.5 * a:            # tall higher-timeframe zone: enter in its proximal half
        half = (zh - zl) * 0.5
        if s == 1:
            zl = zh - half
        else:
            zh = zl + half
        refined = True
    if s == 1:
        sl = poi["low"] - 0.25 * a
        if sweeps and poi["low"] - 0.5 * a <= sweeps[-1]["extreme"] <= poi["high"]:
            sl = min(sl, sweeps[-1]["extreme"] - 0.15 * a)
    else:
        sl = poi["high"] + 0.25 * a
        if sweeps and poi["low"] <= sweeps[-1]["extreme"] <= poi["high"] + 0.5 * a:
            sl = max(sl, sweeps[-1]["extreme"] + 0.15 * a)
    in_zone = zl - 0.25 * a <= px <= zh + 0.25 * a
    entry = min(max(px, zl), zh) if in_zone else (zl + zh) / 2
    if abs(entry - sl) > 3.0 * a:
        sl = entry - s * 3.0 * a
        notes.append("The zone is tall: the stop was tightened to 3 ATR. Refine it with the trigger-timeframe swing once price is inside.")
    risk = max(abs(entry - sl), 0.3 * a)

    tgts = collect_targets(s, entry, per, ict, mods, a)
    tp = []
    for p, lab in tgts:
        tp.append({"price": p, "label": lab, "rr": s * (p - entry) / risk})
    good = [t for t in tp if t["rr"] >= 1.0]
    if good:
        tp1 = good[0]
        later = [t for t in good if t["price"] != tp1["price"] and t["rr"] >= max(2.0, tp1["rr"] + 0.5)]
        tp2 = later[0] if later else None
    else:
        tp1 = tp[-1] if tp else {"price": entry + s * 2 * risk, "label": "2R projection (no structural target)", "rr": 2.0}
        tp2 = None
    if tp2 is None:
        proj = entry + s * 3 * risk
        tp2 = {"price": proj, "label": "3R projection", "rr": 3.0}

    trig_ok, trig_txt = False, ""
    micro = per_all.get("5m")
    for x in {id(t): t for t in (trig, micro) if t}.values():
        lim = 24 if x["tf"] == "5m" else 20
        for ev in x["events"]:
            if ev["dir"] == s and x["n"] - 1 - ev["idx"] <= lim:
                trig_ok, trig_txt = True, f"{tfl(x['tf'])} {ev['type']} {'up' if s == 1 else 'down'} {x['n'] - 1 - ev['idx']} bars ago"
        for z in x["fvgs"]:
            if z["dir"] == s and z["age"] <= 8:
                trig_ok, trig_txt = True, trig_txt or f"{tfl(x['tf'])} {'bullish' if s == 1 else 'bearish'} FVG formed"
    refine = None
    if micro:
        cands = [z for z in micro["obs"] if z["dir"] == s] + [z for z in micro["fvgs"] if z["dir"] == s]
        inside = [z for z in cands if min(z["high"], zh) >= max(z["low"], zl)]
        if inside:
            z = max(inside, key=lambda q: q["idx"])
            refine = {"type": z["type"], "tf": "5m", "low": z["low"], "high": z["high"]}
    status = ("READY" if trig_ok else "IN ZONE") if in_zone else "WAIT"

    conf = 5 + 20 * max(align, -1.0)
    conf += min(24.0, poi["score"] * 3.0)
    if trig_ok:
        conf += 10
    if sweeps:
        conf += 8
    if fib:
        good_loc = (s == 1 and fib["zone"] == "discount") or (s == -1 and fib["zone"] == "premium")
        bad_loc = (s == 1 and fib["zone"] == "premium") or (s == -1 and fib["zone"] == "discount")
        conf += 6 if good_loc else (-6 if bad_loc else 0)
    if tp1["rr"] >= 2 or tp2["rr"] >= 3:
        conf += 8
    if tp1["rr"] < 1:
        conf -= 10
    against = []
    for t in ("1M", "1w", "1d", cfg["ctx"]):
        if t not in against and t != cfg["bias"] and t in per_all and per_all[t]["trend"] == -s:
            against.append(t)
    if against:
        conf -= min(12, 4 * len(against))
        notes.append(f"Against the {', '.join(tfl(t) for t in against)} trend: reduce size or take profit early.")
    else:
        htf = [t for t in ("1M", "1w", "1d") if t in per_all]
        if len(htf) >= 2 and all(per_all[t]["trend"] == s for t in htf):
            notes.append(f"{', '.join(tfl(t) for t in htf)} structure all agree with the {'long' if s == 1 else 'short'} bias.")
    if range_mode:
        conf -= 10
        notes.append("Higher timeframe is ranging: trade the edges of the range only.")
    if ict.get("session", {}).get("kill") and style != "swing":
        conf += 4
    if ict.get("session", {}).get("closed"):
        notes.append("Forex market is closed (weekend): data is stale, levels are for planning only.")
    conf = int(max(0, min(100, round(conf))))

    stop_atr = abs(entry - sl) / a
    vol = "high" if setup["atr_ratio"] > 1.4 else ("low" if setup["atr_ratio"] < 0.7 else "normal")
    risk_notes = []
    if stop_atr > 3:
        risk_notes.append(f"Stop is wide ({stop_atr:.1f} ATR of the {tfl(setup['tf'])} chart): wait for a lower-timeframe entry inside the zone.")
    if tp1["rr"] < 1.5:
        risk_notes.append(f"Reward to risk to the first target is only {tp1['rr']:.1f}: skip or scale in carefully.")
    if vol == "high":
        risk_notes.append("Volatility is above normal: expect wider swings and stop hunts.")
    if conf < 60:
        risk_notes.append("Confidence is below 60: use half of your normal risk or stay out.")
    res["risk"] = {"stop_pct": abs(entry - sl) / entry * 100, "stop_atr": stop_atr, "atr_pct": setup["atr_pct"],
                   "vol": vol, "rr1": tp1["rr"], "rr2": tp2["rr"], "notes": risk_notes}

    conf_txt = ", ".join(poi["confluence"]) if poi["confluence"] else "none"
    notes.insert(0, f"{_dirword(s)} bias from {reason}; alignment {abs(align) * 100:.0f}% across {', '.join(tfl(t) for t in per_all)}.")
    notes.append(f"POI: {poi['type']} on {poi['tf']} ({poi['note']}), confluence with: {conf_txt}.")
    if sweeps:
        notes.append(f"Liquidity {'sell-side' if s == 1 else 'buy-side'} was just swept at {fmt(sweeps[-1]['level'])}: supports a reversal entry.")
    if fib:
        notes.append(f"Price is in {fib['zone']} of the {tfl(setup['tf'])} range (eq {fmt(fib['eq'])}); OTE zone {fmt(fib['ote'][0])} - {fmt(fib['ote'][1])}.")
    if status == "WAIT":
        notes.append(f"Wait for price to reach the zone ({poi['dist'] / a:.1f} ATR away), then look for a {tfl(cfg['trigger'])} CHoCH or BOS as confirmation.")
    elif status == "IN ZONE":
        notes.append(f"Price is inside the zone: wait for a {tfl(cfg['trigger'])} {'bullish' if s == 1 else 'bearish'} CHoCH/BOS before entering.")
    else:
        notes.append(f"Confirmation present ({trig_txt}).")
    if refine:
        notes.append(f"Precise entry: a {tfl('5m')} {'bullish' if s == 1 else 'bearish'} {refine['type']} at {fmt(refine['low'])} - {fmt(refine['high'])} sits inside the zone; enter on its retest with the stop beyond it.")
    last_opp = [p for p in bias["alt"] if p[2] == ("L" if s == 1 else "H")]
    inval = fmt(last_opp[-1][1]) if last_opp else fmt(sl)
    notes.append(f"Idea is invalid on a {tfl(bias['tf'])} close {'below' if s == 1 else 'above'} {inval}; hard stop {fmt(sl)}.")

    res.update({
        "status": status, "confidence": conf, "conf_label": "High" if conf >= 70 else ("Medium" if conf >= 50 else "Low"),
        "poi": {"type": poi["type"], "tf": poi["tf"], "note": poi["note"], "low": poi["low"], "high": poi["high"],
                "confluence": poi["confluence"], "score": round(poi["score"], 1), "dist_atr": poi["dist"] / a},
        "alt_pois": [{"type": p["type"], "tf": p["tf"], "low": p["low"], "high": p["high"]} for p in pois[1:]],
        "entry": entry, "stop": sl, "tp1": tp1, "tp2": tp2, "notes": notes, "refine": refine,
        "strings": {"entry": f"{fmt(zl)} - {fmt(zh)}", "stop": fmt(sl),
                    "tp1": fmt(tp1["price"]), "tp2": fmt(tp2["price"])},
    })
    return res


def build(name, kind, style, tfs, dec=None, mods=None, ts=None):
    mods = mods or {}
    cfg = STYLES[style]
    per_all = {}
    for tf in ALL_TFS:
        c = tfs.get(tf)
        x = analyze_tf(c, tf) if c else None
        if x:
            per_all[tf] = x
    per = {role: per_all.get(cfg[role]) for role in ROLE_W}
    if not per["setup"] or not per["bias"]:
        return {"name": name, "kind": kind, "style": style, "error": "not enough price history for this style"}
    ict = ict_context(tfs, kind, ts)
    setup = make_setup(name, style, per, ict, dec, mods, kind, per_all)
    px = per["setup"]["price"]
    return {"name": name, "kind": kind, "style": style, "price": px, "dec": dec, "ict": ict, "setup": setup,
            "_per": per, "_all": per_all, "confidence": setup["confidence"]}


# --------------------------------------------------------------------- report


def _levels_line(pts, fmt, n=3):
    return ", ".join(fmt(p) for p in pts[:n]) or "none"


def _ev_info(ev, a, fmt):
    if not ev:
        return None
    return {"dir": ev["dir"], "ago": a["n"] - 1 - ev["idx"], "level": fmt(ev["level"])}


def _zone_info(z, px, fmt):
    d = "bull" if z["dir"] == 1 else "bear"
    mid = (z["low"] + z["high"]) / 2
    txt = f"{fmt(z['low'])} - {fmt(z['high'])}"
    if z["type"] == "OB":
        state = "fresh" if z["fresh"] else "tested"
    else:
        state = "open" if z.get("fresh", True) else f"{z.get('fill', 0) * 100:.0f}% filled"
    return {"dir": z["dir"], "name": d, "zone": txt, "state": state, "dist": abs(mid - px)}


def tf_summary(a, fmt):
    """Structure facts of one timeframe: trend, last BOS / CHoCH, nearest order blocks and FVGs."""
    px = a["price"]
    obs = sorted((_zone_info(z, px, fmt) for z in a["obs"]), key=lambda z: z["dist"])[:3]
    fvg = sorted((_zone_info(z, px, fmt) for z in a["fvgs"]), key=lambda z: z["dist"])[:3]
    f = a["fib"]
    return {"tf": tfl(a["tf"]), "key": a["tf"], "trend": a["trend"], "label": a["trend_label"],
            "bos": _ev_info(a["last_bos"], a, fmt), "choch": _ev_info(a["last_choch"], a, fmt),
            "ob": obs, "fvg": fvg, "zone": f"{f['zone']} {f['pos']:.2f}" if f else ""}


def _ev_txt(name, e):
    if not e:
        return f"no {name}"
    return f"{name} {'up' if e['dir'] == 1 else 'down'} @ {e['level']} ({e['ago']} bars ago)"


def _zones_txt(zs):
    return ", ".join(f"{z['name']} {z['zone']} ({z['state']})" for z in zs) or "none"


def report_text(res, label, focus=None, mods=None):
    """Plain-text report for the chat and the Setups screen."""
    mods = mods or {}
    if res.get("error"):
        return f"{label}: {res['error']}."
    per, setup, ict, style = res["_per"], res["setup"], res["ict"], res["style"]
    cfg = STYLES[style]
    dec = res["dec"]
    fmt = lambda x: A.fmt(x, dec)
    s_a = per["setup"]
    px = res["price"]
    sec = {}
    allp = res.get("_all") or {x["tf"]: x for x in per.values() if x}
    sums = [tf_summary(allp[t], fmt) for t in ALL_TFS if t in allp]
    missing = [tfl(t) for t in ALL_TFS if t not in allp]

    def role_tag(tf):
        tags = [r for r in ("ctx", "bias", "setup", "trigger") if cfg[r] == tf]
        if tf == "5m":
            tags.append("micro entry")
        return f"  [{', '.join(tags)}]" if tags else ""

    L = []
    for m in sums:
        head = f"{m['tf']:<3} {_dirword(m['trend'])} ({m['label']})" + (f", {m['zone']}" if m["zone"] else "") + role_tag(m["key"])
        L.append(head)
        if mods.get("structure", True):
            L.append(f"    {_ev_txt('BOS', m['bos'])}; {_ev_txt('CHoCH', m['choch'])}")
        if mods.get("ob", True):
            L.append(f"    OB: {_zones_txt(m['ob'])}")
        if mods.get("fvg", True):
            L.append(f"    FVG: {_zones_txt(m['fvg'])}")
    if missing:
        L.append("No data for: " + ", ".join(missing))
    td = setup.get("topdown", 0.0)
    mixed = " (mixed)" if abs(td) < 0.35 else ""
    L.append(f"Top-down alignment: {abs(td) * 100:.0f}% {_dirword(1 if td > 0.05 else -1 if td < -0.05 else 0).lower()}{mixed}")
    sec["topdown"] = ["TOP-DOWN, BOS / CHoCH / OB / FVG BY TIMEFRAME (" + " > ".join(m["tf"] for m in sums) + ")"] + L

    S = ["STRUCTURE (SMC): BREAK OF STRUCTURE AND CHANGE OF CHARACTER BY TIMEFRAME"]
    for t in ALL_TFS:
        a = allp.get(t)
        if not a:
            continue
        S.append(f"{tfl(t)}: {_dirword(a['trend'])} ({a['trend_label']})")
        for ev in a["events"][-3:]:
            S.append(f"    {ev['type']} {'up' if ev['dir'] == 1 else 'down'} at {fmt(ev['level'])} ({a['n'] - 1 - ev['idx']} bars ago)")
        if not a["events"]:
            S.append("    no break of structure yet")
    S.append("BOS = trend continuation (close beyond the last swing). CHoCH = first break against the trend (possible reversal).")
    sec["structure"] = S

    z = ["ORDER BLOCKS BY TIMEFRAME"]
    for t in ALL_TFS:
        a = allp.get(t)
        if not a:
            continue
        for o in sorted(a["obs"], key=lambda q: abs((q["low"] + q["high"]) / 2 - px))[:3]:
            z.append(f"{tfl(t)}: {'Bullish' if o['dir'] == 1 else 'Bearish'} OB {fmt(o['low'])} - {fmt(o['high'])} ({'fresh' if o['fresh'] else 'tested'}, after {o['src']})")
        for o in a["breakers"][-1:]:
            z.append(f"{tfl(t)}: Breaker {fmt(o['low'])} - {fmt(o['high'])} ({'bullish' if o['dir'] == 1 else 'bearish'})")
    sec["ob"] = z if len(z) > 1 else z + ["No active order blocks."]

    z = ["FAIR VALUE GAPS BY TIMEFRAME"]
    for t in ALL_TFS:
        a = allp.get(t)
        if not a:
            continue
        for f_ in sorted(a["fvgs"], key=lambda q: abs((q["low"] + q["high"]) / 2 - px))[:3]:
            z.append(f"{tfl(t)}: {'Bullish' if f_['dir'] == 1 else 'Bearish'} FVG {fmt(f_['low'])} - {fmt(f_['high'])}" + ("" if f_["fresh"] else f" ({f_['fill'] * 100:.0f}% filled)"))
    sec["fvg"] = z if len(z) > 1 else z + ["No open gaps."]

    z = ["SUPPLY & DEMAND (" + tfl(s_a["tf"]) + ")"]
    for q in s_a["sd"][:3]:
        z.append(f"{q['type']} {fmt(q['low'])} - {fmt(q['high'])} ({q['pattern']}, {'fresh' if q['fresh'] else str(q['tests']) + ' tests'})")
    sec["sd"] = z if len(z) > 1 else z + ["No clean zones."]

    sr = sorted(s_a["sr"], key=lambda x: -x["strength"])
    up = sorted((x for x in s_a["sr"] if x["price"] > px), key=lambda x: x["price"])
    dn = sorted((x for x in s_a["sr"] if x["price"] < px), key=lambda x: -x["price"])
    z = ["SUPPORT & RESISTANCE (" + tfl(s_a["tf"]) + ")"]
    for lab, xs in (("Resistance", up[:2]), ("Support", dn[:2])):
        for x in xs:
            z.append(f"{lab} {fmt(x['price'])} ({x['touches']} touches{', flipped' if x['flip'] else ''})")
    sec["sr"] = z if len(z) > 1 else z + ["No clear levels."]

    f = s_a["fib"]
    z = ["FIBONACCI / PREMIUM-DISCOUNT (" + tfl(s_a["tf"]) + ")"]
    if f:
        z.append(f"Range {fmt(f['low'])} - {fmt(f['high'])} ({'up' if f['dir'] == 1 else 'down'} leg); price in {f['zone']} ({f['pos']:.2f}), equilibrium {fmt(f['eq'])}")
        z.append("Retracements: " + ", ".join(f"{k} = {fmt(v)}" for k, v in f["retr"].items() if k in (0.382, 0.5, 0.618, 0.786)))
        z.append(f"OTE {fmt(f['ote'][0])} - {fmt(f['ote'][1])}; extensions 1.272 = {fmt(f['ext'][1.272])}, 1.618 = {fmt(f['ext'][1.618])}")
    else:
        z.append("No clear dealing range.")
    sec["fib"] = z

    z = ["TRENDLINES & DYNAMIC LEVELS (" + tfl(s_a["tf"]) + ")"]
    for key, lab in (("support", "Ascending support"), ("resistance", "Descending resistance")):
        t = s_a["tl"].get(key)
        if t:
            st_ = "BROKEN " + f"{s_a['n'] - 1 - t['break_idx']} bars ago (watch the retest)" if t["broken"] else "intact"
            ch = f", channel position {t['channel']['pos'] * 100:.0f}%" if t.get("channel") else ""
            z.append(f"{lab} now at {fmt(t['now'])} ({t['touches']} touches, {st_}{ch})")
    e = s_a["ema"]
    z.append("EMAs: " + ", ".join(f"{k} = {fmt(v)}" for k, v in e.items() if v))
    sec["trend"] = z

    lq = s_a["liq"]
    z = ["LIQUIDITY (" + tfl(s_a["tf"]) + ")"]
    z.append(f"Buy-side above: {_levels_line(lq['bsl'], fmt)}; sell-side below: {_levels_line(lq['ssl'], fmt)}")
    if lq["eqh"] or lq["eql"]:
        z.append("Equal highs: " + _levels_line(lq["eqh"], fmt) + "; equal lows: " + _levels_line(lq["eql"], fmt))
    for w in lq["sweeps"]:
        z.append(f"{'Buy-side' if w['type'] == 'BSL' else 'Sell-side'} liquidity swept at {fmt(w['level'])} {s_a['n'] - 1 - w['idx']} bars ago")
    sec["liquidity"] = z

    z = ["ICT CONTEXT"]
    ss = ict["session"]
    z.append(f"Session: {ss['name']} (NY {ss['ny_time']})" + (", market closed" if ss["closed"] else ""))
    if "pdh" in ict:
        z.append(f"Previous day high {fmt(ict['pdh'])} / low {fmt(ict['pdl'])}; daily open {fmt(ict['dopen'])} ({'above' if px > ict['dopen'] else 'below'})")
    if "pwh" in ict:
        z.append(f"Previous week high {fmt(ict['pwh'])} / low {fmt(ict['pwl'])}")
    if f:
        z.append(f"OTE / {f['zone']} logic applies to the {'long' if f['zone'] == 'discount' else 'short' if f['zone'] == 'premium' else 'neutral'} side.")
    sec["ict"] = z

    P = [f"{cfg['label'].upper()} SETUP"]
    if setup["direction"] == "none":
        P += setup["notes"]
    elif setup["status"] == "NO POI":
        P += setup["notes"]
    else:
        p = setup["poi"]
        P.append(f"{setup['direction'].upper()} - {setup['status']} - confidence {setup['confidence']} ({setup['conf_label']})")
        P.append(f"POI: {p['type']} {p['tf']} {fmt(p['low'])} - {fmt(p['high'])} (score {p['score']}; confluence: {', '.join(p['confluence']) or 'none'})")
        for ap in setup.get("alt_pois", [])[:2]:
            P.append(f"Alternative: {ap['type']} {ap['tf']} {fmt(ap['low'])} - {fmt(ap['high'])}")
        t1, t2 = setup["tp1"], setup["tp2"]
        P.append(f"Entry zone {setup['strings']['entry']}   Stop {setup['strings']['stop']}")
        P.append(f"TP1 {fmt(t1['price'])} ({t1['label']}, {t1['rr']:.1f}R)   TP2 {fmt(t2['price'])} ({t2['label']}, {t2['rr']:.1f}R)")
        r = setup["risk"]
        P.append(f"Risk: stop {r['stop_pct']:.2f}% away ({r['stop_atr']:.1f} ATR), volatility {r['vol']}, ATR {r['atr_pct']:.2f}%")
        rf = setup.get("refine")
        if rf:
            P.append(f"Micro entry ({tfl('5m')}): {rf['type']} {fmt(rf['low'])} - {fmt(rf['high'])} inside the zone")
        P += ["- " + n for n in setup["notes"]]
        P += ["! " + n for n in r["notes"]]
    sec["poi"] = P
    sec["setup"] = P

    head = [f"{label} - {cfg['label']} analysis", f"Price {fmt(px)}"]
    order = ["topdown", "sd", "sr", "fib", "trend", "liquidity", "ict", "setup"]
    if focus and focus in sec and focus not in ("setup", "poi"):
        parts = [sec[focus]]
        if focus != "topdown":
            parts.append(sec["topdown"][:1] + sec["topdown"][-1:])
        parts.append(sec["setup"])
    elif focus in ("poi", "setup"):
        parts = [sec["topdown"], sec["setup"]]
    else:
        parts = [sec[k] for k in order if mods.get(k, True) or k in ("topdown", "setup")]
    body = "\n\n".join("\n".join(p) for p in parts)
    return "\n".join(head) + "\n\n" + body + "\n\nRule-based analysis of live data. Not financial advice."


def public(res, label):
    """JSON-safe summary for the API and the app."""
    if res.get("error"):
        return {"name": res["name"], "label": label, "style": res["style"], "error": res["error"]}
    s, dec = res["setup"], res["dec"]
    fmt = lambda x: A.fmt(x, dec)
    per = res["_per"]
    out = {"name": res["name"], "label": label, "kind": res["kind"], "style": res["style"], "price": res["price"],
           "price_str": fmt(res["price"]), "direction": s["direction"], "status": s["status"],
           "confidence": s["confidence"], "conf_label": s.get("conf_label", "-"),
           "roles": s["roles"], "notes": s["notes"][:5], "session": res["ict"]["session"]["name"],
           "tf": []}
    allp = res.get("_all") or {}
    roles = {}
    for r in ("ctx", "bias", "setup", "trigger"):
        roles.setdefault(s["roles"][r], []).append(r)
    for t in ALL_TFS:
        if t in allp:
            m = tf_summary(allp[t], fmt)
            tag = ", ".join(roles.get(t, [])) or ("micro entry" if t == "5m" else "")
            out["tf"].append({**m, "role": tag})
    rf = s.get("refine")
    if rf:
        out["refine"] = f"{tfl('5m')} {rf['type']} {fmt(rf['low'])} - {fmt(rf['high'])}"
    if s.get("poi"):
        p = s["poi"]
        out.update({"poi": f"{p['type']} {p['tf']} {fmt(p['low'])} - {fmt(p['high'])}", "confluence": p["confluence"],
                    "entry": s["strings"]["entry"], "stop": s["strings"]["stop"], "tp1": s["strings"]["tp1"],
                    "tp2": s["strings"]["tp2"], "rr1": round(s["risk"]["rr1"], 1), "rr2": round(s["risk"]["rr2"], 1),
                    "risk_notes": s["risk"]["notes"], "stop_pct": round(s["risk"]["stop_pct"], 2)})
    return out
