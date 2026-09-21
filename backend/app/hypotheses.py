"""Pre-registered hypotheses.

Each hypothesis was written down BEFORE the data that tests it was run. Every saved backtest trade is placed on a time axis
(how many days before the registration date it was signalled). Trades newer than the hypothesis's "seen" boundary are
discovery data: we had already looked at them when the hypothesis was formed. Older trades are TEST data. Only test trades
decide the verdict, so a result found by browsing one period cannot pass by itself.

Any finished intraday backtest (5 bp fee + 2 bp slippage per side, no minimum confidence) counts, whatever its length or
"ended N days ago" setting: trades are pooled and de-duplicated, so overlapping runs are never counted twice. The panel only
reads saved trades; it never re-runs anything. It tells you which 180-day period is still missing."""
import datetime as _dt
import gzip, json, math, time
from . import backtest

REGISTERED = "2026-09-21"
REF_TS = _dt.datetime(2026, 9, 21, 12, 0, tzinfo=_dt.timezone.utc).timestamp()      # end of the discovery runs
STYLE, FEE, SLIP = "intraday", 5.0, 2.0
BUCKET = 180            # days per reporting period
MIN_COVER = 120         # days of a period a run must cover before the period counts as "run"


def _core(t):
    return backtest.is_core_full(t)


def _conf70(t):
    return (t.get("conf_raw") or 0) >= 70


def _r2conf70(t):
    rr = (t.get("factors") or {}).get("rr") or 0            # r1 trades carry the removed bonus: take it off
    return max(0, min(100, (t.get("conf_raw") or 0) - rr)) >= 70


def _has_rr(t):
    return ((t.get("factors") or {}).get("rr") or 0) > 0


Z_MULTI = 2.8      # 10 hypotheses share one family: a 99.5% range keeps the chance of a false 'confirmed' small


def _f(t, key):
    return (t.get("feat") or {}).get(key)


def _cls_rr(t):
    return ((t.get("factors") or {}).get("rr") or 0) > 0


def _cls_regime(t):
    e = _f(t, "er_setup")
    return None if e is None else e >= 0.30


def _cls_taker(t):
    x = _f(t, "taker_setup")
    if x is None:
        return None
    return (x > 0.5) if t.get("dir") == "long" else (x < 0.5)


def _cls_funding(t):
    f = _f(t, "funding")
    if f is None or f == 0:
        return None
    return (f < 0) if t.get("dir") == "long" else (f > 0)          # against the crowded side


def _cls_btc(t):
    a = _f(t, "btc_align")
    return None if a in (None, 0) else a == 1


def _cls_stop(t):
    s = t.get("stop_pct")
    return None if s is None else s >= 1.0


