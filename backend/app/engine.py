"""Rule-based 'AI' assistant: turns live data + indicators into plain-language
briefings and answers chat questions.

All the numbers here (price, RSI, BOS/CHoCH, PnL, ...) come from the rule-based analysis in this file - no LLM
is involved in computing any of them, ever. For a handful of open-ended/opinion questions (see _natural below),
the finished report text is optionally handed to Gemini (llm.py) purely to phrase it as a natural reply; if no
GEMINI_API_KEY is set, or the call fails for any reason, the plain report text is returned unchanged.
Everything else (screener, backtest, digest, journal, positions, PnL, status, calendar) always stays literal,
since those are precise-data requests where a paraphrase could blur or misstate a number."""
import asyncio, re, time
from datetime import datetime, timezone
from . import analytics as A, backtest, bot, digest, events, hypotheses, journal, llm, market, prefs, strategy, tz as TZ, config as C

_scan_cache = {}
DISCLAIMER = "Rule-based analysis of live data. Not financial advice."

ALIASES = {
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"], "RENDER": ["render", "rndr"],
    "INJ": ["inj", "injective"], "FET": ["fet", "fetch.ai"],
    "NEAR": ["near protocol"], "AVAX": ["avax", "avalanche"],
    "OP": ["optimism", "opusdt"], "XRP": ["xrp", "ripple"], "TRX": ["trx", "tron"], "DOGE": ["doge", "dogecoin"],
    "EURUSD": ["eurusd", "eur/usd", "eur usd", "euro"],
    "GBPUSD": ["gbpusd", "gbp/usd", "pound", "sterling", "cable", "gbp"],
    "USDJPY": ["usdjpy", "usd/jpy", "yen", "jpy"],
    "USDCHF": ["usdchf", "usd/chf", "franc", "chf"],
    "AUDUSD": ["audusd", "aud/usd", "aussie", "aud"],
    "USDCAD": ["usdcad", "usd/cad", "loonie", "cad"],
    "NZDUSD": ["nzdusd", "nzd/usd", "kiwi", "nzd"],
    "XAUUSD": ["xauusd", "xau/usd", "xau", "gold"],
    "DXY": ["dxy", "dollar index", "us dollar", "dollar"],
}


def _now():
    return TZ.stamp()


async def _safe(coro):
    try:
        return await coro
    except Exception:
        return None


def _pct(a, b):
    return (a - b) / b * 100 if b else 0.0


# ---------------------------------------------------------------------- scan


async def scan(kind):
    hit = _scan_cache.get(kind)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    names = C.CRYPTO if kind == "crypto" else list(C.FOREX)
    old = {r["name"]: r for r in (hit[1] if hit else [])}

    async def one(n):
        try:
            tfs = await (market.crypto_tfs(n) if kind == "crypto" else market.forex_tfs(n))
            dec = None if kind == "crypto" else C.FOREX[n][1]
            return A.asset_view(n, C.LABELS.get(n, n), tfs, kind, dec) or old.get(n)
        except Exception:
            return old.get(n)

    rows = [r for r in await asyncio.gather(*[one(n) for n in names]) if r]
    _scan_cache[kind] = (time.time(), rows)
    return rows


def market_status(kind):
    """Open / closed state of a market. Spot forex and gold are closed from Friday 17:00 to Sunday 17:00 New York."""
    if kind == "crypto":
        return {"open": True, "text": "Crypto trades 24/7", "session": "24/7"}
    ss = strategy.session_info(kind="forex")
    if ss["closed"]:
        m = ss.get("reopen_min", 0)
        return {"open": False, "text": f"Market Closed (Weekend). Reopens {ss['reopen_text']}, in {m // 60} h {m % 60} min.",
                "session": "Closed", "reopen_min": m}
    return {"open": True, "text": f"Forex and gold are open. Session: {ss['name']} (New York {ss['ny_time']}, your time {ss['local_time']} {ss['tz']}).",
            "session": ss["name"]}


def public_rows(rows, kind="crypto"):
    keep = ("name", "label", "price", "price_str", "change_pct", "score", "bias",
            "rsi", "atr_pct", "support_str", "resistance_str", "tf")
    ms = market_status(kind)
    out = []
    for r in rows:
        d = {k: r[k] for k in keep}
        d["open"], d["status"] = ms["open"], ("Open 24/7" if kind == "crypto" else ("Open" if ms["open"] else "Closed (Weekend)"))
        if not ms["open"]:                 # no bias or signals for a closed market
            d["bias"], d["score"] = "Market Closed", 0
        out.append(d)
    return out


# --------------------------------------------------------------- text pieces


def _rsi_s(x):
    return "-" if x is None else f"{x:.0f}"


def _tf_line(a):
    parts = []
    for k in ("1h", "4h", "1d"):
        t = a["tf"].get(k)
        if t:
            parts.append(f"{k.upper()} {t['bias']} ({t['score']:+d}, RSI {_rsi_s(t['rsi'])})")
    return "\n".join(parts)


def _align(side, score):
    if score >= 15:
        return "aligned with the bias" if side == "LONG" else "AGAINST the bias"
    if score <= -15:
        return "aligned with the bias" if side == "SHORT" else "AGAINST the bias"
    return "bias is neutral"


def _pos_line(p, row):
    s = f"{p['symbol']} {p['side']} {p['qty']:g} @ {A.fmt(p['entry'])}, mark {A.fmt(p['mark'])}, uPnL {p['pnl']:+.2f}"
    if p.get("liq"):
        s += f", liq {A.fmt(p['liq'])} ({abs(_pct(p['liq'], p['mark'])):.1f}% away)"
    if row:
        s += f" - {_align(p['side'], row['score'])} ({row['bias']})"
    return s


def _funding_note(avg):
    if avg > 0.03:
        return "longs are crowded (squeeze risk)"
    if avg > 0.01:
        return "longs pay a small premium"
    if avg < -0.01:
        return "shorts are paying (crowded shorts)"
    return "balanced"


def _headlines(items, n=6):
    out = []
    for i in items[:n]:
        tag = {1: "[+]", -1: "[-]", 0: "[ ]"}[i["sent"]]
        out.append(f"{tag} {i['title']} ({i['source']})")
    return out


# Keywords signaling a genuinely market-moving story, as opposed to routine churn ("X partners with Y",
# ordinary price-action recaps, minor listings). Deliberately broad, not an exhaustive or perfectly precise
# classifier - the goal is filtering OUT noise for the dedicated news feed below, not scoring nuance. Only
# applied to news_text() (the "show me the news" feature) - crypto_briefing/forex_briefing's own incidental
# use of headlines is untouched, since narrowing their sample could quietly change their sentiment read.
_HIGH_IMPACT_KEYWORDS = (
    # macro / rates
    "fed ", "federal reserve", "fomc", "interest rate", "rate hike", "rate cut", "rate decision",
    "cpi", "inflation", "ppi", "nonfarm payroll", "nfp", "jobs report", "unemployment rate", "gdp",
    "ecb", "boe", "boj", "central bank", "powell", "treasury yield", "recession",
    # crypto-specific majors
    "sec ", "etf approv", "etf reject", "halving", "hack", "exploit", "hacked", "exchange collapse",
    "bankrupt", "delist", "regulation", "regulatory", " ban ", "lawsuit", "settlement", "indictment",
    "network upgrade", "hard fork", "mainnet launch", "outage", "depeg", "liquidation cascade", "insolvent",
    # geopolitical / broad risk-off triggers
    "war", "sanctions", "tariff", "election result", "government shutdown", "credit rating", "default",
)


