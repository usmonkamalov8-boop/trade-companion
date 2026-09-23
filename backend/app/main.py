import asyncio, secrets, time
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from . import backtest, bot, digest, econ, engine, events, hypotheses, journal, llm, market, prefs, push, security, strategy, trade_api, tz, watcher, config as C


@asynccontextmanager
async def lifespan(app):
    tasks = [asyncio.create_task(fn()) for fn in (watcher.run, push.run, econ.run, journal.run, digest.run)]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Trade Companion API", lifespan=lifespan)
SH = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


def auth(authorization: str = Header(default="")):
    tok = authorization.removeprefix("Bearer ").strip()
    if not C.API_TOKEN or not secrets.compare_digest(tok.encode(), C.API_TOKEN.encode()):
        raise HTTPException(401, "bad token")


api = APIRouter(prefix="/api", dependencies=[Depends(auth)])


@app.get("/ping")
async def ping():
    return {"ok": True}


# ------------------------------------------------------------------- bot


@api.get("/status")
async def status():
    st = bot.load()
    out = {"halted": st["halted"], "profiles": st["profiles"],
           "service": bot.service_state(), "time": int(time.time()),
           "account": None, "positions": [], "pnl": None}
    try:
        out["account"] = await bot.account()
        out["positions"] = await bot.positions()
        out["pnl"] = await bot.pnl(7)
    except Exception as e:
        out["error"] = str(e)
    return out


@api.get("/positions")
async def positions():
    try:
        return await bot.positions()
    except Exception as e:
        raise HTTPException(502, str(e))


class RiskIn(BaseModel):
    profile: str
    enabled: bool | None = None
    risk_pct: float | None = Field(None, ge=0.05, le=5)
    max_positions: int | None = Field(None, ge=1, le=10)


@api.get("/risk")
async def get_risk():
    return bot.load()["profiles"]


@api.post("/risk")
async def set_risk(b: RiskIn):
    st = bot.load()
    if b.profile not in st["profiles"]:
        raise HTTPException(404, "unknown profile")
    prof = st["profiles"][b.profile]
    old = dict(prof)
    for k in ("enabled", "risk_pct", "max_positions"):
        v = getattr(b, k)
        if v is not None:
            prof[k] = v
    bot.save(st)
    watcher.sync_known()
    n = b.profile
    if prof["enabled"] != old["enabled"]:
        events.add("profile", f"Profile {n} switched {'on' if prof['enabled'] else 'off'}",
                   "New signals for this profile can be confirmed." if prof["enabled"]
                   else "Signals for this profile are blocked until it is switched on.",
                   "success" if prof["enabled"] else "warning")
    if prof["risk_pct"] != old["risk_pct"]:
        events.add("risk", f"{n}: risk per trade changed", f"{old['risk_pct']:.1f}% -> {prof['risk_pct']:.1f}%", "info")
    if prof["max_positions"] != old["max_positions"]:
        events.add("risk", f"{n}: max positions changed", f"{old['max_positions']} -> {prof['max_positions']}", "info")
    return st["profiles"]


@api.post("/command/{cmd}")
async def command(cmd: str):
    st = bot.load()
    if cmd in ("halt", "resume"):
        st["halted"] = cmd == "halt"
        bot.save(st)
        watcher.sync_known()
        if st["halted"]:
            events.add("command", "Bot halted", "Halt pressed in the app. No new entries until Resume.", "warning")
        else:
            events.add("command", "Bot resumed", "Resume pressed in the app. New entries are allowed again.", "success")
        return {"ok": True, "halted": st["halted"]}
    if cmd == "closeall":
        st["halted"] = True  # stop new entries first
        bot.save(st)
        watcher.sync_known()
        try:
            res = await bot.close_all()
        except Exception as e:
            events.add("command", "Close all failed", str(e)[:200], "error")
            raise HTTPException(502, str(e))
        n, ok = len(res), sum(1 for r in res if r["ok"])
        if n == 0:
            events.add("command", "Close all", "No open positions to close. Bot is halted.", "info")
        elif ok == n:
            events.add("command", "Close all", f"Closed {ok} of {n} positions. Bot is halted.", "success")
        else:
            bad = ", ".join(r["symbol"] for r in res if not r["ok"])
            events.add("command", "Close all: some orders failed", f"Closed {ok} of {n}. Failed: {bad}.", "error")
        return {"ok": all(r["ok"] for r in res), "halted": True, "results": res}
    raise HTTPException(404, "unknown command")


