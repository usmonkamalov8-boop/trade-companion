"""Historical backtest of the analyst's setups on crypto (Order Blocks + FVG + Volume Profile and everything else
the engine uses). It replays the last N days hour by hour, asks the same strategy code what it would have shown,
then follows price candle by candle with the same rules as the live setup journal:

- No look-ahead: at every step the engine only sees candles that were already closed at that moment.
- A setup fills when price trades through its entry price. If TP1 is reached first it is "missed".
- On the fill candle only the stop counts. If stop and TP1 sit in one candle the stop wins.
- Win = TP1 before the stop (R = planned reward to TP1). Loss = -1R. Fees and slippage are subtracted.
- Not modelled: news filtering, funding, partial exits, order-book depth. Forex is not supported (no real volume).

The replay runs in its own low-priority process (python -m app.backtest run --job ID), so the API and the bot stay
responsive on a small VPS. Progress and results are written to backtests/<id>.json."""
import bisect, gzip, json, os, signal, subprocess, sys, time, uuid
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


def _get(params, tries=4):
    import httpx
    for i in range(tries):
        try:
            r = httpx.get(BINANCE, params=params, timeout=30)
            if r.status_code in (418, 429):
                time.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
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
        time.sleep(0.15)
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


def load_data(name, days, now=None):
    now = int((now or time.time()) // 300 * 300)
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


def replay(name, rows, wk, mo, days, style, fee_bp, slip_bp, min_conf, end_ts, cancelled=lambda: False, tick=lambda i, n: None):
    """Replay one asset. Returns (trades, logged, unresolved)."""
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
    seen, trades, logged, unresolved = {}, [], 0, 0
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
                row = {"ts": T, "dir": s["direction"], "entry": s["entry"], "stop": s["stop"], "tp1": s["tp1"]["price"],
                       "style": style, "state": "pending", "result": None, "activated_ts": None, "closed_ts": None,
                       "r_result": None, "mfe_r": None, "mae_r": None, "checked_ts": None, "expires_ts": T + life}
                horizon = T + life + hold
                i0, i1 = bisect.bisect_left(t5, T), bisect.bisect_right(t5, horizon)
                fut = {key: base[key][i0:i1] for key in ("t", "h", "l", "c")}
                now = min(horizon, end_ts)
                row.update(journal.advance(row, fut, 300, now))
                if row["state"] != "closed" and now < horizon:
                    unresolved += 1
                elif row["result"] in ("win", "loss", "timeout"):
                    risk_pct = abs(row["entry"] - row["stop"]) / row["entry"] * 100
                    cost_r = cost_pct / risk_pct if risk_pct > 0 else 0.0
                    trades.append({"name": name, "style": style, "ts": T, "dir": row["dir"], "conf": s["confidence"],
                                   "conf_raw": s.get("conf_raw", s["confidence"]), "poi": s["poi"]["type"],
                                   "poi_tf": s["poi"]["tf"], "confluence": list(s["poi"]["confluence"]),
                                   "result": row["result"], "r": round(row["r_result"], 3),
                                   "net_r": round(row["r_result"] - cost_r, 3), "rr1": round(s["risk"]["rr1"], 2),
                                   "stop_pct": round(risk_pct, 3), "closed_ts": row["closed_ts"]})
                else:
                    trades.append({"name": name, "style": style, "ts": T, "result": row["result"], "unfilled": True,
                                   "poi": s["poi"]["type"], "conf_raw": s.get("conf_raw", s["confidence"]),
                                   "confluence": list(s["poi"]["confluence"]), "dir": row["dir"]})
        k += 1
        if k % 25 == 0:
            tick(k, steps)
        T += step
    return trades, logged, unresolved


# ------------------------------------------------------------------ statistics


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
    return {"logged": len(trades), "filled": len(filled), "unfilled": len(unf), "wins": len(w), "losses": len(l),
            "timeouts": len(filled) - len(w) - len(l),
            "win_rate": (len(w) / (len(w) + len(l)) * 100) if w or l else None,
            "avg_r": (sum(gross) / len(gross)) if gross else None,
            "avg_net_r": (sum(net) / len(net)) if net else None,
            "total_net_r": round(sum(net), 2), "profit_factor": (pos / neg) if neg > 0 else (None if not pos else 999.0),
            "max_dd_r": round(dd, 2),
            "fill_rate": (len(filled) / len(trades) * 100) if trades else None}


def is_core_full(t):
    c = t.get("confluence") or []
    zone_ok = (t["poi"] == "OB" and "FVG" in c) or (t["poi"] == "FVG" and "OB" in c)
    return zone_ok and any(x.startswith(("POC", "VAL", "VAH")) for x in c)


def group(trades):
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


def start(days=90, style="intraday", assets=None, fee_bp=5.0, slip_bp=2.0, min_conf=0):
    cur = latest()
    if cur and cur.get("status") == "running":
        raise RuntimeError("a backtest is already running")
    names = [a for a in (assets or C.CRYPTO) if a in C.CRYPTO]
    if not names:
        raise ValueError("no valid crypto assets")
    days = max(7, min(int(days), 180))
    if style not in strategy.STYLES:
        style = "intraday"
    job = {"id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4], "status": "running", "started": time.time(),
           "params": {"days": days, "style": style, "assets": names, "fee_bp": float(fee_bp), "slip_bp": float(slip_bp),
                      "min_conf": int(min_conf)},
           "progress": {"done": 0, "total": len(names), "current": None, "pct": 0}, "assets": {}}
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
    job = json.loads(_path(job_id).read_text())
    p = job["params"]
    end_ts = int(time.time() // 300 * 300)
    all_trades = []
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
                rows, wk, mo = load_data(name, p["days"], end_ts)
                if len(rows) < 2000:
                    raise RuntimeError("not enough history")
                trades, logged, unresolved = replay(name, rows, wk, mo, p["days"], p["style"], p["fee_bp"], p["slip_bp"],
                                                    p["min_conf"], end_ts, cancelled, tick)
                res = group(trades)
                res["unresolved"] = unresolved
                job["assets"][name] = res
                all_trades += trades
            except Exception as e:
                job["assets"][name] = {"error": str(e)[:120]}
            _wsave(job)
        job["overall"] = group(all_trades)
        job["by_asset"] = sorted(({"name": n, **(r.get("all") or {})} for n, r in job["assets"].items() if "all" in r),
                                 key=lambda x: -(x.get("total_net_r") or 0))
        job["status"], job["finished"] = "done", time.time()
        job["progress"].update({"done": len(p["assets"]), "pct": 100, "current": None})
        with gzip.open(DIR / f"{job_id}_trades.json.gz", "wt") as f:
            json.dump(all_trades[:20000], f)
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