HYPS = [
    {"id": "H1", "kind": "avg", "mode": "limit", "pick": _conf70, "seen": 180, "test_max": 1, "rules": "r1",
     "title": "Blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Rules r1 (confidence with the bonus), so only r1 runs count and only the first unseen period. Needs 30+ trades "
             "and a 95% range above zero. Superseded by H5."},
    {"id": "H2", "kind": "avg", "mode": "limit", "pick": _core, "seen": 180, "test_max": 3,
     "title": "Blind-limit order block + FVG + volume profile setups average a positive net R",
     "rule": "Every 180-day period between 181 and 720 days back is a test. Same criterion as H1."},
    {"id": "H3", "kind": "diff", "mode": "limit", "cls": _cls_rr, "expect": -1, "word": "REPLICATED", "seen": 180, "test_max": 1,
     "rules": "r1", "labels": ("with bonus", "without"),
     "title": "Setups that got the reward-to-risk bonus do worse than those without it",
     "rule": "Average net R with the bonus minus without it is negative on the unseen period. Adopted in rule set r2."},
    {"id": "H4", "kind": "avg", "mode": "confirm", "pick": _core, "seen": 360, "test_max": 2,
     "title": "Confirmed entry on order block + FVG + volume profile averages a positive net R",
     "rule": "Confirmed entry = wait for a 5-minute CHoCH/BOS in the zone. Only the periods 361-720 days back are test."},
    {"id": "H5", "kind": "avg", "mode": "limit", "pick": _r2conf70, "seen": 180, "test_max": 3,
     "title": "Under rules r2 (no reward-to-risk bonus), blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Confidence is recomputed without the bonus for older runs. The last 180 days are discovery, because H3 was found there."},
    # ---- registered 2026-09-21 with step 16, before any of these numbers had been computed. One-sided directions, 99.5% range.
    {"id": "H6", "kind": "diff", "mode": "limit", "cls": _cls_regime, "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "labels": ("trending", "ranging"),
     "title": "Shadow feature: setups in a trending regime (efficiency ratio 0.30+) average a higher net R than in a range",
     "rule": "Efficiency ratio of the last 48 closes on the setup timeframe. Needs runs made with step 16 or later."},
    {"id": "H7", "kind": "diff", "mode": "limit", "cls": _cls_taker, "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "labels": ("taker flow with the trade", "against it"),
     "title": "Shadow feature: setups where taker flow agrees with the direction average a higher net R",
     "rule": "Taker-buy share of the last 9 closed setup-timeframe candles above 50% for longs, below for shorts."},
    {"id": "H8", "kind": "diff", "mode": "limit", "cls": _cls_funding, "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "labels": ("against the crowd", "with the crowd"),
     "title": "Shadow feature: trades against the crowded side of funding average a higher net R",
     "rule": "Longs when the last funding rate is negative and shorts when it is positive, against the opposite."},
    {"id": "H9", "kind": "diff", "mode": "limit", "cls": _cls_btc, "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "labels": ("with BTC trend", "against BTC"),
     "title": "Shadow feature: alt trades in the direction of the BTC bias-timeframe trend average a higher net R",
     "rule": "BTC itself and BTC ranging periods are excluded."},
    {"id": "H10", "kind": "diff", "mode": "limit", "cls": _cls_stop, "expect": 1, "seen": 360, "test_max": 2, "z": Z_MULTI,
     "labels": ("stop 1%+", "stop under 1%"),
     "title": "Stop-size floor: setups whose stop is 1% or more away average a higher net R than tighter ones",
     "rule": "Fees are a fixed percentage, so tight stops pay more in R. The cost-drag table (windows up to 360 days back) suggested it; "
             "only the 361-720 day periods are test."},
    {"id": "H11", "kind": "prop", "mode": "limit", "k": "1.0", "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "title": "Event study: after touching a zone, price reaches +1 ATR in the trade direction before -1 ATR more often than at random moments",
     "rule": "Independent of stops, targets and fees. Measured from the close of the touch candle, against a random moment "
             "and random direction on the same asset."},
    {"id": "H12", "kind": "paired", "mode": "limit", "variant": "be1", "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "title": "Exit experiment: moving the stop to breakeven at +1R improves average net R",
     "rule": "Paired on the same filled trades: variant minus the baseline exit."},
    {"id": "H13", "kind": "paired", "mode": "limit", "variant": "runner", "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "title": "Exit experiment: half off at TP1 and the rest to TP2 with a breakeven stop improves average net R",
     "rule": "Paired on the same filled trades."},
    {"id": "H14", "kind": "paired", "mode": "limit", "variant": "time24", "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "title": "Exit experiment: closing at market after 24 hours improves average net R",
     "rule": "Paired on the same filled trades."},
    {"id": "H15", "kind": "paired", "mode": "limit", "variant": "fixed1r", "expect": 1, "seen": 0, "test_max": 3, "needs": "shadow", "z": Z_MULTI,
     "title": "Exit experiment: taking profit at exactly 1R instead of the structural target improves average net R",
     "rule": "Paired on the same filled trades."},
]

_cache = {"sig": None, "value": None}


def _stats(trs, z=1.96, key="net_r"):
    v = [t[key] for t in trs]
    n = len(v)
    if n == 0:
        return {"n": 0}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    hw = z * sd / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "avg": round(m, 3), "lo": round(m - hw, 3), "hi": round(m + hw, 3), "sd": sd,
            "win": round(sum(1 for t in trs if t.get("result") == "win") / n * 100, 1)}


def _filled(trs):
    return [t for t in trs if not t.get("unfilled") and "net_r" in t and t.get("ts") is not None]


def _age(ts):
    return (REF_TS - ts) / 86400.0