def _is_high_impact(title):
    t = f" {title.lower()} "
    return any(k in t for k in _HIGH_IMPACT_KEYWORDS)


def _counts(rows):
    b = sum(1 for r in rows if r["score"] >= 15)
    s = sum(1 for r in rows if r["score"] <= -15)
    return b, len(rows) - b - s, s


def _rank_line(rows):
    rs = sorted(rows, key=lambda r: r["score"], reverse=True)
    top = ", ".join(f"{r['name']} ({r['score']:+d})" for r in rs[:2])
    bot_ = ", ".join(f"{r['name']} ({r['score']:+d})" for r in rs[-2:][::-1])
    return f"Strongest: {top}. Weakest: {bot_}."


def _usd_index(rows):
    vals = []
    for r in rows:
        if r["name"] in C.USD_QUOTE:
            vals.append(-r["score"])
        elif r["name"] in C.USD_BASE:
            vals.append(r["score"])
    if not vals:
        return None, 0, 0
    avg = sum(vals) / len(vals)
    agree = sum(1 for v in vals if (v > 0) == (avg > 0) and abs(v) >= 15)
    return avg, agree, len(vals)


# ---------------------------------------------------------------- briefings


async def _crypto_briefing_base():
    rows, fng, fund, items, pos = await asyncio.gather(
        scan("crypto"), market.fear_greed(), market.funding(),
        _safe(market.news("crypto")), _safe(bot.positions()))
    items = items or []
    if not rows:
        return "Crypto data is unreachable right now (Binance market data). Try again in a minute."
    L = [f"CRYPTO BRIEFING - {_now()}", "", "Sentiment"]
    if fng:
        L.append(f"- Fear & Greed: {fng['value']} ({A.fng_label(fng['value'])})")
    if fund:
        avg = sum(fund.values()) / len(fund)
        L.append(f"- Funding (avg of {len(fund)} pairs): {avg:+.3f}%, {_funding_note(avg)}")
    m, tone = A.news_tone(items)
    L.append(f"- Headlines: {tone} ({sum(1 for i in items[:20] if i['sent'] > 0)} bullish, "
             f"{sum(1 for i in items[:20] if i['sent'] < 0)} bearish of {min(len(items), 20)})")
    b, n, s = _counts(rows)
    L += ["", "Overview", f"{b} bullish, {n} neutral, {s} bearish across the {len(rows)} pairs.",
          _rank_line(rows), "", "Pairs"]
    for r in rows:
        L.append(f"{r['name']} {r['price_str']} ({r['change_pct']:+.1f}%): {r['bias']} ({r['score']:+d}), RSI {_rsi_s(r['rsi'])}")
        L.append(f"   support {r['support_str']}, resistance {r['resistance_str']}")
    watch = [(r["name"], x) for r in rows for x in r["notes"] if x.startswith("Watch")]
    if watch:
        L += ["", "Setups to watch"] + [f"- {nm}: {x[7:]}" for nm, x in watch[:4]]
    if items:
        L += ["", "Headlines"] + _headlines(items)
    if pos is not None:
        L += ["", "Your open positions"]
        idx = {r["name"] + "USDT": r for r in rows}
        L += [_pos_line(p, idx.get(p["symbol"])) for p in pos] or ["None open."]
    L += ["", DISCLAIMER]
    return "\n".join(L)


async def _forex_briefing_base():
    rows, items = await asyncio.gather(scan("forex"), _safe(market.news("forex")))
    items = items or []
    if not rows:
        return "Forex data is unreachable right now (Yahoo Finance). Try again in a minute."
    idx = {r["name"]: r for r in rows}
    L = [f"FOREX & GOLD BRIEFING - {_now()}", "", "USD view"]
    avg, agree, tot = _usd_index(rows)
    if avg is not None:
        word = A.bias_label(round(avg)).lower()
        L.append(f"- USD strength index {avg:+.0f}: broadly {word} ({agree} of {tot} majors agree)")
    if "DXY" in idx:
        d = idx["DXY"]
        L.append(f"- DXY {d['price_str']}: {d['bias']} ({d['score']:+d}), RSI {_rsi_s(d['rsi'])}")
    if "XAUUSD" in idx:
        g = idx["XAUUSD"]
        L.append(f"- Gold {g['price_str']} ({g['change_pct']:+.1f}%): {g['bias']} ({g['score']:+d})")
        if avg is not None and avg > 15 and g["score"] < -15:
            L.append("  A stronger dollar is weighing on gold.")
        elif avg is not None and avg < -15 and g["score"] > 15:
            L.append("  A softer dollar is supporting gold.")
    m, tone = A.news_tone(items)
    L += [f"- Headlines: {tone}", "", "Majors and gold"]
    for r in rows:
        if r["name"] == "DXY":
            continue
        L.append(f"{r['label']} {r['price_str']} ({r['change_pct']:+.2f}%): {r['bias']} ({r['score']:+d}), RSI {_rsi_s(r['rsi'])}")
        L.append(f"   support {r['support_str']}, resistance {r['resistance_str']}")
    watch = [(r["label"], x) for r in rows for x in r["notes"] if x.startswith("Watch")]
    if watch:
        L += ["", "Setups to watch"] + [f"- {nm}: {x[7:]}" for nm, x in watch[:4]]
    if items:
        L += ["", "Headlines"] + _headlines(items)
    L += ["", DISCLAIMER]
    return "\n".join(L)


async def briefing(kind):
    return await (crypto_briefing() if kind == "crypto" else forex_briefing())


# ------------------------------------------------------------ detail answers


async def asset_report(name):
    kind = "crypto" if name in C.CRYPTO else "forex"
    rows = await scan(kind)
    a = next((r for r in rows if r["name"] == name), None)
    if not a:
        return f"I have no data for {C.LABELS.get(name, name)} right now. Try again in a minute."
    px = a["price"]
    L = [f"{a['label']} ({name})",
         f"Price {a['price_str']} ({a['change_pct']:+.2f}% {'24h' if kind == 'crypto' else 'daily'})",
         f"Overall bias: {a['bias']} ({a['score']:+d})", _tf_line(a),
         f"4H levels: support {a['support_str']} ({_pct(a['support'], px):+.2f}%), "
         f"resistance {a['resistance_str']} ({_pct(a['resistance'], px):+.2f}%)", ""]
    L += [f"- {x}" for x in a["notes"]]
    if kind == "crypto":
        f = await market.funding()
        if name + "USDT" in f:
            L.append(f"- Funding {f[name + 'USDT']:+.3f}%")
        pos = await _safe(bot.positions())
        for p in pos or []:
            if p["symbol"] == name + "USDT":
                L += ["", "Your position", _pos_line(p, a)]
    L += ["", DISCLAIMER]
    return "\n".join(L)


