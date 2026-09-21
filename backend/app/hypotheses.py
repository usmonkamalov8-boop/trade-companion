"""Pre-registered hypotheses.

Each hypothesis was written down BEFORE the data that tests it was run. A window is "discovery" if we had already looked
at it when the hypothesis was formed, and "test" if it is data nobody had looked at. Only test windows decide the verdict,
so a result that was found by browsing one window cannot pass by itself.

Windows are 180-day intraday backtests (5 bp fee + 2 bp slippage per side) that end N days ago. The panel reads the saved
trades of the finished backtests, so nothing here re-runs a backtest; it only tells you which window is still missing."""
import gzip, json, math, time
from . import backtest

REGISTERED = "2026-09-21"
DAYS, STYLE, FEE, SLIP = 180, "intraday", 5.0, 2.0


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
    {"id": "H1", "kind": "avg", "mode": "limit", "pick": _conf70, "discovery": [0], "test": [180],
     "title": "Blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Rules r1 (confidence with the bonus), so only the r1 test window counts. Needs 30+ trades and a 95% range above zero. "
             "Superseded by H5 for later windows."},
    {"id": "H2", "kind": "avg", "mode": "limit", "pick": _core, "discovery": [0], "test": [180, 365],
     "title": "Blind-limit order block + FVG + volume profile setups average a positive net R",
     "rule": "Same criterion as H1."},
    {"id": "H3", "kind": "diff", "mode": "limit", "with": _has_rr, "discovery": [0], "test": [180],
     "title": "Setups that got the reward-to-risk bonus do worse than those without it",
     "rule": "Average net R with the bonus minus without it is negative on the test window. Adopted in rule set r2."},
    {"id": "H4", "kind": "avg", "mode": "confirm", "pick": _core, "discovery": [0, 180], "test": [365],
     "title": "Confirmed entry on order block + FVG + volume profile averages a positive net R",
     "rule": "Confirmed entry = wait for a 5-minute CHoCH/BOS in the zone. Only the 365-days-ago window is unseen."},
    {"id": "H5", "kind": "avg", "mode": "limit", "pick": _r2conf70, "discovery": [0], "test": [180, 365],
     "title": "Under rules r2 (no reward-to-risk bonus), blind-limit setups with confidence 70+ average a positive net R",
     "rule": "Confidence is recomputed without the bonus for older runs. Window 0 is discovery, because H3 was found there."},
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
    return [t for t in trs if not t.get("unfilled") and "net_r" in t]


def _windows():
    """Latest finished 180-day intraday job per 'ended N days ago'."""
    out = {}
    if not backtest.DIR.is_dir():
        return out
    for f in sorted(backtest.DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text())
        except Exception:
            continue
        p = j.get("params") or {}
        if (j.get("status") != "done" or p.get("days") != DAYS or p.get("style") != STYLE
                or float(p.get("fee_bp", 0)) != FEE or float(p.get("slip_bp", 0)) != SLIP
                or int(p.get("min_conf", 0)) != 0):
            continue
        off = int(p.get("offset_days", 0))
        if off not in out and (backtest.DIR / f"{j['id']}_trades.json.gz").exists():
            out[off] = j
    return out


def _load(job_id):
    try:
        with gzip.open(backtest.DIR / f"{job_id}_trades.json.gz", "rt") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _label(off):
    return "most recent 180 days" if off == 0 else f"days {off + 1}-{off + DAYS} back"


def _verdict_avg(st):
    if not st or st["n"] == 0:
        return "UNTESTED: no test window has been run yet", "wait"
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
    wins = _windows()
    sig = tuple(sorted((o, j["id"]) for o, j in wins.items()))
    if _cache["sig"] == sig and _cache["value"]:
        return _cache["value"]
    data = {o: _load(j["id"]) for o, j in wins.items()}
    out = []
    for h in HYPS:
        rows, pooled_test, pooled_with, pooled_without = [], [], [], []
        for role, offs in (("discovery", h["discovery"]), ("test", h["test"])):
            for off in offs:
                d = data.get(off)
                base = {"offset": off, "label": _label(off), "role": role, "job": wins[off]["id"] if off in wins else None}
                if not d:
                    rows.append(dict(base, missing=True))
                    continue
                fl = _filled(d.get(h["mode"], []))
                if h["kind"] == "avg":
                    sel = [t for t in fl if h["pick"](t)]
                    st = _stats(sel)
                    rows.append(dict(base, **{k: v for k, v in st.items() if k != "sd"}))
                    if role == "test":
                        pooled_test += sel
                else:
                    w = [t for t in fl if h["with"](t)]
                    wo = [t for t in fl if not h["with"](t)]
                    if not w:
                        rows.append(dict(base, note="not measurable: this run used rules without the bonus"))
                        continue
                    df = _diff(_stats(w), _stats(wo))
                    rows.append(dict(base, n=len(w) + len(wo), diff=df and df["diff"], lo=df and df["lo"], hi=df and df["hi"],
                                     n_with=len(w), n_without=len(wo), avg_with=_stats(w)["avg"], avg_without=_stats(wo)["avg"]))
                    if role == "test":
                        pooled_with += w
                        pooled_without += wo
        missing = [r["offset"] for r in rows if r.get("missing") and r["role"] == "test"]
        if h["kind"] == "avg":
            st = _stats(pooled_test)
            verdict, cls = _verdict_avg(st if st["n"] else None)
            pooled = {k: v for k, v in st.items() if k != "sd"}
        else:
            df = _diff(_stats(pooled_with), _stats(pooled_without)) if pooled_with else None
            pooled = df or {}
            if not df:
                verdict, cls = "UNTESTED: no test window with the bonus present", "wait"
            elif df["hi"] < 0:
                verdict, cls = "REPLICATED: the bonus hurts, and the 95% range is below zero", "pass"
            elif df["diff"] < 0:
                verdict, cls = "CONSISTENT but not significant on the test window", "open"
            else:
                verdict, cls = "NOT REPLICATED", "fail"
        run = None
        if missing:
            run = {"days": DAYS, "offset_days": missing[0], "style": STYLE, "fee_bp": FEE, "slip_bp": SLIP,
                   "min_conf": 0, "rules": "r2", "label": f"Run the missing test window ({missing[0]} d ago)"}
        out.append({"id": h["id"], "title": h["title"], "rule": h["rule"], "mode": h["mode"], "kind": h["kind"],
                    "registered": REGISTERED, "windows": rows, "pooled_test": pooled, "verdict": verdict, "cls": cls, "run": run})
    value = {"generated": time.time(), "hypotheses": out,
             "windows": {str(o): {"job": j["id"], "rules": (j.get("params") or {}).get("rules"), "label": _label(o)} for o, j in wins.items()}}
    _cache["sig"], _cache["value"] = sig, value
    return value


def text():
    d = evaluate()
    L = ["PRE-REGISTERED HYPOTHESES", "Only unseen (test) windows decide a verdict. Windows: 180 days, intraday, 5+2 bp per side.", ""]
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
