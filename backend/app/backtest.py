"""Historical backtest of the analyst's setups on crypto (Order Blocks + FVG + Volume Profile and everything else
the engine uses). It replays the last N days hour by hour, asks the same strategy code what it would have shown,
then follows price candle by candle with the same rules as the live setup journal:

- No look-ahead: at every step the engine only sees candles that were already closed at that moment.
- A setup fills when price trades through its entry price. If TP1 is reached first it is "missed".
- On the fill candle only the stop counts. If stop and TP1 sit in one candle the stop wins.
- Win = TP1 before the stop (R = planned reward to TP1). Loss = -1R. Fees and slippage are subtracted.
- Two ways to enter are replayed side by side: "limit" (a resting order at the zone midpoint) and "confirm" (wait until
  price is in the zone AND a 5-minute CHoCH/BOS in the trade direction appears, then enter at that close).
- Every FILLED trade is compared with a coin-flip baseline: same stop and target distances, entered at market at the
  moment the order filled, averaged over long and short. A strategy only has an edge if it beats that baseline.
- Results carry 95% ranges and a verdict, so a small sample cannot pass for proof.
- Not modelled: news filtering, funding, partial exits, order-book depth. Forex is not supported (no real volume).

The replay runs in its own low-priority process (python -m app.backtest run --job ID), so the API and the bot stay
responsive on a small VPS. Progress and results are written to backtests/<id>.json."""
import bisect, gzip, json, math, os, signal, subprocess, sys, time, uuid
from pathlib import Path
from . import config as C, journal, strategy

DIR = C.BASE / "backtests"
CACHE = DIR / "cache"
BINANCE = "https://fapi.binance.com/fapi/v1/klines"
SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
STEP_MIN = {"scalp": 15, "intraday": 60, "swing": 240}
WARMUP_DAYS = 60
POI_CORE = ("OB", "FVG")


# ------------------------------------------------------------------ data


class Banned(RuntimeError):
    pass