async def positions_text():
    try:
        pos = await bot.positions()
    except Exception as e:
        return f"I can't read your positions: {e}"
    acc = await _safe(bot.account())
    head = []
    if acc:
        head = [f"Balance {acc['balance']:,.2f} USDT, free {acc['available']:,.2f}, uPnL {acc['upnl']:+.2f}", ""]
    if not pos:
        return "\n".join(head + ["No open positions on the tracked pairs."])
    rows = await scan("crypto")
    idx = {r["name"] + "USDT": r for r in rows}
    total = sum(p["pnl"] for p in pos)
    L = head + [f"{len(pos)} open position(s), total uPnL {total:+.2f} USDT", ""]
    L += [_pos_line(p, idx.get(p["symbol"])) for p in pos]
    return "\n".join(L)


async def pnl_text():
    try:
        p = await bot.pnl(7)
    except Exception as e:
        return f"I can't read your trade history: {e}"
    acc = await _safe(bot.account())
    L = ["BOT PERFORMANCE - last 7 days"]
    if acc:
        L.append(f"Balance {acc['balance']:,.2f} USDT (uPnL {acc['upnl']:+.2f})")
    if not p["trades"]:
        L.append("No closed trades with realized PnL in the last 7 days.")
    else:
        wr = p["wins"] / p["trades"] * 100
        L.append(f"Realized PnL {p['total']:+.2f} USDT from {p['trades']} closing fills "
                 f"({p['wins']} wins, {p['losses']} losses, {wr:.0f}% win rate).")
        best = max(p["by_symbol"].items(), key=lambda kv: kv[1])
        worst = min(p["by_symbol"].items(), key=lambda kv: kv[1])
        L.append(f"Best pair {best[0]} ({best[1]:+.2f}), worst {worst[0]} ({worst[1]:+.2f}).")
        L.append("By day: " + ", ".join(f"{d} {v:+.2f}" for d, v in p["by_day"].items()))
    L += ["", "Realized PnL is before fees and funding, and Binance does not tag hier vs scalp, "
          "so it is not split by profile."]
    return "\n".join(L)


def status_text():
    st = bot.load()
    L = [f"Bot service ({C.BOT_SERVICE}): {bot.service_state()}",
         "Trading is HALTED (no new entries)." if st["halted"] else "Trading is running (not halted)."]
    for k, p in st["profiles"].items():
        L.append(f"{k}: {'on' if p['enabled'] else 'off'}{' (shadow, no orders)' if p.get('shadow') else ''}, "
                 f"risk {p['risk_pct']}% per trade, max {p['max_positions']} positions")
    return "\n".join(L)


async def news_text(cat):
    items = await _safe(market.news(cat))
    if not items:
        return "News feeds are unreachable right now."
    m, tone = A.news_tone(items)
    curated = [i for i in items if _is_high_impact(i["title"])]
    lines = [f"{cat.upper()} NEWS - tone {tone}", ""]
    if curated:
        lines += _headlines(curated, 8)
    else:
        # Never show a confusingly empty feed just because nothing hit the high-impact keywords right now -
        # fall back to the most recent items, with a clear note about why they're there.
        lines += _headlines(items, 5)
        lines.append("(no high-impact headlines in the current window - showing the most recent instead)")
    lines += ["", "[+] bullish keywords, [-] bearish keywords (simple keyword scoring, not a full read)."]
    return "\n".join(lines)


async def sentiment_text():
    fng, fund, ci, fi, frows = await asyncio.gather(
        market.fear_greed(), market.funding(), _safe(market.news("crypto")),
        _safe(market.news("forex")), scan("forex"))
    L = ["MARKET SENTIMENT"]
    if fng:
        L.append(f"Crypto Fear & Greed: {fng['value']} ({A.fng_label(fng['value'])})")
    if fund:
        avg = sum(fund.values()) / len(fund)
        L.append(f"Crypto funding avg {avg:+.3f}%: {_funding_note(avg)}")
    if ci:
        L.append(f"Crypto headlines: {A.news_tone(ci)[1]}")
    avg, agree, tot = _usd_index(frows)
    if avg is not None:
        L.append(f"USD strength {avg:+.0f} ({agree} of {tot} majors agree): broadly {A.bias_label(round(avg)).lower()}")
    if fi:
        L.append(f"Forex headlines: {A.news_tone(fi)[1]}")
    return "\n".join(L)


async def ranking_text():
    c, f = await asyncio.gather(scan("crypto"), scan("forex"))
    allr = [r for r in c + f if r["name"] != "DXY"]
    if not allr:
        return "No market data right now. Try again in a minute."
    rs = sorted(allr, key=lambda r: r["score"], reverse=True)
    L = ["STRONGEST TRENDS"] + [f"{r['label']}: {r['bias']} ({r['score']:+d})" for r in rs[:4]]
    L += ["", "WEAKEST TRENDS"] + [f"{r['label']}: {r['bias']} ({r['score']:+d})" for r in rs[-4:][::-1]]
    w = [(r["label"], x) for r in allr for x in r["notes"] if x.startswith("Watch")]
    if w:
        L += ["", "SETUPS TO WATCH"] + [f"- {n}: {x[7:]}" for n, x in w[:5]]
    L += ["", DISCLAIMER]
    return "\n".join(L)


async def calendar_text():
    from . import econ
    rows = await econ.upcoming(hours=96)
    st = econ.status()
    c = econ.cfg()
    if not rows and st["error"]:
        return "The Forex Factory calendar feed is unreachable right now (" + st["error"] + "). Try again in a few minutes."
    L = ["RED-FOLDER CALENDAR - next 4 days (" + ", ".join(sorted(c["cur"])) + "; Gold follows USD)", ""]
    if not rows:
        L.append("No high-impact events in this window.")
    for e in rows:
        d, tzl = econ.local(e["ts"])
        m = e["mins"]
        if m < -1:
            when = "released"
        elif m <= 0:
            when = "now"
        elif m < 60:
            when = f"in {m} min"
        elif m < 1440:
            when = f"in {m // 60}h {m % 60}m"
        else:
            when = f"in {m // 1440}d {(m % 1440) // 60}h"
        L.append(f"{d:%a %d %b %H:%M} ({tzl}) - {e['currency']} {e['title']} - {when}")
        bits = []
        if e["forecast"]:
            bits.append("forecast " + e["forecast"])
        if e["previous"]:
            bits.append("previous " + e["previous"])
        if e["affects"]:
            bits.append("affects " + e["affects"])
        if bits:
            L.append("   " + ", ".join(bits))
    L += ["", "Alerts are pushed 60 and 15 minutes before each release, and at release time. " + DISCLAIMER]
    return "\n".join(L)


# ------------------------------------------------------------ heat map, mini charts, backtest


def _sentiment(avg):
    return ("Bullish" if avg >= 25 else "Mildly bullish" if avg >= 10 else "Bearish" if avg <= -25
            else "Mildly bearish" if avg <= -10 else "Neutral")