# ---------------------------------------------------------------- activity


@api.get("/events")
async def events_feed(since: int = Query(0, ge=0), wait: int = Query(0, ge=0, le=25),
                      limit: int = Query(100, ge=1, le=300)):
    """Long-poll: returns as soon as an event newer than `since` exists (or after `wait` seconds).
    since=0 returns the latest 200 events."""
    if since == 0:
        rows = events.latest(200)
        if rows or wait == 0:
            return {"events": rows, "last_id": events.last_id()}
    end = time.time() + wait
    while True:
        rows = events.since(since, limit)
        if rows or time.time() >= end:
            break
        await asyncio.sleep(0.5)
    return {"events": rows, "last_id": events.last_id()}


@api.post("/events/test")
async def events_test():
    events.add("system", "Test notification", "If you can see this pop-up, live notifications work.", "info")
    return {"ok": True}



@api.get("/push/info")
async def push_info():
    return push.info()


@api.post("/push/test")
async def push_test(priority: int = Query(3, ge=1, le=5), provider: str = Query("")):
    """Send a test push at a given ntfy priority (1-5) so each level can be given its own sound.
    provider=ntfy or telegram tests that provider alone."""
    try:
        await push.send_test(priority, provider or None)
    except Exception as e:
        raise HTTPException(502, f"Push failed: {e}")
    return {"ok": True}


# ------------------------------------------------------ preferences / diagnostics


class PrefsIn(BaseModel):
    push: dict | None = None
    calendar: dict | None = None
    analyst: dict | None = None
    general: dict | None = None
    setups: dict | None = None
    digest: dict | None = None


def _prefs_view(p):
    """Preferences plus the effective time zone (so the app can show it without a tz database)."""
    out = dict(p)
    out["general"] = {**p["general"], "tz_label": tz.label_now(), "tz_offset_now": tz.offset_now(), "tz_title": tz.zone_title()}
    return out


@api.get("/prefs")
async def prefs_get():
    return _prefs_view(prefs.get())


@api.post("/prefs")
async def prefs_set(b: PrefsIn):
    patch = {k: v for k, v in b.model_dump().items() if v is not None}
    return _prefs_view(prefs.save(patch))


@api.get("/time")
async def time_info():
    """Current time in the user's zone, market hours and ICT sessions converted to it."""
    d = tz.info()
    d["forex"] = engine.market_status("forex")
    return d


@api.post("/setups/test")
async def setups_test():
    journal.test_alert()
    return {"ok": True}


@api.get("/diagnostics")
async def diagnostics():
    st = bot.load()
    return {"time": int(time.time()), "service": bot.service_state(), "halted": st["halted"],
            "events": {"last_id": events.last_id()}, "push": push.info(), "calendar": econ.diag(), "timezone": tz.info(),
            "journal": journal.counts(), "rate_limit": {"until": getattr(market, "_ban", {}).get("until", 0),
                                                         "why": getattr(market, "_ban", {}).get("why", "")},
            "security": await asyncio.to_thread(security.status), "digest": digest._load(), "llm": llm.info()}


@api.get("/digest")
async def digest_get():
    """The weekly digest as text (built now)."""
    return {"text": await asyncio.to_thread(digest.build), "settings": prefs.get()["digest"], "last": digest._load()}


@api.post("/digest/send")
async def digest_send():
    """Send the digest now (it is logged as an event and pushed like the weekly one)."""
    return {"text": await asyncio.to_thread(digest.send)}


# --------------------------------------------------------- economic calendar


