"""Setup journal: every setup the analyst produces is logged once, then price is followed to see
whether it reached TP1 or the stop first. Live forward results replace guesses.

Rules (deliberately conservative, so the stats are not flattering):
- A setup is "filled" when price trades through its entry price after the setup was logged.
- If price reaches TP1 before the entry, it is "missed" (never filled).
- On the candle that fills the entry only the stop is checked; TP1 counts from the next candle.
- If the stop and TP1 are both inside one candle, the stop wins.
- A win is TP1 before the stop (R = reward to TP1). A loss is -1R. Fees and slippage are ignored.
- Setups that never fill expire; filled setups that neither hit TP1 nor the stop time out at market."""
import asyncio, json, sqlite3, time
from . import analytics as A, config as C, events, prefs, strategy

DB = C.BASE / "journal.db"
LIFE = {"scalp": 8 * 3600, "intraday": 36 * 3600, "swing": 10 * 86400}          # unfilled setups expire
MAX_OPEN = {"scalp": 24 * 3600, "intraday": 4 * 86400, "swing": 30 * 86400}     # filled setups time out
TF_SEC = {"5m": 300, "1h": 3600, "4h": 14400, "1d": 86400}
SCAN_EVERY = 300
_st = {"last_scan": 0.0, "last_new": 0, "error": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS setups (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, name TEXT, kind TEXT, style TEXT, dir TEXT, status0 TEXT,
  conf INTEGER, conf_raw INTEGER, news_pts INTEGER, poi_type TEXT, poi_tf TEXT, confluence TEXT,
  zone_lo REAL, zone_hi REAL, entry REAL, stop REAL, tp1 REAL, tp2 REAL, rr1 REAL, rr2 REAL, price0 REAL,
  factors TEXT, sig TEXT, state TEXT, activated_ts REAL, closed_ts REAL, result TEXT, r_result REAL,
  mfe_r REAL, mae_r REAL, checked_ts REAL, expires_ts REAL
);
CREATE INDEX IF NOT EXISTS ix_state ON setups(state);
CREATE INDEX IF NOT EXISTS ix_sig ON setups(sig, ts);
"""


def _db():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _db() as con:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(setups)")}
        if "alert_state" not in cols:          # added with instant setup alerts
            con.execute("ALTER TABLE setups ADD COLUMN alert_state TEXT")


init()


# ------------------------------------------------------------------ recording


def record(res, now=None):
    """Log a setup from a strategy.build() result. Returns the new id, or None (nothing to log or duplicate)."""
    now = now or time.time()
    if res.get("error"):
        return None
    s = res["setup"]
    if s["direction"] == "none" or not s.get("poi") or not s.get("factors"):
        return None
    if res["kind"] == "forex" and res["ict"]["session"]["closed"]:
        return None
    z = s["zone"]
    sig = f"{res['name']}|{res['style']}|{s['direction']}|{s['poi']['type']}|{s['poi']['tf']}|{z['low']:.6g}|{z['high']:.6g}"
    with _db() as con:
        if con.execute("SELECT 1 FROM setups WHERE sig=? AND ts>?", (sig, now - 86400)).fetchone():
            return None
        con.execute("UPDATE setups SET state='closed', result='superseded', closed_ts=? "
                    "WHERE name=? AND style=? AND state='pending'", (now, res["name"], res["style"]))
        nfx = s.get("news") or {}
        cur = con.execute(
            "INSERT INTO setups (ts,name,kind,style,dir,status0,conf,conf_raw,news_pts,poi_type,poi_tf,confluence,"
            "zone_lo,zone_hi,entry,stop,tp1,tp2,rr1,rr2,price0,factors,sig,state,expires_ts,alert_state) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, res["name"], res["kind"], res["style"], s["direction"], s["status"], s["confidence"], s["conf_raw"],
             nfx.get("pts", 0), s["poi"]["type"], s["poi"]["tf"], ",".join(s["poi"]["confluence"]),
             z["low"], z["high"], s["entry"], s["stop"], s["tp1"]["price"], s["tp2"]["price"],
             s["risk"]["rr1"], s["risk"]["rr2"], res["price"], json.dumps(s["factors"]), sig, "pending",
             now + LIFE[res["style"]], s["status"] if s["status"] in ("IN ZONE", "READY") else ""))
        return cur.lastrowid


# ------------------------------------------------------------------ outcome tracking


def _ts(t):
    return t / 1000.0 if t > 1e11 else float(t)


def advance(r, c, dur, now):
    """Walk the candles forward for one journal row (a dict). Returns the columns that changed."""
    s = 1 if r["dir"] == "long" else -1
    entry, stop, tp1 = r["entry"], r["stop"], r["tp1"]
    risk = abs(entry - stop) or 1e-9
    state, result = r["state"], r["result"]
    act, closed_ts, r_res = r["activated_ts"], r["closed_ts"], r["r_result"]
    mfe, mae = r["mfe_r"] or 0.0, r["mae_r"] or 0.0
    checked = r["checked_ts"]
    last_close = c["c"][-1] if c["c"] else None
    prev_px = None

    def close(res_, at, rr):
        nonlocal state, result, closed_ts, r_res
        state, result, closed_ts, r_res = "closed", res_, at, rr

    for i in range(len(c["c"])):
        t = _ts(c["t"][i])
        if t < r["ts"] or (checked is not None and t <= checked):
            continue
        if state == "closed":
            break
        if state == "pending" and t > r["expires_ts"]:      # never fill a setup after it has expired
            close("expired", r["expires_ts"], None)
            break
        if state == "active" and t - act > MAX_OPEN[r["style"]]:
            close("timeout", t, s * (prev_px - entry) / risk if prev_px is not None else 0.0)
            break
        hi, lo = c["h"][i], c["l"][i]
        is_closed = t + dur <= now
        if state == "pending":
            if lo <= entry <= hi:
                state, act = "active", t
            elif (s == 1 and hi >= tp1) or (s == -1 and lo <= tp1):
                close("missed", t, None)
            elif (s == 1 and lo <= stop) or (s == -1 and hi >= stop):
                close("invalid", t, None)
        if state == "active":
            if s == 1:
                mfe, mae = max(mfe, (hi - entry) / risk), min(mae, (lo - entry) / risk)
                sl_hit, tp_hit = lo <= stop, hi >= tp1
            else:
                mfe, mae = max(mfe, (entry - lo) / risk), min(mae, (entry - hi) / risk)
                sl_hit, tp_hit = hi >= stop, lo <= tp1
            if sl_hit:
                close("loss", t, -1.0)
            elif tp_hit and t > act:
                close("win", t, s * (tp1 - entry) / risk)
        prev_px = c["c"][i]
        if is_closed:
            checked = t
        if state == "closed":
            break
    if state == "pending" and now > r["expires_ts"]:
        close("expired", now, None)
    if state == "active" and now - (act or now) > MAX_OPEN[r["style"]]:
        px = last_close if last_close is not None else entry
        close("timeout", now, s * (px - entry) / risk)
    out = {"state": state, "result": result, "activated_ts": act, "closed_ts": closed_ts, "r_result": r_res,
           "mfe_r": mfe, "mae_r": mae, "checked_ts": checked}
    return {k: v for k, v in out.items() if v != r.get(k)}


async def resolve_all(now=None):
    from . import market
    now = now or time.time()
    with _db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM setups WHERE state IN ('pending','active')")]
    groups = {}
    for r in rows:
        groups.setdefault((r["name"], r["kind"]), []).append(r)
    for (name, kind), rs in groups.items():
        age = now - min((r["checked_ts"] or r["ts"]) for r in rs)
        tf = "5m" if age <= 20 * 3600 else "1h" if age <= 10 * 86400 else "4h" if age <= 45 * 86400 else "1d"
        try:
            c = await market.klines_tf(name, kind, tf)
        except Exception as e:
            _st["error"] = f"{name} {tf}: {e}"
            continue
        for r in rs:
            ch = advance(r, c, TF_SEC[tf], now)
            if ch:
                cols = ", ".join(f"{k}=?" for k in ch)
                with _db() as con:
                    con.execute(f"UPDATE setups SET {cols} WHERE id=?", (*ch.values(), r["id"]))


# ------------------------------------------------------------------ statistics


def _rows(days, style=None, name=None):
    q, a = "SELECT * FROM setups WHERE ts>=?", [time.time() - days * 86400]
    if style:
        q, a = q + " AND style=?", a + [style]
    if name:
        q, a = q + " AND name=?", a + [name]
    with _db() as con:
        return [dict(r) for r in con.execute(q, a)]


def _summ(rows):
    w = sum(1 for r in rows if r["result"] == "win")
    l = sum(1 for r in rows if r["result"] == "loss")
    filled = [r for r in rows if r["result"] in ("win", "loss", "timeout")]
    rs = [r["r_result"] for r in filled if r["r_result"] is not None]
    return {"n": w + l, "wins": w, "losses": l, "win_rate": (w / (w + l) * 100) if w + l else None,
            "avg_r": (sum(rs) / len(rs)) if rs else None}


def stats(days=90, style=None, name=None):
    rows = _rows(days, style, name)
    filled = sum(1 for r in rows if r["result"] in ("win", "loss", "timeout"))
    unfilled = sum(1 for r in rows if r["result"] in ("missed", "expired", "invalid"))
    out = {"days": days, "logged": len(rows), "open": sum(1 for r in rows if r["state"] != "closed"),
           "filled": filled, "unfilled": unfilled,
           "fill_rate": (filled / (filled + unfilled) * 100) if filled + unfilled else None, **_summ(rows)}
    buckets = (("Low (under 50)", 0, 50), ("Medium (50-69)", 50, 70), ("High (70+)", 70, 101))
    out["by_conf"] = [{"label": lab, **_summ([r for r in rows if lo <= (r["conf_raw"] or 0) < hi])} for lab, lo, hi in buckets]
    out["by_style"] = [{"label": st, **_summ([r for r in rows if r["style"] == st])} for st in strategy.STYLES]
    types = {}
    for r in rows:
        types.setdefault(r["poi_type"], []).append(r)
    out["by_poi"] = sorted(({"label": k, **_summ(v)} for k, v in types.items() if _summ(v)["n"]), key=lambda x: -x["n"])[:6]
    return out


def similar(style, poi_type, direction, name=None, days=180):
    """Resolved journal results for setups like this one (same style, POI type and direction)."""
    rows = [r for r in _rows(days, style) if r["poi_type"] == poi_type and r["dir"] == direction]
    allr = _summ(rows)
    asset = _summ([r for r in rows if r["name"] == name]) if name else None
    return {"all": allr, "asset": asset}


def similar_line(style, poi_type, direction, name=None):
    sm = similar(style, poi_type, direction, name)
    a = sm["all"]
    if a["n"] < 5:
        return f"Journal: still collecting data for this setup type ({a['n']} resolved so far)."
    line = (f"Journal: {a['n']} resolved {style} {direction} setups with POI type {poi_type} so far: {a['wins']} reached TP1 "
            f"before the stop ({a['win_rate']:.0f}%), average {a['avg_r']:+.2f}R.")
    b = sm["asset"]
    if b and b["n"] >= 5:
        line += f" On {name} alone: {b['n']} resolved, {b['win_rate']:.0f}% hit TP1."
    return line + " Live forward results, small sample."


def recent(limit=40, state=None, style=None, name=None):
    q, a = "SELECT * FROM setups WHERE 1=1", []
    if state == "open":
        q += " AND state IN ('pending','active')"
    elif state == "closed":
        q += " AND state='closed' AND result!='superseded'"
    if style:
        q, a = q + " AND style=?", a + [style]
    if name:
        q, a = q + " AND name=?", a + [name]
    q += " ORDER BY ts DESC LIMIT ?"
    a.append(max(1, min(int(limit), 200)))
    with _db() as con:
        rows = [dict(r) for r in con.execute(q, a)]
    out = []
    for r in rows:
        dec = None if r["kind"] == "crypto" else C.FOREX.get(r["name"], (None, None))[1]
        f = lambda x: A.fmt(x, dec)
        out.append({"id": r["id"], "ts": r["ts"], "name": r["name"], "style": r["style"], "dir": r["dir"],
                    "conf": r["conf"], "conf_raw": r["conf_raw"], "news_pts": r["news_pts"], "status0": r["status0"],
                    "poi": f"{r['poi_type']} {r['poi_tf']}", "confluence": r["confluence"],
                    "zone": f"{f(r['zone_lo'])} - {f(r['zone_hi'])}", "stop": f(r["stop"]), "tp1": f(r["tp1"]),
                    "rr1": round(r["rr1"], 1), "state": r["state"], "result": r["result"],
                    "r": None if r["r_result"] is None else round(r["r_result"], 2),
                    "mfe": None if r["mfe_r"] is None else round(r["mfe_r"], 2), "closed_ts": r["closed_ts"]})
    return out


def counts():
    with _db() as con:
        o = con.execute("SELECT COUNT(*) FROM setups WHERE state IN ('pending','active')").fetchone()[0]
        t = con.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
    return {"open": o, "total": t, "last_scan": _st["last_scan"], "last_new": _st["last_new"], "error": _st["error"]}


# ------------------------------------------------------------------ instant setup alerts

_RANK = {"": 0, "IN ZONE": 1, "READY": 2}
MAX_ALERTS_PER_SCAN = 8


def _sig(res):
    s, z = res["setup"], res["setup"]["zone"]
    return f"{res['name']}|{res['style']}|{s['direction']}|{s['poi']['type']}|{s['poi']['tf']}|{z['low']:.6g}|{z['high']:.6g}"


def _wanted(res, update=False):
    """Does this setup pass the alert filters chosen in Settings > Notifications?"""
    cfg = prefs.get()["setups"]
    s = res["setup"]
    if not cfg["enabled"] or res["style"] not in cfg["styles"] or res["kind"] not in cfg["markets"]:
        return False
    if update and not cfg["on_zone"]:
        return False
    return s["confidence"] >= cfg["min_conf"]


def _status_line(res):
    st = res["setup"]["status"]
    cfg = strategy.STYLES[res["style"]]
    trig = strategy.tfl(cfg["trigger"])
    if st == "READY":
        return f"READY: price is in the zone and {trig} confirmation is present."
    if st == "IN ZONE":
        return f"Price is in the zone: wait for a {trig} CHoCH/BOS before entering."
    if st == "NEWS HOLD":
        n = res["setup"].get("news") or {}
        w = n.get("worst") or {}
        return f"NEWS HOLD: {w.get('currency', '')} {w.get('title', 'a high-impact release')} is imminent. Do not enter yet."
    return "Waiting for price to reach the zone."


def _alert(res, update=False):
    s = res["setup"]
    stg = s["strings"]
    d = "LONG" if s["direction"] == "long" else "SHORT"
    if update:
        title = f"Setup update: {res['name']} {d} ({res['style']}, confidence {s['confidence']}) - {s['status']}"
    else:
        title = f"New {res['style']} setup: {res['name']} {d} (confidence {s['confidence']})"
    text = (f"Zone {stg['entry']}, stop {stg['stop']}, TP1 {stg['tp1']} ({s['risk']['rr1']:.1f}R). "
            + _status_line(res))
    if s.get("vp_tags"):
        text += f" Volume: {', '.join(s['vp_tags'])}."
    level = "success" if s["status"] == "READY" else ("warning" if s["status"] == "NEWS HOLD" else "info")
    events.add("setup", title, text, level)


def process(res, now=None):
    """Log a setup. Returns 'new' for a newly logged setup, 'update' when an already logged, unfilled setup has
    just reached its zone / READY, or None."""
    if record(res, now):
        return "new"
    s = res.get("setup") or {}
    if res.get("error") or s.get("direction", "none") == "none" or not s.get("poi") or not s.get("factors"):
        return None
    rank = _RANK.get(s["status"], 0)
    if not rank:
        return None
    with _db() as con:
        row = con.execute("SELECT id, alert_state FROM setups WHERE sig=? AND state='pending' ORDER BY ts DESC LIMIT 1",
                          (_sig(res),)).fetchone()
        if row and rank > _RANK.get(row["alert_state"] or "", 0):
            con.execute("UPDATE setups SET alert_state=? WHERE id=?", (s["status"], row["id"]))
            return "update"
    return None


def test_alert():
    events.add("setup", "New intraday setup: BTC LONG (confidence 68)",
               "Zone 67,100 - 67,300, stop 66,900, TP1 68,400 (2.1R). Waiting for price to reach the zone. "
               "This is a test of the instant setup alert.", "info")


# ------------------------------------------------------------------ background tracker


async def scan():
    from . import engine
    new = 0
    with _db() as con:
        baseline = con.execute("SELECT COUNT(*) FROM setups").fetchone()[0] == 0   # first ever scan: log silently
    pending = []
    for style in strategy.STYLES:
        for kind, names in (("crypto", list(C.CRYPTO)), ("forex", [n for n in C.FOREX if n != "DXY"])):
            for nm in names:
                try:
                    res = await engine.analyze(nm, style)
                except Exception as e:
                    _st["error"] = f"{nm} {style}: {e}"
                    continue
                what = process(res)
                if what == "new":
                    new += 1
                if what and not baseline and _wanted(res, update=(what == "update")):
                    pending.append((what, res))
    pending.sort(key=lambda x: -x[1]["setup"]["confidence"])
    for what, res in pending[:MAX_ALERTS_PER_SCAN]:
        _alert(res, update=(what == "update"))
    if len(pending) > MAX_ALERTS_PER_SCAN:
        events.add("setup", f"{len(pending) - MAX_ALERTS_PER_SCAN} more setup alerts",
                   "Open Markets > Screener to see all current setups.", "info")
    _st["last_new"] = new


def prune():
    with _db() as con:
        con.execute("DELETE FROM setups WHERE state='closed' AND closed_ts<?", (time.time() - 180 * 86400,))


async def run():
    await asyncio.sleep(45)
    while True:
        try:
            if prefs.get()["analyst"].get("journal", True):
                await scan()
                await resolve_all()
                prune()
                _st["last_scan"] = time.time()
                _st["error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _st["error"] = str(e)[:120]
            print("journal error:", e)
        await asyncio.sleep(prefs.get()["setups"].get("scan_seconds", SCAN_EVERY))
