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


HYPS = [
    {"id": "H1", "kind": "avg", "mode": "limit", "pick": _conf70, "seen": 180, "test_max": 1, "rules": "r1",
     "title": "Blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Rules r1 (confidence with the bonus), so only r1 runs count and only the first unseen period. Needs 30+ trades "
             "and a 95% range above zero. Superseded by H5."},
    {"id": "H2", "kind": "avg", "mode": "limit", "pick": _core, "seen": 180, "test_max": 3,
     "title": "Blind-limit order block + FVG + volume profile setups average a positive net R",
     "rule": "Every 180-day period between 181 and 720 days back is a test. Same criterion as H1."},
    {"id": "H3", "kind": "diff", "mode": "limit", "with": _has_rr, "seen": 180, "test_max": 1, "rules": "r1",
     "title": "Setups that got the reward-to-risk bonus do worse than those without it",
     "rule": "Average net R with the bonus minus without it is negative on the unseen period. Adopted in rule set r2."},
    {"id": "H4", "kind": "avg", "mode": "confirm", "pick": _core, "seen": 360, "test_max": 2,
     "title": "Confirmed entry on order block + FVG + volume profile averages a positive net R",
     "rule": "Confirmed entry = wait for a 5-minute CHoCH/BOS in the zone. Only the periods 361-720 days back are test."},
    {"id": "H5", "kind": "avg", "mode": "limit", "pick": _r2conf70, "seen": 180, "test_max": 3,
     "title": "Under rules r2 (no reward-to-risk bonus), blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Confidence is recomputed without the bonus for older runs. The last 180 days are discovery, because H3 was found there."},
]

_cache = {"sig": None, "value": None}


def _stats(trs):
    v = [t["net_r"] for t in trs]
    n = len(v)
    if n == 0:
        return {"n": 0}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    hw = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
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
                    "mtime": f.stat().st_mtime})
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


def _verdict_avg(st):
    if not st or st["n"] == 0:
        return "UNTESTED: no unseen period has been run yet", "wait"
    if st["n"] < 30:
        return f"TOO FEW TRADES so far ({st['n']}, need 30+)", "wait"
    if st["lo"] > 0:
        return "CONFIRMED: positive, and the 95% range is above zero", "pass"
    if st["hi"] < 0:
        return "REJECTED: significantly negative", "fail"
    if st["avg"] <= 0:
        return "NOT CONFIRMED: the average is not positive", "fail"
    return "INCONCLUSIVE: average positive, but the 95% range includes zero", "open"


def _diff(a, b):
    if a["n"] < 2 or b["n"] < 2:
        return None
    d = a["avg"] - b["avg"]
    se = math.sqrt(a["sd"] ** 2 / a["n"] + b["sd"] ** 2 / b["n"])
    return {"diff": round(d, 3), "lo": round(d - 1.96 * se, 3), "hi": round(d + 1.96 * se, 3), "n1": a["n"], "n2": b["n"]}