async def heatmap(style=None):
    """Bias of every asset on every timeframe (MN to 5m) plus market-wide sentiment, crypto and forex together."""
    style = style if style in strategy.STYLES else _default_style()
    names_c, names_f = list(C.CRYPTO), list(C.FOREX)
    sem = asyncio.Semaphore(4)

    async def one(n):
        async with sem:
            try:
                return n, await analyze(n, style)
            except Exception:
                return n, None

    results = dict(await asyncio.gather(*[one(n) for n in names_c + names_f]))

    def market_block(kind, names):
        rows = []
        for n in names:
            res = results.get(n)
            if not res or res.get("error"):
                continue
            base = {"name": n, "label": C.LABELS.get(n, n)}
            if res.get("closed"):
                rows.append({**base, "open": False, "market_status": "Closed (Weekend)" if res.get("closed_why") == "weekend" else "No fresh data",
                             "price_str": A.fmt(res["price"], res["dec"]) if res.get("price") is not None else "-",
                             "overall": 0, "bias": "Closed", "cells": []})
                continue
            cells, overall = strategy.heat_row(res, style)
            rows.append({**base, "open": True, "market_status": "Open 24/7" if kind == "crypto" else "Open",
                         "price_str": A.fmt(res["price"], res["dec"]), "overall": overall,
                         "bias": "Bullish" if overall >= 20 else "Bearish" if overall <= -20 else "Neutral", "cells": cells})
        open_rows = [r for r in rows if r["open"]]
        avg = sum(r["overall"] for r in open_rows) / len(open_rows) if open_rows else 0
        tf_avg = []
        for i, t in enumerate(strategy.ALL_TFS):
            vals = [r["cells"][i]["score"] for r in open_rows if r["cells"][i]["score"] is not None]
            tf_avg.append({"tf": strategy.tfl(t), "avg": int(round(sum(vals) / len(vals))) if vals else None})
        return {"summary": {"open": len(open_rows), "closed": len(rows) - len(open_rows),
                            "bullish": sum(1 for r in open_rows if r["bias"] == "Bullish"),
                            "bearish": sum(1 for r in open_rows if r["bias"] == "Bearish"),
                            "neutral": sum(1 for r in open_rows if r["bias"] == "Neutral"),
                            "avg": int(round(avg)), "label": _sentiment(avg) if open_rows else "Closed", "tf_avg": tf_avg},
                "rows": rows}

    return {"style": style, "tfs": [strategy.tfl(t) for t in strategy.ALL_TFS],
            "markets": {"crypto": market_block("crypto", names_c), "forex": market_block("forex", names_f)}}


async def heatmap_text(style=None):
    d = await heatmap(style)
    L = [f"MARKET HEAT MAP - {strategy.STYLES[d['style']]['label']} weighting - {_now()}", "Scores run from -100 (bearish) to +100 (bullish).",
         "Columns: " + ", ".join(d["tfs"])]
    for k, title in (("crypto", "CRYPTO"), ("forex", "FOREX AND GOLD")):
        m = d["markets"][k]
        sm = m["summary"]
        L += ["", f"{title}: {sm['label']} (average {sm['avg']:+d}); {sm['bullish']} bullish, {sm['bearish']} bearish, {sm['neutral']} neutral"
              + (f", {sm['closed']} closed" if sm["closed"] else "")]
        for r in sorted((r for r in m["rows"] if r["open"]), key=lambda r: -r["overall"]):
            cells = " ".join(f"{c['score']:+4d}" if c["score"] is not None else "   -" for c in r["cells"])
            L.append(f"{r['name']:<7}{r['overall']:+4d}  {cells}")
    L += ["", DISCLAIMER]
    return "\n".join(L)


async def chart_data(name, tf, style=None, n=100):
    """Candles plus the structure the analyst sees on them (zones, levels, breaks) for the app's mini charts."""
    style = style if style in strategy.STYLES else _default_style()
    tf = tf if tf in strategy.ALL_TFS else "1h"
    n = max(20, min(int(n), 200))
    kind = "crypto" if name in C.CRYPTO else "forex"
    tfs = await market.get_tfs(name, kind, [tf])
    c = tfs.get(tf)
    if not c or len(c["c"]) < 5:
        raise ValueError("no candles for this timeframe")
    total = len(c["c"])
    start = max(0, total - n)

    def secs(t):
        return t / 1000.0 if t > 1e11 else float(t)

    candles = [[secs(c["t"][i]), c["o"][i], c["h"][i], c["l"][i], c["c"][i], c["v"][i]] for i in range(start, total)]
    a = await asyncio.to_thread(strategy.analyze_tf, c, tf) if total >= 40 else None
    zones, levels, events = [], [], []
    if a:
        for z in a["obs"]:
            zones.append({"kind": "OB", "dir": z["dir"], "low": z["low"], "high": z["high"], "x": max(0, z["idx"] - start), "fresh": z["fresh"]})
        for z in a["fvgs"]:
            zones.append({"kind": "FVG", "dir": z["dir"], "low": z["low"], "high": z["high"], "x": max(0, z["idx"] - start), "fresh": z["fresh"]})
        for z in a["sd"]:
            zones.append({"kind": z["type"], "dir": z["dir"], "low": z["low"], "high": z["high"], "x": max(0, z["idx"] - start), "fresh": z["fresh"]})
        vp = a.get("vp")
        if vp:
            levels += [{"label": "POC", "price": vp["poc"], "kind": "vp"}, {"label": "VAH", "price": vp["vah"], "kind": "vp2"},
                       {"label": "VAL", "price": vp["val"], "kind": "vp2"}]
        for ev in a["events"]:
            if ev["idx"] >= start:
                events.append({"type": ev["type"], "dir": ev["dir"], "x": ev["idx"] - start, "level": ev["level"]})
    closed = False
    try:
        res = await analyze(name, style)
        closed = bool(res.get("closed"))
        s = res.get("setup") or {}
        if not closed and s.get("poi") and s.get("zone"):
            zones.append({"kind": "ENTRY", "dir": 1 if s["direction"] == "long" else -1, "low": s["zone"]["low"],
                          "high": s["zone"]["high"], "x": 0, "fresh": True})
            levels += [{"label": "Stop", "price": s["stop"], "kind": "stop"}, {"label": "TP1", "price": s["tp1"]["price"], "kind": "tp"},
                       {"label": "TP2", "price": s["tp2"]["price"], "kind": "tp"}]
    except Exception:
        pass
    dec = None if kind == "crypto" else C.FOREX[name][1]
    return {"name": name, "tf": strategy.tfl(tf), "key": tf, "n": len(candles), "closed": closed, "dec": dec,
            "price": candles[-1][4], "candles": candles, "zones": zones, "levels": levels, "events": events}