def _get(params, tries=4):
    """Binance klines with backoff. A ban (418) stops everything: the trading bot shares this IP."""
    import httpx
    for i in range(tries):
        try:
            r = httpx.get(BINANCE, params=params, timeout=30)
            if r.status_code == 418:
                raise Banned(f"Binance banned this IP (HTTP 418), retry after {r.headers.get('retry-after', '?')} s")
            if r.status_code == 429:
                time.sleep(min(int(r.headers.get("retry-after", "30") or 30), 120))
                continue
            used = r.headers.get("x-mbx-used-weight-1m")
            if used and used.isdigit() and int(used) > 1500:
                time.sleep(15)                          # leave room for the trading bot
            r.raise_for_status()
            return r.json()
        except Banned:
            raise
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _page(sym, a_ms, b_ms):
    rows = []
    while a_ms < b_ms:
        data = _get({"symbol": sym, "interval": "5m", "startTime": a_ms, "endTime": b_ms, "limit": 1500})
        if not data:
            break
        rows += [[x[0], float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in data]
        a_ms = data[-1][0] + 300000
        if len(data) < 1500:
            break
        time.sleep(0.35)                                 # about 170 weight per minute: well below the 2400 limit
    return rows


def fetch_5m(sym, start_ms, end_ms):
    """5-minute rows [open_ms, o, h, l, c, v], cached on disk and extended when needed."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{sym}_5m.json.gz"
    rows = []
    if path.exists():
        try:
            rows = json.load(gzip.open(path, "rt"))
        except Exception:
            rows = []
    if not rows:
        rows = _page(sym, start_ms, end_ms)
    else:
        if start_ms < rows[0][0] - 600000:
            rows = _page(sym, start_ms, rows[0][0] - 1) + rows
        if end_ms > rows[-1][0] + 600000:
            rows = rows + _page(sym, rows[-1][0] + 300000, end_ms)
    seen, out = set(), []
    for r in sorted(rows):
        if r[0] not in seen:
            seen.add(r[0])
            out.append(r)
    with gzip.open(path, "wt") as f:
        json.dump(out, f)
    return [r for r in out if start_ms <= r[0] <= end_ms]


def fetch_htf(sym, interval):
    """Weekly / monthly candles with their close time (only closed ones are used in the replay)."""
    data = _get({"symbol": sym, "interval": interval, "limit": 1000})
    return [[x[0], float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), x[6]] for x in data]


def load_data(name, days, now=None, offset_days=0):
    now = int((now or time.time()) // 300 * 300) - int(offset_days) * 86400
    sym = name + "USDT"
    rows = fetch_5m(sym, (now - (days + WARMUP_DAYS) * 86400) * 1000, now * 1000)
    return rows, fetch_htf(sym, "1w"), fetch_htf(sym, "1M")


def _cols(rows):
    return {"t": [r[0] / 1000.0 for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
            "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}


def _resample(base, sec):
    out = {k: [] for k in ("t", "o", "h", "l", "c", "v", "end")}
    cur = None
    for i in range(len(base["t"])):
        b = int(base["t"][i] // sec)
        if b != cur:
            cur = b
            out["t"].append(b * sec)
            out["end"].append((b + 1) * sec)
            out["o"].append(base["o"][i])
            out["h"].append(base["h"][i])
            out["l"].append(base["l"][i])
            out["c"].append(base["c"][i])
            out["v"].append(base["v"][i])
        else:
            out["h"][-1] = max(out["h"][-1], base["h"][i])
            out["l"][-1] = min(out["l"][-1], base["l"][i])
            out["c"][-1] = base["c"][i]
            out["v"][-1] += base["v"][i]
    if out["end"] and base["t"][-1] + 300 < out["end"][-1]:        # the newest bucket is not finished
        for k in out:
            out[k].pop()
    return out


def _htf(rows):
    return {"t": [r[0] / 1000.0 for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
            "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows],
            "end": [r[6] / 1000.0 for r in rows]}


# ------------------------------------------------------------------ replay

WAIT_BARS = {"scalp": 24, "intraday": 48, "swing": 96}           # 5-minute bars to wait for confirmation after a touch


def _row(T, direction, entry, stop, tp1, style, state="pending", act=None):
    return {"ts": T, "dir": direction, "entry": entry, "stop": stop, "tp1": tp1, "style": style, "state": state,
            "result": None, "activated_ts": act, "closed_ts": None, "r_result": None, "mfe_r": None, "mae_r": None,
            "checked_ts": None, "expires_ts": T + journal.LIFE[style]}


def _net(row, cost_pct, entry, stop):
    risk_pct = abs(entry - stop) / entry * 100
    cost_r = cost_pct / risk_pct if risk_pct > 0 else 0.0
    return row["r_result"] - cost_r, cost_r


def _baseline(base, i0, style, sd, td, px0, cost_pct, end_ts, T):
    """Coin-flip benchmark: enter at market at the open of candle i0 with the same stop distance sd and target
    distance td, once long and once short, and average. Returns (net R, win share) or None if not resolvable."""
    horizon = T + journal.MAX_OPEN[style]
    i1 = bisect.bisect_right(base["t"], horizon)
    fut = {k: base[k][i0:i1] for k in ("t", "h", "l", "c")}
    now = min(horizon, end_ts)
    rs, wins = [], 0.0
    for d in (1, -1):
        row = _row(T, "long" if d == 1 else "short", px0, px0 - d * sd, px0 + d * td, style, "active", T - 1)
        row.update(journal.advance(row, fut, 300, now))
        if row["state"] != "closed" and now < horizon:
            return None
        if row["r_result"] is None:
            return None
        net, _ = _net(row, cost_pct, px0, row["stop"])
        rs.append(net)
        wins += 1.0 if row["result"] == "win" else 0.0
    return sum(rs) / 2, wins / 2


def _confirm_entry(base, i0, T, s, style, end_ts):
    """After the price touches the zone, wait for a 5-minute CHoCH/BOS in the trade direction and enter at its close.
    Returns (row dict ready for advance, candle index) or None when there was no confirmed entry."""
    d = 1 if s["direction"] == "long" else -1
    zl, zh, stop, tp1 = s["zone"]["low"], s["zone"]["high"], s["stop"], s["tp1"]["price"]
    life_bars = journal.LIFE[style] // 300
    n = len(base["t"])
    j = None
    for i in range(i0, min(n, i0 + life_bars)):
        if (d == 1 and base["l"][i] <= stop) or (d == -1 and base["h"][i] >= stop):
            return None                                   # the stop level was hit before any zone touch
        if (d == 1 and base["h"][i] >= tp1 and base["l"][i] > zh) or (d == -1 and base["l"][i] <= tp1 and base["h"][i] < zl):
            return None                                   # the target ran away without touching the zone
        if base["l"][i] <= zh and base["h"][i] >= zl:
            j = i
            break
    if j is None:
        return None
    a, e = max(0, j - 80), min(n, j + WAIT_BARS[style] + 1)
    sub = {k: base[k][a:e] for k in ("o", "h", "l", "c")}
    st = strategy.structure(sub, 3)
    conf = next((a + ev["idx"] for ev in st["events"] if ev["dir"] == d and a + ev["idx"] >= j), None)
    if conf is None or conf >= n - 1 or base["t"][conf] + 300 > end_ts:
        return None
    for i in range(j, conf + 1):                           # stopped out while waiting for the confirmation
        if (d == 1 and base["l"][i] <= stop) or (d == -1 and base["h"][i] >= stop):
            return None
    entry = base["c"][conf]
    if d * (entry - stop) <= 0 or d * (tp1 - entry) <= 0:
        return None
    risk, reward = abs(entry - stop), abs(tp1 - entry)
    if reward / risk < 1.0:
        return None                                        # the confirmation came too late for a sensible target
    T2 = base["t"][conf] + 300
    row = _row(T2, s["direction"], entry, stop, tp1, style, "active", T2 - 1)
    row["expires_ts"] = T2 + journal.MAX_OPEN[style]
    return row, conf + 1


def replay(name, rows, wk, mo, days, style, fee_bp, slip_bp, min_conf, end_ts, cancelled=lambda: False, tick=lambda i, n: None):
    """Replay one asset. Returns (limit_trades, confirm_trades, logged, unresolved)."""
    base = _cols(rows)
    base["end"] = [t + 300 for t in base["t"]]
    frames = {"5m": base}
    for tf in ("15m", "1h", "4h", "1d"):
        frames[tf] = _resample(base, SEC[tf])
    if wk:
        frames["1w"] = _htf(wk)
    if mo:
        frames["1M"] = _htf(mo)
    step = STEP_MIN[style] * 60
    start = end_ts - days * 86400
    first = int(-(-start // step) * step)
    last = end_ts - 3600
    steps = max(1, (last - first) // step + 1)
    life, hold = journal.LIFE[style], journal.MAX_OPEN[style]
    cost_pct = 2 * (fee_bp + slip_bp) / 100.0
    seen, limit_t, conf_t, logged, unresolved = {}, [], [], 0, 0
    t5 = base["t"]
    T, k = first, 0
    while T <= last:
        if cancelled():
            break
        tfs = {}
        for tf, d in frames.items():
            hi = bisect.bisect_right(d["end"], T)
            lo = max(0, hi - 300)
            if hi - lo >= 5:
                tfs[tf] = {key: d[key][lo:hi] for key in ("t", "o", "h", "l", "c", "v")}
        res = strategy.build(name, "crypto", style, tfs, None, None, T, None)
        s = res.get("setup") if not res.get("error") else None
        if s and s["direction"] != "none" and s.get("poi") and s.get("factors") and s["confidence"] >= min_conf:
            z = s["zone"]
            sig = f"{s['direction']}|{s['poi']['type']}|{s['poi']['tf']}|{z['low']:.6g}|{z['high']:.6g}"
            if seen.get(sig, 0) < T - 86400:
                seen[sig] = T
                logged += 1
                i0 = bisect.bisect_left(t5, T)
                common = {"name": name, "style": style, "ts": T, "dir": s["direction"], "conf": s["confidence"],
                          "conf_raw": s.get("conf_raw", s["confidence"]), "poi": s["poi"]["type"], "poi_tf": s["poi"]["tf"],
                          "confluence": list(s["poi"]["confluence"]), "dist_atr": round(s["poi"].get("dist_atr") or 0, 2),
                          "stop_atr": round(s["risk"]["stop_atr"], 2), "rr1": round(s["risk"]["rr1"], 2),
                          "factors": {f["key"]: f["pts"] for f in s["factors"]}, "status0": s["status"], "signal": True}
                # --- blind limit order at the zone midpoint
                row = _row(T, s["direction"], s["entry"], s["stop"], s["tp1"]["price"], style)
                horizon = T + life + hold
                i1 = bisect.bisect_right(t5, horizon)
                fut = {key: base[key][i0:i1] for key in ("t", "h", "l", "c")}
                now = min(horizon, end_ts)
                row.update(journal.advance(row, fut, 300, now))
                sd = abs(s["entry"] - s["stop"])
                td = abs(s["tp1"]["price"] - s["entry"])
                if row["state"] != "closed" and now < horizon:
                    unresolved += 1
                else:
                    rec = dict(common)
                    if row["result"] in ("win", "loss", "timeout"):
                        net, _ = _net(row, cost_pct, row["entry"], row["stop"])
                        # coin flip taken at the same moment the strategy's order filled, with the same stop and target distances
                        ia = bisect.bisect_left(t5, row["activated_ts"]) if row.get("activated_ts") else i0
                        bl = _baseline(base, ia, style, sd, td, base["o"][ia], cost_pct, end_ts, t5[ia]) if ia < len(t5) else None
                        rec.update(result=row["result"], r=round(row["r_result"], 3), net_r=round(net, 3),
                                   stop_pct=round(abs(row["entry"] - row["stop"]) / row["entry"] * 100, 3), closed_ts=row["closed_ts"],
                                   act_ts=row.get("activated_ts"), b_r=None if bl is None else round(bl[0], 3),
                                   b_win=None if bl is None else bl[1])
                    else:
                        rec.update(result=row["result"], unfilled=True)
                    limit_t.append(rec)
                # --- wait for a 5-minute CHoCH / BOS inside the zone, then enter at market
                ce = _confirm_entry(base, i0, T, s, style, end_ts)
                if ce:
                    row2, i2 = ce
                    horizon2 = row2["expires_ts"]
                    j1 = bisect.bisect_right(t5, horizon2)
                    fut2 = {key: base[key][i2:j1] for key in ("t", "h", "l", "c")}
                    now2 = min(horizon2, end_ts)
                    row2.update(journal.advance(row2, fut2, 300, now2))
                    if row2["state"] == "closed" and row2["result"] in ("win", "loss", "timeout"):
                        net, _ = _net(row2, cost_pct, row2["entry"], row2["stop"])
                        sd2, td2 = abs(row2["entry"] - row2["stop"]), abs(row2["tp1"] - row2["entry"])
                        bl2 = _baseline(base, i2, style, sd2, td2, base["o"][i2], cost_pct, end_ts, row2["ts"])
                        conf_t.append(dict(common, ts=row2["ts"], b_r=None if bl2 is None else round(bl2[0], 3),
                                           b_win=None if bl2 is None else bl2[1], result=row2["result"], r=round(row2["r_result"], 3),
                                           net_r=round(net, 3), stop_pct=round(sd2 / row2["entry"] * 100, 3), closed_ts=row2["closed_ts"]))
        k += 1
        if k % 25 == 0:
            tick(k, steps)
        T += step
    return limit_t, conf_t, logged, unresolved


# ------------------------------------------------------------------ statistics


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round((c - h) * 100, 1), round((c + h) * 100, 1)]


def _mean_sd(xs):
    n = len(xs)
    if n == 0:
        return None, None
    m = sum(xs) / n
    if n < 2:
        return m, None
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def summarize(trades):
    filled = [t for t in trades if not t.get("unfilled")]
    unf = [t for t in trades if t.get("unfilled")]
    w = [t for t in filled if t["result"] == "win"]
    l = [t for t in filled if t["result"] == "loss"]
    net = [t["net_r"] for t in filled]
    gross = [t["r"] for t in filled]
    pos, neg = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in sorted(filled, key=lambda t: t["closed_ts"]):
        eq += t["net_r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    m, sd = _mean_sd(net)
    ci = [round(m - 1.96 * sd / math.sqrt(len(net)), 3), round(m + 1.96 * sd / math.sqrt(len(net)), 3)] if sd is not None else None
    if len(filled) < 30 or ci is None:
        verdict = "too few trades"
    elif ci[0] > 0:
        verdict = "positive (significant)"
    elif ci[1] < 0:
        verdict = "negative (significant)"
    else:
        verdict = "inconclusive"
    # coin-flip baseline over every setup in the group (filled or not): what a random entry with the same risk would do
    bl = [t for t in filled if t.get("b_r") is not None]        # like for like: only the trades that actually filled
    bm, bsd = _mean_sd([t["b_r"] for t in bl])
    baseline = None
    edge = edge_z = None
    if bl:
        baseline = {"n": len(bl), "avg_net_r": bm, "win_rate": sum(t["b_win"] for t in bl) / len(bl) * 100}
        if m is not None and sd is not None and bsd is not None and len(net) > 1 and len(bl) > 1:
            edge = m - bm
            se = math.sqrt(sd ** 2 / len(net) + bsd ** 2 / len(bl))
            edge_z = edge / se if se > 0 else None
    return {"logged": len(trades), "filled": len(filled), "unfilled": len(unf), "wins": len(w), "losses": len(l),
            "timeouts": len(filled) - len(w) - len(l),
            "win_rate": (len(w) / (len(w) + len(l)) * 100) if w or l else None, "win_ci": wilson(len(w), len(w) + len(l)),
            "avg_r": (sum(gross) / len(gross)) if gross else None,
            "avg_net_r": m, "avg_net_ci": ci, "verdict": verdict,
            "total_net_r": round(sum(net), 2), "profit_factor": (pos / neg) if neg > 0 else (None if not pos else 999.0),
            "max_dd_r": round(dd, 2), "fill_rate": (len(filled) / len(trades) * 100) if trades else None,
            "baseline": baseline, "edge": edge, "edge_z": edge_z}


def is_core_full(t):
    c = t.get("confluence") or []
    zone_ok = (t["poi"] == "OB" and "FVG" in c) or (t["poi"] == "FVG" and "OB" in c)
    return zone_ok and any(x.startswith(("POC", "VAL", "VAH")) for x in c)


def _equity(trades, points=60):
    filled = sorted((t for t in trades if not t.get("unfilled")), key=lambda t: t["closed_ts"])
    eq, series = 0.0, []
    for t in filled:
        eq += t["net_r"]
        series.append(round(eq, 2))
    if len(series) > points:
        step = len(series) / points
        series = [series[min(len(series) - 1, int(i * step))] for i in range(points)] + [series[-1]]
    return series


def group(trades, extras=False):
    out = {"all": summarize(trades),
           "ob_fvg": summarize([t for t in trades if t["poi"] in POI_CORE]),
           "ob_fvg_volume": summarize([t for t in trades if is_core_full(t)])}
    buckets = (("Under 50", 0, 50), ("50-69", 50, 70), ("70-84", 70, 85), ("85+", 85, 101))
    out["by_conf"] = [{"label": lab, **summarize([t for t in trades if lo <= (t.get("conf_raw") or 0) < hi])} for lab, lo, hi in buckets]
    types = {}
    for t in trades:
        types.setdefault(t["poi"], []).append(t)
    out["by_poi"] = sorted(({"label": k, **summarize(v)} for k, v in types.items()), key=lambda x: -x["logged"])[:6]
    out["by_dir"] = [{"label": d, **summarize([t for t in trades if t["dir"] == d])} for d in ("long", "short")]
    if extras:
        out["by_dist"] = [{"label": lab, **summarize([t for t in trades if lo <= (t.get("dist_atr") or 0) < hi])}
                          for lab, lo, hi in (("Inside / under 1 ATR", 0, 1), ("1-3 ATR away", 1, 3), ("3+ ATR away", 3, 999))]
        names = ["vp", "volvalid", "trigger", "sweep", "loc", "rr", "htf", "session", "range"]
        abl = []
        for key in names:
            with_ = [t for t in trades if (t.get("factors") or {}).get(key, 0) > 0]
            without = [t for t in trades if (t.get("factors") or {}).get(key, 0) <= 0]
            a, c = summarize(with_), summarize(without)
            if a["filled"] >= 15 and c["filled"] >= 15:
                abl.append({"label": key, "with": a["filled"], "without": c["filled"], "avg_with": a["avg_net_r"],
                            "avg_without": c["avg_net_r"], "diff": a["avg_net_r"] - c["avg_net_r"]})
        out["ablation"] = sorted(abl, key=lambda x: -x["diff"])
        ts = sorted((t["ts"] for t in trades))
        if len(ts) >= 30:
            a1, a2 = ts[len(ts) // 3], ts[2 * len(ts) // 3]
            out["by_third"] = [{"label": lab, **summarize([t for t in trades if lo <= t["ts"] < hi])}
                               for lab, lo, hi in (("First third", 0, a1), ("Middle third", a1, a2), ("Last third", a2, 9e12))]
        out["equity"] = _equity(trades)
    return out


# ------------------------------------------------------------------ jobs (API side)


def _path(job_id):
    return DIR / f"{job_id}.json"


def _save(job):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job))
    os.replace(tmp, _path(job["id"]))


def _wsave(job):
    """Worker-side save that never overwrites a cancellation."""
    try:
        if json.loads(_path(job["id"]).read_text()).get("status") == "cancelled":
            return False
    except Exception:
        pass
    _save(job)
    return True


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def latest():
    if not DIR.is_dir():
        return None
    files = sorted(DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            job = json.loads(f.read_text())
        except Exception:
            continue
        if job.get("status") == "running" and job.get("pid") and not _alive(job["pid"]):
            job["status"], job["error"] = "failed", "the worker stopped unexpectedly"
            _save(job)
        return job
    return None


def latest_done():
    if not DIR.is_dir():
        return None
    for f in sorted(DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            job = json.loads(f.read_text())
        except Exception:
            continue
        if job.get("status") == "done":
            return job
    return None


def load_trades(job_id, mode="limit"):
    try:
        with gzip.open(DIR / f"{job_id}_trades.json.gz", "rt") as f:
            data = json.load(f)
    except Exception:
        return []
    return data.get(mode, []) if isinstance(data, dict) else data


def refresh_job(job_id):
    """Recompute a finished job's summaries from its saved trades with the current statistics (like-for-like coin flip)."""
    try:
        job = json.loads(_path(job_id).read_text())
        with gzip.open(DIR / f"{job_id}_trades.json.gz", "rt") as f:
            data = json.load(f)
    except Exception:
        return None
    if job.get("status") != "done" or not isinstance(data, dict):
        return job
    lim, conf = data.get("limit", []), data.get("confirm", [])
    for key, src in (("assets", lim), ("assets_confirm", conf)):
        old = job.get(key, {})
        new = {}
        for n in job["params"]["assets"]:
            mine = [t for t in src if t.get("name") == n]
            if mine:
                g = group(mine)
                if "unresolved" in old.get(n, {}):
                    g["unresolved"] = old[n]["unresolved"]
                new[n] = g
            elif n in old:
                new[n] = old[n]
        job[key] = new
    job["overall"] = group(lim, extras=True)
    job["overall_confirm"] = group(conf, extras=True)
    for key, src in (("by_asset", "assets"), ("by_asset_confirm", "assets_confirm")):
        job[key] = sorted(({"name": n, **(r.get("all") or {})} for n, r in job[src].items() if "all" in r),
                          key=lambda x: -(x.get("total_net_r") or 0))
    job["summary_version"] = SUMMARY_VERSION
    job.setdefault("baseline_basis", "signal")           # older runs: coin flip entered when the setup appeared
    _save(job)
    return job


def slim(job):
    """Job without the bulky per-asset detail, for the app's polling while a run is in progress."""
    if not job:
        return job
    keep = ("id", "status", "started", "finished", "params", "progress", "error", "end_ts")
    return {k: job[k] for k in keep if k in job}


SUMMARY_VERSION = 2          # 2 = the coin-flip baseline uses only filled trades (entered at the fill time for new runs)


def start(days=90, style="intraday", assets=None, fee_bp=5.0, slip_bp=2.0, min_conf=0, offset_days=0, rules="r2"):
    cur = latest()
    if cur and cur.get("status") == "running":
        raise RuntimeError("a backtest is already running")
    names = [a for a in (assets or C.CRYPTO) if a in C.CRYPTO]
    if not names:
        raise ValueError("no valid crypto assets")
    days = max(7, min(int(days), 365))
    offset_days = max(0, min(int(offset_days), 730))
    if style not in strategy.STYLES:
        style = "intraday"
    if rules not in strategy.RULE_SETS:
        rules = "r2"
    job = {"id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4], "status": "running", "started": time.time(),
           "params": {"days": days, "offset_days": offset_days, "style": style, "assets": names, "fee_bp": float(fee_bp),
                      "slip_bp": float(slip_bp), "min_conf": int(min_conf),
                      "rules": strategy.rules_version(rules), "ruleset": rules},
           "progress": {"done": 0, "total": len(names), "current": None, "pct": 0}, "assets": {}, "assets_confirm": {}}
    _save(job)
    DIR.mkdir(parents=True, exist_ok=True)
    log = open(DIR / "worker.log", "ab")
    proc = subprocess.Popen([sys.executable, "-m", "app.backtest", "run", "--job", job["id"]], cwd=str(C.BASE),
                            stdout=log, stderr=log, start_new_session=True)
    job["pid"] = proc.pid
    _save(job)
    return job


def cancel():
    job = latest()
    if not job or job.get("status") != "running":
        return None
    try:
        os.kill(job["pid"], signal.SIGTERM)
    except Exception:
        pass
    job["status"] = "cancelled"
    _save(job)
    return job


def runs(limit=10):
    out = []
    if DIR.is_dir():
        for f in sorted(DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                j = json.loads(f.read_text())
                out.append({"id": j["id"], "status": j["status"], "started": j["started"], "params": j["params"],
                            "overall": (j.get("overall") or {}).get("all")})
            except Exception:
                continue
    return out


# ------------------------------------------------------------------ worker


def worker(job_id):
    try:
        os.nice(15)                       # never compete with the API or the bot
    except Exception:
        pass
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_DATA, (700 << 20, 700 << 20))    # a runaway replay must not starve the VPS
    except Exception:
        pass
    job = json.loads(_path(job_id).read_text())
    job.setdefault("assets", {})
    job.setdefault("assets_confirm", {})
    p = job["params"]
    strategy.RULESET = p.get("ruleset", "r1" if str(p.get("rules", "")).startswith("r1") else "r2")
    end_ts = int(time.time() // 300 * 300) - p.get("offset_days", 0) * 86400
    job["end_ts"] = end_ts
    all_limit, all_conf = [], []
    try:
        for i, name in enumerate(p["assets"]):
            cur = json.loads(_path(job_id).read_text())
            if cur.get("status") == "cancelled":
                return
            job["progress"].update({"current": name, "done": i, "pct": int(i / len(p["assets"]) * 100)})
            _wsave(job)

            def tick(k, n, i=i, name=name):
                job["progress"]["pct"] = int((i + k / n) / len(p["assets"]) * 100)
                _wsave(job)

            def cancelled():
                try:
                    return json.loads(_path(job_id).read_text()).get("status") == "cancelled"
                except Exception:
                    return False
            try:
                rows, wk, mo = load_data(name, p["days"], time.time(), p.get("offset_days", 0))
                if len(rows) < 2000:
                    raise RuntimeError("not enough history")
                lt, ct, logged, unresolved = replay(name, rows, wk, mo, p["days"], p["style"], p["fee_bp"], p["slip_bp"],
                                                    p["min_conf"], end_ts, cancelled, tick)
                res = group(lt)
                res["unresolved"] = unresolved
                job["assets"][name] = res
                job["assets_confirm"][name] = group(ct)
                all_limit += lt
                all_conf += ct
                del rows
            except Banned as e:
                job["status"], job["error"] = "failed", str(e)
                _wsave(job)
                return
            except Exception as e:
                job["assets"][name] = {"error": str(e)[:120]}
            _wsave(job)
        job["overall"] = group(all_limit, extras=True)
        job["overall_confirm"] = group(all_conf, extras=True)
        for key, src in (("by_asset", "assets"), ("by_asset_confirm", "assets_confirm")):
            job[key] = sorted(({"name": n, **(r.get("all") or {})} for n, r in job[src].items() if "all" in r),
                              key=lambda x: -(x.get("total_net_r") or 0))
        job["status"], job["finished"] = "done", time.time()
        job["summary_version"], job["baseline_basis"] = SUMMARY_VERSION, "fill"
        job["progress"].update({"done": len(p["assets"]), "pct": 100, "current": None})
        with gzip.open(DIR / f"{job_id}_trades.json.gz", "wt") as f:
            json.dump({"limit": all_limit[:30000], "confirm": all_conf[:30000]}, f)
    except BaseException as e:
        job["status"], job["error"] = "failed", str(e)[:200]
    _wsave(job)


def _main(argv):
    if len(argv) >= 4 and argv[1] == "run" and argv[2] == "--job":
        worker(argv[3])
    else:
        print("usage: python -m app.backtest run --job ID")


if __name__ == "__main__":
    _main(sys.argv)
