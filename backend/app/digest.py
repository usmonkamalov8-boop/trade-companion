"""Weekly digest: one plain-text summary of how the live journal is doing, sent as a push and shown in the app.

It only reports; it never changes a rule. Numbers carry 95% ranges, and small samples say so."""
import asyncio, json, math, os, time
from pathlib import Path
from . import config as C, events, hypotheses, journal, prefs, tz

STATE = C.BASE / "digest_state.json"
SNAP_DIR = Path.home() / "tc_backups"
OFFSITE_STATE = Path.home() / ".tc_offsite_state.json"


def _wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h) * 100, (c + h) * 100


def _ago(ts):
    m = int((time.time() - ts) / 60)
    return f"{m} min" if m < 90 else (f"{m // 60} h" if m < 2880 else f"{m // 1440} days")


def _backup_line():
    try:
        snaps = sorted(d for d in SNAP_DIR.iterdir() if d.is_dir() and (d / "MANIFEST.json").exists())
        line = f"Backups: {len(snaps)} snapshots, newest {_ago(snaps[-1].stat().st_mtime)} ago" if snaps else "Backups: none yet"
    except Exception:
        line = "Backups: not readable"
    try:
        o = json.loads(OFFSITE_STATE.read_text())
        line += f"; off-server copy {_ago(o['last_ok'])} ago ({o.get('provider', '?')})" if o.get("last_ok") else "; off-server copy: never sent"
        if o.get("last_error") and o.get("last_fail", 0) > o.get("last_ok", 0):
            line += f" - the last attempt FAILED: {str(o['last_error'])[:80]}"
    except Exception:
        line += "; off-server copy: not set up"
    return line


def build(days=7):
    now = time.time()
    st, allt = journal.stats(days), journal.stats(365)
    ev = [e for e in events.latest(1000) if e["ts"] >= now - days * 86400]
    alerts = sum(1 for e in ev if e["kind"] == "setup")
    L = [f"WEEKLY DIGEST - {tz.stamp(now)}", ""]
    L.append(f"Last {days} days: {st['logged']} setups logged, {alerts} setup alerts sent, {st['filled']} filled, {st['unfilled']} never filled.")
    if st["n"]:
        ci = _wilson(st["wins"], st["n"])
        L.append(f"Resolved {st['n']}: {st['wins']} reached TP1, {st['losses']} were stopped ({st['win_rate']:.0f}%, 95% range {ci[0]:.0f}-{ci[1]:.0f}%), "
                 f"average {(st['avg_r'] or 0):+.2f}R before fees.")
    else:
        L.append("Nothing has resolved this week.")
    tiers = [b for b in st["by_conf"] if b["n"]]
    if tiers:
        L.append("By confidence: " + "; ".join(f"{b['label']}: {b['wins']}/{b['n']}" for b in tiers))
    rp = st["repaint"]
    if rp["tracked"]:
        L.append(f"Repainting: {rp['rate']:.0f}% of {rp['tracked']} setups disappeared before their candle closed.")
    L += ["", f"Since the journal started (up to 365 days): {allt['logged']} setups, {allt['n']} resolved"
          + (f", {allt['win_rate']:.0f}% TP1, average {(allt['avg_r'] or 0):+.2f}R before fees" if allt["n"] else "") + "."]
    if allt["n"] and allt["n"] < 100:
        ci = _wilson(allt["wins"], allt["n"])
        L.append(f"Still a small sample: with {allt['n']} resolved, the 95% range on the win rate is {ci[0]:.0f}-{ci[1]:.0f}%.")
    try:
        rc = journal.reconcile()
        if not rc.get("error"):
            lines = journal.reconcile_text(rc).splitlines()
            if len(lines) > 1:
                L.append("Live vs backtest: " + lines[1].strip())
    except Exception:
        pass
    try:
        hv = hypotheses.evaluate()["hypotheses"]
        good = [h["id"] for h in hv if h["cls"] == "pass"]
        rev = [h["id"] for h in hv if h["verdict"].startswith("REVERSED")]
        wait = [h["id"] for h in hv if h["cls"] == "wait"]
        L += ["", "Hypotheses: " + (f"confirmed {', '.join(good)}" if good else "none confirmed yet")
              + (f"; reversed {', '.join(rev)}" if rev else "") + (f"; waiting for test runs: {', '.join(wait)}" if wait else "") + "."]
    except Exception:
        pass
    L += ["", _backup_line()]
    L += ["", "Rules stay frozen at " + __import__("app.strategy", fromlist=["x"]).rules_version() + ". Past results do not predict future results."]
    return "\n".join(x for x in L if x is not None)


def send(force=False):
    """Log the digest as a 'digest' event (the push dispatcher forwards it). Returns the text."""
    text = build()
    events.add("digest", "Weekly digest", text, "info")
    s = _load()
    s["last"] = time.strftime("%G-W%V", time.gmtime())
    s["last_ts"] = time.time()
    _save(s)
    return text


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        STATE.write_text(json.dumps(d))
    except Exception:
        pass


async def run():
    await asyncio.sleep(90)
    while True:
        try:
            cfg = prefs.get()["digest"]
            if cfg["enabled"]:
                d = tz.local(time.time())[0]
                week = time.strftime("%G-W%V", time.gmtime())
                if d.weekday() == cfg["day"] and d.hour == cfg["hour"] and _load().get("last") != week:
                    await asyncio.to_thread(send)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("digest error:", e)
        await asyncio.sleep(120)