@api.get("/calendar")
async def calendar(hours: int = Query(168, ge=1, le=336), impact: str = Query("high"), refresh: int = 0):
    """Forex Factory calendar: upcoming (and the last 2 h of) high-impact events for the tracked currencies."""
    if refresh:
        await econ.refresh(force=True)
    rows = await econ.upcoming(hours, impact if impact in ("high", "medium") else "high")
    return {"events": rows, **econ.status(), "tz": tz.label_now()}


@api.post("/calendar/test")
async def calendar_test():
    econ.test_alert()
    return {"ok": True}


@api.post("/calendar/refresh")
async def calendar_refresh():
    await econ.refresh(force=True)
    return econ.diag()


# ---------------------------------------------------------------- markets


def _kind(m: str) -> str:
    if m not in ("crypto", "forex"):
        raise HTTPException(400, "market must be crypto or forex")
    return m


@api.get("/scanner")
async def scanner(m: str = Query("crypto", alias="market")):
    k = _kind(m)
    return engine.public_rows(await engine.scan(k), k)


def _asset(name: str) -> str:
    n = name.upper()
    if n not in C.CRYPTO and n not in C.FOREX:
        raise HTTPException(400, "unknown asset")
    return n


def _style(s: str | None) -> str:
    return s if s in strategy.STYLES else prefs.get()["analyst"]["style"]


@api.get("/analysis")
async def analysis(name: str, style: str | None = None, focus: str | None = None):
    """Multi-strategy, multi-timeframe analysis of one asset: structured summary plus a text report."""
    n, st = _asset(name), _style(style)
    res = await engine.analyze(n, st)
    label = C.LABELS.get(n, n)
    f = focus if focus in ("topdown", "structure", "ob", "fvg", "sd", "sr", "fib", "trend", "liquidity", "volume", "ict", "poi", "xray") else None
    text = (await engine.xray_report(n, st)) if f == "xray" else \
        strategy.report_text(res, f"{n} ({label})", f, prefs.get()["analyst"]["modules"])
    return {"summary": strategy.public(res, label), "text": text}


@api.get("/screener")
async def screener(m: str = Query("crypto", alias="market"), style: str | None = None):
    """One row per asset: open/closed, bias, active zones, setup status and volume profile."""
    return await engine.screener(_kind(m), _style(style))


@api.get("/heatmap")
async def heatmap(style: str | None = None):
    """Bias score of every asset on every timeframe, plus crypto and forex sentiment summaries."""
    return await engine.heatmap(_style(style))


class CustomSymbolIn(BaseModel):
    symbol: str


@api.get("/symbols/custom")
async def custom_symbols():
    """Currently-tracked custom coins (built-in defaults aren't included here - see C.CRYPTO_BASE for those)."""
    return {"symbols": list(C.CUSTOM_CRYPTO)}


@api.post("/symbols/custom")
async def custom_symbols_add(b: CustomSymbolIn):
    raw = b.symbol.strip().upper().replace(" ", "")
    if not raw:
        raise HTTPException(400, "give a ticker, e.g. SOLUSDT or DOT")
    base = raw[:-4] if raw.endswith("USDT") else raw
    if not (base.isalnum() and 1 < len(base) <= 15):
        raise HTTPException(400, f"'{raw}' doesn't look like a valid ticker")
    if base in C.CRYPTO:
        raise HTTPException(409, f"{base} is already tracked")
    try:
        await market.validate_futures_pair(base + "USDT")
    except ValueError as e:
        raise HTTPException(400, str(e))
    C.add_custom_crypto(base)
    return {"ok": True, "symbol": base, "label": C.LABELS.get(base, base)}


@api.delete("/symbols/custom/{symbol}")
async def custom_symbols_remove(symbol: str):
    base = symbol.strip().upper()
    base = base[:-4] if base.endswith("USDT") else base
    if not C.remove_custom_crypto(base):
        raise HTTPException(404, f"{base} isn't a custom-added symbol")
    return {"ok": True}