def backtest_text(name=None):
    job = backtest.latest_done() or backtest.latest()
    if job and job.get("status") == "done" and job.get("summary_version", 1) < backtest.SUMMARY_VERSION:
        job = backtest.refresh_job(job["id"]) or job              # older run: recompute with the like-for-like baseline
    if not job:
        return ("No backtest has been run yet. Start one in the app: Markets > Backtest (it replays 30-365 days "
                "and takes a few minutes), or say \"run backtest\".")
    p = job["params"]
    off = f", ending {p['offset_days']} days ago" if p.get("offset_days") else ""
    head = (f"BACKTEST - {strategy.STYLES[p['style']]['label']}, {p['days']} days{off}, fees {p['fee_bp'] + p['slip_bp']:.0f} bp per side, "
            f"rules {p.get('rules', 'r1')}")
    if job["status"] == "running":
        pr = job["progress"]
        return f"{head}\nRunning: {pr['pct']}% ({pr.get('current') or '-'}, {pr['done']}/{pr['total']} assets). Check again in a few minutes."
    if job["status"] != "done":
        return f"{head}\nStatus: {job['status']}" + (f" ({job.get('error')})" if job.get("error") else "")

    def line(lab, s):
        if not s or not s["filled"]:
            return f"{lab}: no filled setups"
        rng = f" (95% range {s['win_ci'][0]:.0f}-{s['win_ci'][1]:.0f}%)" if s.get("win_ci") else ""
        base = f"; a random entry with the same risk: {s['baseline']['avg_net_r']:+.2f}R" if s.get("baseline") else ""
        return (f"{lab}: {s['filled']} trades, win rate {s['win_rate']:.0f}%{rng}, average {s['avg_net_r']:+.2f}R after costs, "
                f"total {s['total_net_r']:+.1f}R, profit factor {s['profit_factor'] or 0:.2f}, max drawdown {s['max_dd_r']:.1f}R"
                f" - {s['verdict']}{base}")

    L = [head, ""]
    if name and name in job["assets"] and "all" in job["assets"][name]:
        r = job["assets"][name]
        L += [f"{name}", line("Blind limit, all setups", r["all"]), line("Order block / FVG zones", r["ob_fvg"]),
              line("OB + FVG + volume profile", r["ob_fvg_volume"])]
        rc = (job.get("assets_confirm") or {}).get(name)
        if rc and "all" in rc:
            L.append(line("Confirmed entry", rc["all"]))
        L += ["By confidence: " + "; ".join(f"{b['label']}: {b['filled']} trades, {b['win_rate']:.0f}% wins" for b in r["by_conf"] if b["filled"])]
    else:
        o = job["overall"]
        L += [line("Blind limit, all setups", o["all"]), line("Order block / FVG zones", o["ob_fvg"]),
              line("OB + FVG + volume profile", o["ob_fvg_volume"])]
        oc = job.get("overall_confirm")
        if oc:
            L += [line("Confirmed entry (wait for a 5m CHoCH/BOS in the zone)", oc["all"])]
        L += ["", "By asset (net R):"]
        L += [f"- {a['name']}: {a['filled']} trades, {a['win_rate'] or 0:.0f}% wins, {a['total_net_r']:+.1f}R" for a in job.get("by_asset", [])]
        L += ["", "By confidence: " + "; ".join(f"{b['label']}: {b['filled']} trades, {b['win_rate']:.0f}% wins, {b['avg_net_r']:+.2f}R" for b in o["by_conf"] if b["filled"])]
        if o.get("by_dist"):
            L.append("Fill rate by distance to the zone: " + "; ".join(f"{b['label']}: {b['fill_rate'] or 0:.0f}%" for b in o["by_dist"]))
    L += ["", "Same rules as the live journal: no look-ahead, a win is TP1 before the stop, fees and slippage included. "
          "'Significant' means the 95% range excludes zero; smaller samples cannot prove anything. Past results do not "
          "predict future results.", DISCLAIMER]
    return "\n".join(L)


# ------------------------------------------------- multi-strategy analysis (strategy.py)

_an_cache = {}


def _mods():
    return prefs.get()["analyst"]["modules"]


def _style_of(ql):
    if _has(ql, "scalp"):
        return "scalp"
    if _has(ql, "intraday", "day trad", "day-trad", "daytrad"):
        return "intraday"
    if _has(ql, "swing", "position trad"):
        return "swing"
    return None


_FOCUS = [
    ("topdown", r"top[- ]?down|multi[- ]?timeframe|\bmtf\b|alignment"),
    ("poi", r"\bpois?\b|points? of interest"),
    ("volume", r"volume|\bpoc\b|value area|\bvah\b|\bval\b"),
    ("ob", r"order[- ]?blocks?|\bobs?\b|breaker"),
    ("fvg", r"\bfvgs?\b|fair value|imbalance"),
    ("sd", r"\bsupply\b|\bdemand\b|\bs&d\b|\bsnd\b"),
    ("fib", r"\bfib|retracement|golden pocket|\bote\b|premium|discount|extension"),
    ("trend", r"trend ?lines?|channel|dynamic level|breakout"),
    ("liquidity", r"liquidity|sweep|stop hunt|equal (?:highs|lows)"),
    ("ict", r"\bict\b|inner circle|kill ?zone|silver bullet|power of 3|\bpo3\b"),
    ("structure", r"\bsmc\b|smart money|\bbos\b|choch|market structure|structure"),
    ("sr", r"support|resistance|key levels?|\bs/r\b"),
]


def _focus_of(ql):
    for key, pat in _FOCUS:
        if re.search(pat, ql):
            return key
    return None


async def _news():
    """Upcoming and just-released calendar events for news-risk scoring (None = scoring off or feed down)."""
    if not prefs.get()["analyst"].get("news_scoring", True):
        return None
    try:
        from . import econ
        rows = await econ.upcoming(hours=3, impact="medium", past_h=1)
        if not rows and econ.diag()["count"] == 0:
            return None
    except Exception:
        return None
    return [{"currency": r["currency"], "impact": r["impact"], "title": r["title"], "mins": r["mins"]} for r in rows]


async def analyze(name, style):
    mods = _mods()
    news_on = prefs.get()["analyst"].get("news_scoring", True)
    key = (name, style, tuple(sorted(mods.items())), news_on)
    hit = _an_cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    kind = "crypto" if name in C.CRYPTO else "forex"
    tfs, news, fund = await asyncio.gather(market.get_tfs(name, kind, list(strategy.ALL_TFS)), _news(),
                                           market.funding() if kind == "crypto" else asyncio.sleep(0, {}))
    dec = None if kind == "crypto" else C.FOREX[name][1]
    res = await asyncio.to_thread(strategy.build, name, kind, style, tfs, dec, mods, time.time(), news)
    res["news_active"] = news is not None
    # shadow mode: log extra numbers next to the setup without touching scores, alerts or entries
    try:
        btc = None
        if kind == "crypto" and name != "BTC" and not res.get("error") and not res.get("closed"):
            b = await analyze("BTC", style)
            if b.get("_per") and b["_per"].get("bias") and b["_per"].get("setup"):
                btc = {"bias": b["_per"]["bias"]["trend"], "setup": b["_per"]["setup"]["trend"]}
        res["shadow"] = strategy.shadow_features(res, (fund or {}).get(name + "USDT"), btc) if not res.get("error") else {}
    except Exception:
        res["shadow"] = {}
    _an_cache[key] = (time.time(), res)
    if len(_an_cache) > 200:
        for k in sorted(_an_cache, key=lambda k: _an_cache[k][0])[:50]:
            _an_cache.pop(k, None)
    return res


def _journal_line(res):
    if res.get("error") or not prefs.get()["analyst"].get("journal", True):
        return ""
    s = res["setup"]
    if s["direction"] == "none" or not s.get("poi"):
        return ""
    try:
        return journal.similar_line(res["style"], s["poi"]["type"], s["direction"], res["name"])
    except Exception:
        return ""


async def xray_report(name, style=None):
    style = style if style in strategy.STYLES else _default_style()
    res = await analyze(name, style)
    text = strategy.xray_text(res, f"{name} ({C.LABELS.get(name, name)})")
    if res.get("error"):
        return text
    extra = []
    if not res.get("news_active"):
        extra.append("News scoring is not active (switched off in Settings, or the calendar feed is unavailable).")
    jl = _journal_line(res)
    if jl:
        extra.append(jl)
    tail = "\n\nScores are a rule-based checklist"
    block = ("\n\n" + "\n".join(extra)) if extra else ""
    return text.replace(tail, block + tail) if tail in text else text + block