def evaluate():
    jobs = _jobs()
    sig = tuple(sorted((j["id"], j["mtime"]) for j in jobs))
    if _cache["sig"] == sig and _cache["value"]:
        return _cache["value"]
    data = {}
    out = []
    for h in HYPS:
        use = [j for j in jobs if h.get("rules") is None or j["rules"] == h["rules"]]
        seen, trades = set(), []
        for j in use:                                            # newest run first: duplicates keep the newest copy
            if j["id"] not in data:
                data[j["id"]] = _load(j["id"])
            d = data[j["id"]]
            if not d:
                continue
            for t in _filled(d.get(h["mode"], [])):
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
            if _covered(use, s0, s0 + BUCKET) >= MIN_COVER:        # a period counts once a run covers 120+ of its 180 days
                test_starts.append(s0)
            elif missing is None:
                missing = s0                                         # the first unseen period nobody has run yet
        rows, pooled_test, pooled_with, pooled_without = [], [], [], []
        for role, ss in (("discovery", starts), ("test", sorted(test_starts + ([missing] if missing is not None else [])))):
            for s0 in ss:
                base = {"offset": s0, "label": _label(s0), "role": role, "job": None}
                got = by.get(s0, [])
                if s0 == missing:
                    rows.append(dict(base, missing=True))
                    continue
                if h["kind"] == "avg":
                    sel = [t for t in got if h["pick"](t)]
                    st = _stats(sel)
                    rows.append(dict(base, **{k: v for k, v in st.items() if k != "sd"}))
                    if role == "test":
                        pooled_test += sel
                else:
                    w = [t for t in got if h["with"](t)]
                    wo = [t for t in got if not h["with"](t)]
                    if not w:
                        rows.append(dict(base, note="not measurable: no run with the bonus covers this period"))
                        continue
                    df = _diff(_stats(w), _stats(wo))
                    rows.append(dict(base, n=len(w) + len(wo), diff=df and df["diff"], lo=df and df["lo"], hi=df and df["hi"],
                                     n_with=len(w), n_without=len(wo), avg_with=_stats(w)["avg"], avg_without=_stats(wo)["avg"]))
                    if role == "test":
                        pooled_with += w
                        pooled_without += wo
        if h["kind"] == "avg":
            st = _stats(pooled_test)
            verdict, cls = _verdict_avg(st if st["n"] else None)
            pooled = {k: v for k, v in st.items() if k != "sd"}
        else:
            df = _diff(_stats(pooled_with), _stats(pooled_without)) if pooled_with else None
            pooled = df or {}
            if not df:
                verdict, cls = "UNTESTED: no unseen period with the bonus present", "wait"
            elif df["hi"] < 0:
                verdict, cls = "REPLICATED: the bonus hurts, and the 95% range is below zero", "pass"
            elif df["diff"] < 0:
                verdict, cls = "CONSISTENT but not significant on the unseen period", "open"
            else:
                verdict, cls = "NOT REPLICATED", "fail"
        run = None
        if missing is not None:
            run = {"days": BUCKET, "offset_days": missing, "style": STYLE, "fee_bp": FEE, "slip_bp": SLIP, "min_conf": 0,
                   "rules": h.get("rules") or "r2", "label": f"Run the missing test period ({missing} d ago)"}
        out.append({"id": h["id"], "title": h["title"], "rule": h["rule"], "mode": h["mode"], "kind": h["kind"],
                    "registered": REGISTERED, "windows": rows, "pooled_test": pooled, "verdict": verdict, "cls": cls, "run": run})
    value = {"generated": time.time(), "hypotheses": out,
             "windows": [{"job": j["id"], "rules": j["rules"], "from_days_back": round(j["from"]), "to_days_back": round(j["to"])} for j in jobs]}
    _cache["sig"], _cache["value"] = sig, value
    return value


def text():
    d = evaluate()
    L = ["PRE-REGISTERED HYPOTHESES", "Only unseen (test) periods decide a verdict. Runs: intraday, 5+2 bp per side; overlapping runs are pooled once.", ""]
    for h in d["hypotheses"]:
        L.append(f"{h['id']}: {h['title']}")
        L.append(f"   {h['verdict']}")
        for w in h["windows"]:
            tag = "test" if w["role"] == "test" else "seen"
            if w.get("missing"):
                L.append(f"   - {w['label']} ({tag}): not run yet")
            elif h["kind"] == "avg":
                L.append(f"   - {w['label']} ({tag}): {w['n']} trades, average {w.get('avg', 0):+.2f}R (95% {w.get('lo', 0):+.2f} to {w.get('hi', 0):+.2f})"
                         if w["n"] else f"   - {w['label']} ({tag}): no trades")
            elif w.get("note"):
                L.append(f"   - {w['label']} ({tag}): {w['note']}")
            elif w.get("diff") is not None:
                L.append(f"   - {w['label']} ({tag}): with bonus {w['avg_with']:+.2f}R ({w['n_with']}) vs without {w['avg_without']:+.2f}R ({w['n_without']})")
        if h["run"]:
            L.append(f"   Next: {h['run']['label']}")
        L.append("")
    L.append("A confirmed hypothesis is evidence, not proof: it still needs a live journal that agrees. Past results do not predict future results.")
    return "\n".join(L)