def _label(start):
    return "most recent 180 days" if start == 0 else f"days {start + 1}-{start + BUCKET} back"


def _jobs():
    """Eligible finished runs, newest first, each with the span (in days before REF_TS) it covers."""
    out = []
    if not backtest.DIR.is_dir():
        return out
    for f in backtest.DIR.glob("*.json"):
        try:
            j = json.loads(f.read_text())
        except Exception:
            continue
        p = j.get("params") or {}
        if (j.get("status") != "done" or p.get("style") != STYLE or float(p.get("fee_bp", 0)) != FEE
                or float(p.get("slip_bp", 0)) != SLIP or int(p.get("min_conf", 0)) != 0
                or not (backtest.DIR / f"{j['id']}_trades.json.gz").exists() or "started" not in j):
            continue
        end_ts = j["started"] - int(p.get("offset_days", 0)) * 86400
        start_ts = end_ts - int(p.get("days", 0)) * 86400
        rules = p.get("ruleset") or ("r1" if str(p.get("rules", "")).startswith("r1") else "r2")
        out.append({"id": j["id"], "rules": rules, "from": _age(end_ts), "to": _age(start_ts), "started": j["started"],
                    "mtime": f.stat().st_mtime, "shadow": bool(p.get("shadow"))})
    return sorted(out, key=lambda x: -x["started"])


def _load(job_id):
    try:
        with gzip.open(backtest.DIR / f"{job_id}_trades.json.gz", "rt") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _covered(jobs, a, b):
    """Days of [a, b) (ages in days) covered by the union of the jobs' spans."""
    spans = sorted((max(a, j["from"]), min(b, j["to"])) for j in jobs if j["to"] > a and j["from"] < b)
    total, end = 0.0, a
    for s, e in spans:
        if e <= end:
            continue
        total += e - max(s, end)
        end = e
    return total


def _diff(a, b, z=1.96):
    if a["n"] < 2 or b["n"] < 2:
        return None
    d = a["avg"] - b["avg"]
    se = math.sqrt(a["sd"] ** 2 / a["n"] + b["sd"] ** 2 / b["n"])
    return {"diff": round(d, 3), "lo": round(d - z * se, 3), "hi": round(d + z * se, 3), "n1": a["n"], "n2": b["n"]}


def _prop(zs, rs, z=1.96):
    if len(zs) < 5 or len(rs) < 5:
        return None
    pz, pr = sum(zs) / len(zs), sum(rs) / len(rs)
    se = math.sqrt(pz * (1 - pz) / len(zs) + pr * (1 - pr) / len(rs))
    d = (pz - pr) * 100
    return {"diff": round(d, 1), "lo": round(d - z * se * 100, 1), "hi": round(d + z * se * 100, 1), "n1": len(zs), "n2": len(rs),
            "p1": round(pz * 100, 1), "p2": round(pr * 100, 1)}