def journal_text(style=None, name=None):
    st = journal.stats(90, style if style in strategy.STYLES else None, name)
    who = f"{name} " if name else ""
    L = [f"SETUP JOURNAL - {who}{strategy.STYLES[style]['label'] + ' ' if style in strategy.STYLES else ''}last {st['days']} days", ""]
    if not st["logged"]:
        L.append("The journal is empty. Every 5 minutes the server logs new setups and follows price to see whether "
                 "each one reached TP1 or its stop. Results start to appear after a few hours.")
        return "\n".join(L)
    L.append(f"Logged {st['logged']} setups: {st['open']} still open, {st['filled']} filled, {st['unfilled']} never filled.")
    if st["n"]:
        L.append(f"Filled and resolved: {st['n']}. TP1 before the stop: {st['wins']} ({st['win_rate']:.0f}%), "
                 f"stopped out: {st['losses']}. Average result {st['avg_r']:+.2f}R (before fees).")
    else:
        L.append("No setup has resolved yet.")
    rp = st.get("repaint") or {}
    if rp.get("tracked"):
        c, v = rp["confirmed"], rp["vanished"]
        L.append(f"Repainting: {rp['rate']:.0f}% of {rp['tracked']} setups disappeared before their candle closed"
                 + (f"; those that survived: {c['win_rate']:.0f}% TP1 ({c['n']} resolved)" if c["n"] else "")
                 + (f", those that vanished: {v['win_rate']:.0f}% ({v['n']})" if v["n"] else "") + ".")
    rows = [b for b in st["by_conf"] if b["n"]]
    if rows:
        L += ["", "By confidence (setup quality before news):"]
        L += [f"- {b['label']}: {b['n']} resolved, {b['win_rate']:.0f}% TP1, {b['avg_r']:+.2f}R" for b in rows]
    rows = [b for b in st["by_poi"] if b["n"]]
    if rows:
        L += ["", "By zone type:"] + [f"- {b['label']}: {b['n']} resolved, {b['win_rate']:.0f}% TP1" for b in rows]
    L += ["", "Rules: a fill needs price through the entry; if stop and TP1 sit in one candle the stop wins; "
          "fees and slippage are ignored. Small samples are noisy.", DISCLAIMER]
    return "\n".join(L)


def _default_style():
    return prefs.get()["analyst"]["style"]


async def strategy_report(name, style=None, focus=None):
    style = style if style in strategy.STYLES else _default_style()
    res = await analyze(name, style)
    text = strategy.report_text(res, f"{name} ({C.LABELS.get(name, name)})", focus, _mods())
    extra = []
    if name in C.CRYPTO and not res.get("error"):
        pos = await _safe(bot.positions())
        for p in pos or []:
            if p["symbol"] == name + "USDT":
                d = res["setup"]["direction"]
                want = "long" if p["side"] == "LONG" else "short"
                rel = "matches" if d == want else ("goes against" if d != "none" else "has no clear")
                extra.append(f"Your position: {_pos_line(p, None)} - it {rel} the {style} setup direction.")
    if not focus:
        jl = _journal_line(res)
        if jl:
            extra.append(jl)
        try:
            rows = await scan("crypto" if name in C.CRYPTO else "forex")
            r = next((x for x in rows if x["name"] == name), None)
            if r:
                extra.append(f"Indicator snapshot: {r['bias']} ({r['score']:+d}), RSI {_rsi_s(r['rsi'])}, "
                             f"support {r['support_str']}, resistance {r['resistance_str']}.")
        except Exception:
            pass
    tail = "\n\nRule-based analysis of live data."
    block = ("\n\n" + "\n".join(extra)) if extra else ""
    return text.replace(tail, block + tail) if tail in text else text + block


_last_empty_warn = {}  # kind -> last time we logged "every symbol failed", so a broken market doesn't spam events


async def setups_list(kind, style):
    names = list(C.CRYPTO) if kind == "crypto" else [n for n in C.FOREX if n != "DXY"]
    sem = asyncio.Semaphore(4)
    errors = []

    async def one(n):
        async with sem:
            try:
                res = await analyze(n, style)
            except Exception as ex:
                errors.append(f"{n}: {type(ex).__name__}: {str(ex)[:150]}")
                return None
        row = strategy.public(res, C.LABELS.get(n, n))
        if row is not None:
            row["ts"] = time.time()  # when THIS card's numbers were computed - shown in the app as "last analyzed"
        return row

    rows = [r for r in await asyncio.gather(*[one(n) for n in names]) if r and not r.get("error")]
    if not rows and errors:
        # Every symbol failed, not "the market has nothing interesting right now" - these look identical to the
        # app otherwise (an empty screener), so log it once per 10 min per market instead of guessing later.
        last = _last_empty_warn.get(kind, 0)
        if time.time() - last > 600:
            _last_empty_warn[kind] = time.time()
            events.add("warning", f"{kind} screener came back empty - every symbol's fetch failed",
                       f"{len(errors)} failed. Examples: " + "; ".join(errors[:5]), "warning")
    rows.sort(key=lambda r: (0 if r["direction"] != "none" and r.get("poi") else 1, -r["confidence"]))
    return rows


def _screener_summary(rows):
    return {"total": len(rows), "open": sum(1 for r in rows if r.get("open")), "closed": sum(1 for r in rows if not r.get("open")),
            "bullish": sum(1 for r in rows if r.get("bias") == "Bullish"), "bearish": sum(1 for r in rows if r.get("bias") == "Bearish"),
            "in_zone": sum(1 for r in rows if (r.get("zones") or {}).get("in_zone")),
            "ready": sum(1 for r in rows if r.get("status") == "READY")}


async def screener(kind, style):
    rows = await setups_list(kind, style)
    return {"style": style, "market": kind, "market_status": market_status(kind), "summary": _screener_summary(rows), "rows": rows}


async def screener_text(kind=None, style=None):
    style = style if style in strategy.STYLES else _default_style()
    kinds = [kind] if kind else ["crypto", "forex"]
    L = [f"SCREENER - {strategy.STYLES[style]['label']} - {_now()}"]
    for k in kinds:
        d = await screener(k, style)
        sm, ms = d["summary"], d["market_status"]
        L += ["", f"{'CRYPTO' if k == 'crypto' else 'FOREX AND GOLD'}: {ms['text']}",
              f"{sm['bullish']} bullish, {sm['bearish']} bearish, {sm['in_zone']} in a zone, {sm['ready']} ready"]
        for r in d["rows"]:
            if not r.get("open"):
                L.append(f"{r['name']:<7} {r['market_status'].upper()}")
                continue
            z = r["zones"]
            tail = f" | {r['direction'].upper()} {r['status']} {r['confidence']}" if r["direction"] != "none" else ""
            L.append(f"{r['name']:<7} {r['bias']:<8} {r['bias_pct']:+d}% | zones {z['count']}{' (in zone)' if z['in_zone'] else ''}{tail}")
    L += ["", "Ask for details, for example: 'intraday setup BTC' or 'volume profile XRP'.", DISCLAIMER]
    return "\n".join(L)