@api.get("/chart")
async def chart(name: str, tf: str = "1h", n: int = Query(100, ge=20, le=200), style: str | None = None):
    """Candles and the analyst's structure (zones, levels, BOS/CHoCH) for one asset and timeframe."""
    nm = _asset(name)
    try:
        return await engine.chart_data(nm, tf, _style(style), n)
    except ValueError as ex:
        raise HTTPException(502, str(ex))


class BacktestIn(BaseModel):
    days: int = 90
    offset_days: int = 0
    style: str = "intraday"
    assets: list[str] | None = None
    fee_bp: float = 5.0
    slip_bp: float = 2.0
    min_conf: int = 0
    rules: str = "r2"
    shadow: bool = True


@api.post("/backtest/start")
async def backtest_start(b: BacktestIn):
    try:
        return backtest.start(b.days, b.style, [a.upper() for a in b.assets] if b.assets else None, b.fee_bp, b.slip_bp, b.min_conf, b.offset_days, b.rules, b.shadow)
    except RuntimeError as ex:
        raise HTTPException(409, str(ex))
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@api.get("/backtest/status")
async def backtest_status(detail: int = 1):
    """detail=0 returns only progress (cheap, for polling); detail=1 the full result of the latest run."""
    job = backtest.latest()
    if not job:
        return {"status": "none"}
    if detail and job.get("status") == "done" and job.get("summary_version", 1) < backtest.SUMMARY_VERSION:
        job = await asyncio.to_thread(backtest.refresh_job, job["id"]) or job      # older run: recompute with the current statistics
    return job if detail else backtest.slim(job)


@api.get("/hypotheses")
async def hypotheses_status():
    """The pre-registered hypotheses with a verdict from the unseen windows that have been run so far."""
    return await asyncio.to_thread(hypotheses.evaluate)


@api.post("/backtest/cancel")
async def backtest_cancel():
    return backtest.cancel() or {"status": "none"}


@api.get("/backtest/runs")
async def backtest_runs():
    return {"runs": backtest.runs()}


@api.get("/journal")
async def journal_list(limit: int = Query(40, ge=1, le=200), state: str | None = None,
                       style: str | None = None, name: str | None = None):
    """Logged setups and how they turned out."""
    return {"items": journal.recent(limit, state if state in ("open", "closed") else None,
                                    style if style in strategy.STYLES else None, name.upper() if name else None)}


@api.get("/journal/reconcile")
async def journal_reconcile():
    """Compare the live journal with the latest finished backtest for the same period."""
    rc = journal.reconcile()
    rc["text"] = journal.reconcile_text(rc)
    return rc


@api.get("/journal/stats")
async def journal_stats(days: int = Query(90, ge=1, le=365), style: str | None = None, name: str | None = None):
    return journal.stats(days, style if style in strategy.STYLES else None, name.upper() if name else None)


@api.get("/setups")
async def setups(m: str = Query("crypto", alias="market"), style: str | None = None):
    st = _style(style)
    return {"style": st, "setups": await engine.setups_list(_kind(m), st)}


@api.get("/news")
async def news(category: str = "crypto"):
    if category not in C.FEEDS:
        raise HTTPException(400, "category must be crypto or forex")
    return await market.news(category)


@api.get("/insights")
async def insights(m: str = Query("crypto", alias="market")):
    return {"market": m, "text": await engine.briefing(_kind(m))}


@api.get("/insights/stream")
async def insights_stream(m: str = Query("crypto", alias="market")):
    kind = _kind(m)

    async def gen():
        async for c in engine.typewriter(await engine.briefing(kind)):
            yield c

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8", headers=SH)


class Msg(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[Msg]


@api.post("/chat")
async def chat(b: ChatIn):
    msgs = [m.model_dump() for m in b.messages[-20:]
            if m.role in ("user", "assistant") and m.content.strip()]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "last message must be from the user")

    async def gen():
        try:
            text = await engine.answer(msgs[-1]["content"], msgs)
        except Exception as e:
            text = f"Something went wrong while analysing that: {e}"
        async for c in engine.typewriter(text):
            yield c

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8", headers=SH)


app.include_router(api)
app.include_router(trade_api.router, dependencies=[Depends(auth)])