def _bucket(h, got):
    """Statistics of one period. Returns (row fields, payload to pool across the test periods)."""
    z = h.get("z", 1.96)
    kind = h["kind"]
    if kind == "avg":
        sel = [t for t in _filled(got) if h["pick"](t)]
        st = _stats(sel, z)
        row = {k: v for k, v in st.items() if k != "sd"}
        row["text"] = (f"{st['n']} trades, average {st['avg']:+.2f}R ({z_pct(z)} {st['lo']:+.2f} to {st['hi']:+.2f})" if st["n"] else "no trades")
        return row, sel
    if kind == "diff":
        fl = _filled(got)
        w = [t for t in fl if h["cls"](t) is True]
        wo = [t for t in fl if h["cls"](t) is False]
        if not w or not wo:
            return {"n": 0, "note": "not measurable: no run with this data covers the period", "text": "not measurable: no run with this data covers the period"}, ([], [])
        sw, so = _stats(w, z), _stats(wo, z)
        df = _diff(sw, so, z)
        a, b = h["labels"]
        row = {"n": sw["n"] + so["n"], "diff": df and df["diff"], "lo": df and df["lo"], "hi": df and df["hi"], "n_with": sw["n"],
               "n_without": so["n"], "avg_with": sw["avg"], "avg_without": so["avg"],
               "text": f"{a} {sw['avg']:+.2f}R ({sw['n']}) vs {b} {so['avg']:+.2f}R ({so['n']})"}
        return row, (w, wo)
    if kind == "paired":
        d = [{"net_r": t["exits"][h["variant"]] - t["net_r"]} for t in _filled(got) if (t.get("exits") or {}).get(h["variant"]) is not None]
        st = _stats(d, z)
        if not st["n"]:
            return {"n": 0, "text": "no trades with this data"}, []
        row = {k: v for k, v in st.items() if k not in ("sd", "win")}
        row["text"] = f"{st['n']} trades, variant minus baseline {st['avg']:+.3f}R ({z_pct(z)} {st['lo']:+.3f} to {st['hi']:+.3f})"
        return row, d
    if kind == "prop":
        ev = [t["ev"] for t in got if t.get("ev")]
        zs = [e["fp"].get(h["k"]) for e in ev if e["fp"].get(h["k"]) is not None]
        rs = [e["rb"].get(h["k"]) for e in ev if e["rb"].get(h["k"]) is not None]
        pr = _prop(zs, rs, z)
        if not pr:
            return {"n": len(zs), "text": f"{len(zs)} zone touches (too few)"}, ([], [])
        return dict(pr, n=len(zs), text=f"{len(zs)} zone touches: {pr['p1']:.0f}% reach +1 ATR first vs {pr['p2']:.0f}% at random ({pr['diff']:+.1f} points)"), (zs, rs)
    return {"n": 0, "text": ""}, []


def z_pct(z):
    return "99.5% range" if z > 2.5 else "95% range"


def _verdict(h, pooled):
    kind, z = h["kind"], h.get("z", 1.96)
    if kind == "avg":
        st = _stats(pooled, z) if pooled else None
        if not st or st["n"] == 0:
            return "UNTESTED: no unseen period has been run yet", "wait", {}
        pl = {k: v for k, v in st.items() if k != "sd"}
        if st["n"] < 30:
            return f"TOO FEW TRADES so far ({st['n']}, need 30+)", "wait", pl
        if st["lo"] > 0:
            return f"CONFIRMED: positive, and the {z_pct(z)} is above zero", "pass", pl
        if st["hi"] < 0:
            return "REJECTED: significantly negative", "fail", pl
        if st["avg"] <= 0:
            return "NOT CONFIRMED: the average is not positive", "fail", pl
        return f"INCONCLUSIVE: average positive, but the {z_pct(z)} includes zero", "open", pl
    if kind == "diff":
        w, wo = pooled
        df = _diff(_stats(w, z), _stats(wo, z), z) if w and wo else None
    elif kind == "paired":
        st = _stats(pooled, z) if pooled else None
        df = ({"diff": st["avg"], "lo": st["lo"], "hi": st["hi"], "n1": st["n"], "n2": st["n"]} if st and st["n"] > 1 else None)
    else:
        zs, rs = pooled
        df = _prop(zs, rs, z)
    if not df:
        return "UNTESTED: no unseen period with this data has been run yet", "wait", {}
    if min(df["n1"], df["n2"]) < 30:
        return f"TOO FEW TRADES so far ({min(df['n1'], df['n2'])}, need 30+)", "wait", df
    e = h["expect"]
    word = h.get("word", "CONFIRMED")
    if e > 0:
        if df["lo"] > 0:
            return f"{word}: better as predicted, and the {z_pct(z)} is above zero", "pass", df
        if df["hi"] < 0:
            return "REVERSED: significantly the opposite way (this does not count as confirmed)", "fail", df
        return ("CONSISTENT with the prediction but not significant", "open", df) if df["diff"] > 0 else ("NOT CONFIRMED: the difference is not in the predicted direction", "fail", df)
    if df["hi"] < 0:
        return f"{word}: worse as predicted, and the {z_pct(z)} is below zero", "pass", df
    if df["lo"] > 0:
        return "REVERSED: significantly the opposite way", "fail", df
    return ("CONSISTENT with the prediction but not significant", "open", df) if df["diff"] < 0 else ("NOT REPLICATED", "fail", df)