async def setups_ranking_text(style=None, focus=None):
    style = style if style in strategy.STYLES else _default_style()
    crypto, fx = await asyncio.gather(setups_list("crypto", style), setups_list("forex", style))
    rows = [r for r in crypto + fx if r["direction"] != "none" and r.get("poi")]
    rows.sort(key=lambda r: -r["confidence"])
    L = [f"BEST {strategy.STYLES[style]['label'].upper()} SETUPS - {_now()}", ""]
    if not rows:
        L.append("No clean setups right now: structure and zones do not line up. Waiting is a position.")
    for r in rows[:6]:
        L.append(f"{r['name']} {r['direction'].upper()} [{r['status']}] confidence {r['confidence']} ({r['conf_label']})")
        L.append(f"   {r['poi']} | entry {r['entry']} | stop {r['stop']} | TP1 {r['tp1']} ({r['rr1']}R)")
    rest = [r["name"] for r in crypto + fx if r not in rows]
    if rest:
        L += ["", "No clear setup: " + ", ".join(rest)]
    L += ["", "Ask for details, for example: 'intraday setup BTC', 'order blocks ETH', 'fib gold', 'top-down SOL', "
          "'scalp EURUSD'.", DISCLAIMER]
    return "\n".join(L)


async def _setup_block(kind):
    try:
        style = _default_style()
        rows = await asyncio.wait_for(setups_list(kind, style), 8)
    except Exception:
        return ""
    good = [r for r in rows if r["direction"] != "none" and r.get("poi")][:3]
    if not good:
        return ""
    L = [f"TOP SETUPS ({strategy.STYLES[style]['label']})"]
    for r in good:
        L.append(f"{r['name']} {r['direction'].upper()} [{r['status']}] confidence {r['confidence']}: zone {r['entry']}, stop {r['stop']}, TP1 {r['tp1']} ({r['rr1']}R)")
    return "\n".join(L)


def _insert_block(text, block):
    if not block:
        return text
    tail = "\n\n" + DISCLAIMER
    return text.replace(tail, "\n\n" + block + tail) if tail in text else text + "\n\n" + block


async def crypto_briefing():
    return _insert_block(await _crypto_briefing_base(), await _setup_block("crypto"))


async def forex_briefing():
    ms = market_status("forex")
    if not ms["open"]:
        return "\n".join([f"FOREX AND GOLD - {_now()}", "", "MARKET CLOSED (WEEKEND)", ms["text"], "",
                          "No signals or analysis are produced while the market is closed, so nothing stale is shown. "
                          "Crypto trades 24/7: ask for a crypto briefing.", DISCLAIMER])
    return _insert_block(await _forex_briefing_base(), await _setup_block("forex"))


HELP = ("I'm the built-in market analyst (free, rule-based). Ask me things like:\n"
        "- How are my positions?\n- How did the bot do this week?\n- Is the bot halted?\n"
        "- Risk settings for hier and scalp\n- Analyze BTC / SOL / gold / EURUSD\n"
        "- Crypto briefing / Forex briefing\n- Best setups now / best scalp setups\n- Intraday setup BTC, swing setup gold, scalp EURUSD\n- Order blocks ETH, FVG SOL, fib gold, supply and demand, liquidity, trendlines\n- Top-down analysis of BTC (SMC / ICT)\n- News and sentiment\n- Red-folder calendar")


def find_assets(q):
    ql = q.lower()
    found = []
    for name, keys in ALIASES.items():
        for k in keys:
            if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", ql):
                found.append(name)
                break
    if "NEAR" not in found and re.search(r"\bNEAR\b", q):
        found.append("NEAR")
    if "OP" not in found and re.search(r"\bOP\b", q):       # "op" alone is too common a word: only when written OP
        found.append("OP")
    for name in C.CUSTOM_CRYPTO:                             # user-added coins have no entry in ALIASES yet
        if name not in found and re.search(r"\b" + re.escape(name) + r"\b", q, re.IGNORECASE):
            found.append(name)
    return found


def _has(q, *words):
    return any(re.search(r"\b" + w, q) for w in words)


def _ai_unavailable_note():
    """A short, honest note for when Gemini IS configured but a call just failed (a quota limit, an
    overloaded model, a bad key) - distinct from Gemini never being set up at all, which needs no explanation.
    Without this, a temporary Google-side outage and "the app just doesn't do this" look identical from the
    chat, which is its own real source of confusion."""
    info = llm.info()
    if info.get("overloaded"):
        return "_(the AI assistant is temporarily rate-limited or over its quota - showing the raw analysis instead)_\n\n"
    return "_(the AI assistant is temporarily unavailable - showing the raw analysis instead)_\n\n"


async def _natural(text, question, history=None):
    """Optionally rewrite an already-computed report as a natural reply (see the module docstring). Only
    called for open-ended/opinion-style branches of answer() below - never for exact-data commands."""
    if not llm.available():
        return text
    try:
        rewritten = await llm.rewrite(question, text, history)
    except Exception:
        rewritten = None
    if rewritten:
        return rewritten
    return _ai_unavailable_note() + text


async def _quick_state_summary():
    """A short, best-effort snapshot of the user's actual current state (open positions, bot status) for the
    Assistant to have as background awareness on a general question - e.g. "how's it going" should be able to
    reference real positions, not just describe what the app can do in the abstract. Never used to answer a
    precise data question - those stay in their own exact, literal branches elsewhere in this file; this is
    only extra context for a reply that would otherwise have none at all. Any failure here is silent (returns
    None), since a fallback reply without this extra color is still far better than no reply at all."""
    parts = []
    try:
        pos = await positions_text()
        if pos:
            parts.append(f"Open positions: {pos[:300]}")
    except Exception:
        pass
    try:
        st = status_text()
        if st:
            parts.append(f"Bot status: {st[:200]}")
    except Exception:
        pass
    return "\n".join(parts) if parts else None


async def _chat_fallback(question, history=None, context=None):
    """Nothing in answer() below matched a specific command - this used to always be the static HELP text.
    If an LLM is configured, it now replies naturally instead, grounded in what the app can actually do PLUS
    a quick snapshot of the user's real current state (positions, bot status), so even a vague question gets
    a personalized, situationally-aware reply rather than generic capability-listing text. Falls back to HELP
    on any failure, exactly like _natural() does for the data-grounded branches."""
    if not llm.available():
        return HELP
    try:
        state = await _quick_state_summary()
        reply = await llm.chat(question, history, extra_context=state)
    except Exception:
        reply = None
    if reply:
        return reply
    return _ai_unavailable_note() + HELP


async def order_guidance(question, order, history=None):
    """AI commentary for the order ticket's "Ask AI" panel: given a draft order (symbol, side, entry, stop,
    target, leverage - plus the risk numbers the ticket's own /api/trade/order/preview already computed, like
    risk_pct/rr/liq_est) and the person's question, ask Gemini for genuine, grounded commentary. The order's
    numbers are never recomputed or guessed here - they're passed through exactly as the ticket already shows
    them, so the AI can only comment on real figures, not invent new ones. Falls back to a short, honest
    message if Gemini isn't configured, and to the raw context (still useful on its own) if a call fails."""
    symbol = str(order.get("symbol", "")).strip().upper()
    style = str(order.get("style") or "intraday")
    if not llm.available():
        return "AI commentary isn't turned on yet - add GEMINI_API_KEY in backend/.env to enable this."

    context_text = None
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    if base in C.CRYPTO:
        try:
            report = await strategy_report(base, style, None)
            context_text = f"TECHNICAL ANALYSIS for {base}:\n{report[:3000]}"
        except Exception:
            pass

    order_lines = [f"{k}: {v}" for k, v in order.items() if v is not None and k not in ("style",)]
    order_text = ("DRAFT ORDER BEING CONSIDERED (all numbers below, including risk/reward figures, are already "
                 "computed by the app - use them exactly as given, never recompute or guess a different "
                 "value):\n" + "\n".join(order_lines))
    full_context = f"{context_text}\n\n{order_text}" if context_text else order_text

    try:
        reply = await llm.rewrite(question, full_context, history, max_tokens=900)
    except Exception:
        reply = None
    if reply:
        return reply
    return _ai_unavailable_note() + "Here's the context this would have used:\n\n" + full_context


async def answer(question, history=None, context=None):
    if context and context.get("order"):
        # The order ticket's "Ask AI" panel sends the draft trade directly - this is a distinct use case from
        # the normal chat routing below (a free-form question about a SPECIFIC proposed trade, not a general
        # market question), so it's handled entirely separately rather than folded into the keyword routing.
        return await order_guidance(question, context["order"], history)
    q = question.strip()
    ql = q.lower()
    if _has(ql, "calendar", "red folder", "red-folder", "high impact", "high-impact", "economic", "nfp", "cpi", "fomc", "rate decision", "upcoming news"):
        return await calendar_text()
    if re.search(r"(forex|fx|gold|market|xau).{0,25}(open|closed|hours)|(open|closed).{0,15}(forex|fx|gold|market)|market hours|trading hours|forex hours", ql):
        ms = market_status("forex")
        return (f"Forex and gold: {ms['text']}\nCrypto: trades 24/7.\n"
                f"Weekly forex and gold hours in your time: {TZ.market_hours()} (Friday 17:00 to Sunday 17:00 New York). "
                "No signals are produced while closed.\n"
                f"Kill zones today ({TZ.label_now()}): " + "; ".join(f"{w['name']} {w['start']}-{w['end']}" for w in TZ.sessions()))
    if _has(ql, "heatmap", "heat map", "market sentiment", "sentiment map"):
        return await heatmap_text(_style_of(ql))
    if _has(ql, "digest", "weekly summary", "weekly report"):
        return await asyncio.to_thread(digest.build)
    if _has(ql, "hypothes", "pre-registered", "preregistered"):
        return await asyncio.to_thread(hypotheses.text)
    if _has(ql, "backtest", "back-test", "back test"):
        if _has(ql, "run", "start", "launch"):
            try:
                days = next((int(x) for x in re.findall(r"\b(\d{2,3})\b", ql) if 7 <= int(x) <= 180), 90)
                job = backtest.start(days, _style_of(ql) or _default_style())
                return (f"Backtest started: {job['params']['style']} style, last {days} days, {len(job['params']['assets'])} crypto assets. "
                        "It runs in the background for several minutes. Ask \"backtest results\" or open Markets > Backtest.")
            except Exception as ex:
                return f"Could not start the backtest: {ex}"
        found = find_assets(q)
        return backtest_text(found[0] if found and found[0] in C.CRYPTO else None)
    if _has(ql, "screener", "scanner", "scan all", "scan everything", "scan the market", "scan markets"):
        return await screener_text("crypto" if _has(ql, "crypto") else ("forex" if _has(ql, "forex", "fx") else None), _style_of(ql))
    assets = find_assets(q)
    if not assets and context and context.get("asset"):
        # The person didn't name an asset, but the app told us what they're currently looking at (e.g. the
        # Chart or Markets screen) - use that instead of falling straight through to the generic fallback.
        # Only trusted if it's a real, tracked asset; anything else is silently ignored rather than erroring.
        ctx_asset = str(context["asset"]).strip().upper()
        if ctx_asset in C.CRYPTO or ctx_asset in C.FOREX:
            assets = [ctx_asset]
    if not assets and history and _has(ql, "it", "levels", "support", "resistance", "target", "entry", "why", "stop"):
        for m in reversed(history[:-1]):
            if m["role"] == "user":
                assets = find_assets(m["content"])
                if assets:
                    break
    if _has(ql, "forex", "fx") and not any(a in C.FOREX and a not in ("XAUUSD", "DXY") for a in assets):
        return await _natural(await forex_briefing(), question, history)
    style = _style_of(ql)
    focus = _focus_of(ql)
    if _has(ql, "journal") or (_has(ql, "win rate", "winrate", "track record", "accuracy", "statistics", "stats")
                               and _has(ql, "setup", "analyst", "signals", "confidence", "ai")):
        return journal_text(style, assets[0] if assets else None)
    xr = _has(ql, "x-ray", "xray", "breakdown") or (
        _has(ql, "why", "explain", "how come") and _has(ql, "confiden", "score", "rating", "setup", "trade"))
    if xr:
        if not assets and history:
            for m in reversed(history[:-1]):
                if m["role"] == "user":
                    assets = find_assets(m["content"])
                    if assets:
                        break
        if assets:
            return await xray_report(assets[0], style)
        return "Which asset? For example: \"Trade X-ray BTC\" or \"Why is gold confidence low?\""
    ops = _has(ql, "hier", "halt", "status", "pnl", "balance", "settings") or (_has(ql, "profile") and focus != "volume")
    sw = _has(ql, "setup", "trade idea", "entry", "stop loss", "take profit", "risk reward", "top-down", "top down",
              "strategy", "poi", "zone", "trade plan", "smc", "ict")
    if assets and not ops:
        return await _natural(await strategy_report(assets[0], style, focus), question, history)
    if not assets and (style or focus or sw) and not ops:
        return await _natural(await setups_ranking_text(style, focus), question, history)
    if assets:
        parts = [await asset_report(n) for n in assets[:2]]
        return await _natural("\n\n".join(parts), question, history)
    if _has(ql, "position", "trade open", "open trade", "exposure", "my trades"):
        return await positions_text()
    if _has(ql, "pnl", "profit", "performance", "perform", "how did", "how is the bot", "how's the bot", "win rate", "result"):
        return await pnl_text()
    if _has(ql, "status", "halt", "running", "alive", "service", "online", "stopped", "resume"):
        return status_text()
    if _has(ql, "risk", "profile", "hier", "scalp", "setting"):
        return status_text()
    if _has(ql, "forex", "fx", "currenc"):
        return await _natural(await forex_briefing(), question, history)
    if _has(ql, "sentiment", "fear", "greed", "mood", "funding"):
        return await _natural(await sentiment_text(), question, history)
    if _has(ql, "news", "headline"):
        return await news_text("forex" if _has(ql, "forex", "fx") else "crypto")
    if _has(ql, "best", "strong", "weak", "rank", "setup", "opportunit", "top", "watch"):
        return await _natural(await ranking_text(), question, history)
    if _has(ql, "crypto", "market", "overview", "brief", "summary", "today", "now", "outlook", "altcoin"):
        return await _natural(await crypto_briefing(), question, history)
    return await _chat_fallback(question, history, context)


async def typewriter(text, size=36, delay=0.012):
    for i in range(0, len(text), size):
        yield text[i:i + size]
        await asyncio.sleep(delay)