def evaluate():
    jobs = _jobs()
    sig = tuple(sorted((j["id"], j["mtime"]) for j in jobs))
    if _cache["sig"] == sig and _cache["value"]:
        return _cache["value"]
    data = {}
    out = []
    for h in HYPS:
        use = [j for j in jobs if (h.get("rules") is None or j["rules"] == h["rules"]) and (h.get("needs") != "shadow" or j["shadow"])]
        seen, trades = set(), []
        for j in use:                                            # newest run first: duplicates keep the newest copy
            if j["id"] not in data:
                data[j["id"]] = _load(j["id"])
            d = data[j["id"]]
            if not d:
                continue
            for t in d.get(h["mode"], []):
                if t.get("ts") is None:
                    continue
                key = (t.get("name"), int(t["ts"] // 60), t.get("dir"), t.get("poi"), t.get("poi_tf"))
                if key not in seen:
                    seen.add(key)
                    trades.append(t)
        by = {}
        for t in trades:
            by.setdefault(max(0, int(_age(t["ts"]) // BUCKET)) * BUCKET, []).append(t)
        first_test = int(math.ceil(h["seen"] / BUCKET)) * BUCKET
        starts = list(range(0, first_test, BUCKET))
        test_starts, missing = [], None
        for k in range(h["test_max"]):
            s0 = first_test + k * BUCKET
            if _covered(use, s0, s0 + BUCKET) >= MIN_COVER:            # a period counts once a run covers 120+ of its 180 days
                test_starts.append(s0)
            elif missing is None:
                missing = s0                                         # the first unseen period nobody has run yet
        rows, pooled = [], None
        for role, ss in (("discovery", starts), ("test", sorted(test_starts + ([missing] if missing is not None else [])))):
            for s0 in ss:
                base = {"offset": s0, "label": _label(s0), "role": role, "job": None}
                if s0 == missing or (role == "discovery" and _covered(use, s0, s0 + BUCKET) < MIN_COVER):
                    rows.append(dict(base, missing=True, text="not run yet"))
                    continue
                row, payload = _bucket(h, by.get(s0, []))
                rows.append(dict(base, **row))
                if role == "test":
                    if pooled is None:
                        pooled = ([], []) if h["kind"] in ("diff", "prop") else []
                    if h["kind"] in ("diff", "prop"):
                        pooled[0].extend(payload[0])
                        pooled[1].extend(payload[1])
                    else:
                        pooled.extend(payload)
        verdict, cls, pl = _verdict(h, pooled if pooled is not None else ([] if h["kind"] in ("avg", "paired") else ([], [])))
        run = None
        if missing is not None:
            run = {"days": BUCKET, "offset_days": missing, "style": STYLE, "fee_bp": FEE, "slip_bp": SLIP, "min_conf": 0,
                   "rules": h.get("rules") or "r2", "shadow": True, "label": f"Run the missing test period ({missing} d ago)"}
        out.append({"id": h["id"], "title": h["title"], "rule": h["rule"], "mode": h["mode"], "kind": h["kind"],
                    "registered": REGISTERED, "windows": rows, "pooled_test": pl, "verdict": verdict, "cls": cls, "run": run})
    value = {"generated": time.time(), "hypotheses": out,
             "windows": [{"job": j["id"], "rules": j["rules"], "shadow": j["shadow"], "from_days_back": round(j["from"]),
                          "to_days_back": round(j["to"])} for j in jobs]}
    _cache["sig"], _cache["value"] = sig, value
    return value


def text():
    d = evaluate()
    L = ["PRE-REGISTERED HYPOTHESES", "Only unseen (test) periods decide a verdict. Runs: intraday, 5+2 bp per side; overlapping runs are pooled once.",
         "H6-H15 use a 99.5% range because ten hypotheses share one family.", ""]
    for h in d["hypotheses"]:
        L.append(f"{h['id']}: {h['title']}")
        L.append(f"   {h['verdict']}")
        for w in h["windows"]:
            L.append(f"   - {w['label']} ({'test' if w['role'] == 'test' else 'seen'}): {w.get('text', '')}")
        if h["run"]:
            L.append(f"   Next: {h['run']['label']}")
        L.append("")
    L.append("A confirmed hypothesis is evidence, not proof: it still needs a live journal that agrees. Past results do not predict future results.")
    return "\n".join(L)
