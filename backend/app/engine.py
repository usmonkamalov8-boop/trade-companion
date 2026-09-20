"""Rule-based 'AI' assistant: turns live data + indicators into plain-language
briefings and answers chat questions. No paid API, no LLM, no keys."""
import asyncio, re, time
from datetime import datetime, timezone
from . import analytics as A, bot, market, config as C

_scan_cache = {}
DISCLAIMER = "Rule-based analysis of live data. Not financial advice."

ALIASES = {
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"], "RENDER": ["render", "rndr"],
    "INJ": ["inj", "injective"], "FET": ["fet", "fetch.ai"],
    "NEAR": ["near protocol"], "AVAX": ["avax", "avalanche"],
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
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")


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


def public_rows(rows):
    keep = ("name", "label", "price", "price_str", "change_pct", "score", "bias",
            "rsi", "atr_pct", "support_str", "resistance_str", "tf")
    return [{k: r[k] for k in keep} for r in rows]


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


async def crypto_briefing():
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


async def forex_briefing():
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
    return "\n".join([f"{cat.upper()} NEWS - tone {tone}", ""] + _headlines(items, 8)
                     + ["", "[+] bullish keywords, [-] bearish keywords (simple keyword scoring, not a full read)."])


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
        d, tzl = econ.local(e["ts"], c["tz"])
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


HELP = ("I'm the built-in market analyst (free, rule-based). Ask me things like:\n"
        "- How are my positions?\n- How did the bot do this week?\n- Is the bot halted?\n"
        "- Risk settings for hier and scalp\n- Analyze BTC / SOL / gold / EURUSD\n"
        "- Crypto briefing / Forex briefing\n- Best setups now\n- News and sentiment\n- Red-folder calendar")


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
    return found


def _has(q, *words):
    return any(re.search(r"\b" + w, q) for w in words)


async def answer(question, history=None):
    q = question.strip()
    ql = q.lower()
    if _has(ql, "calendar", "red folder", "red-folder", "high impact", "high-impact", "economic", "nfp", "cpi", "fomc", "rate decision", "upcoming news"):
        return await calendar_text()
    assets = find_assets(q)
    if not assets and history and _has(ql, "it", "levels", "support", "resistance", "target", "entry", "why", "stop"):
        for m in reversed(history[:-1]):
            if m["role"] == "user":
                assets = find_assets(m["content"])
                if assets:
                    break
    if _has(ql, "forex", "fx") and not any(a in C.FOREX and a not in ("XAUUSD", "DXY") for a in assets):
        return await forex_briefing()
    if assets:
        parts = [await asset_report(n) for n in assets[:2]]
        return "\n\n".join(parts)
    if _has(ql, "position", "trade open", "open trade", "exposure", "my trades"):
        return await positions_text()
    if _has(ql, "pnl", "profit", "performance", "perform", "how did", "how is the bot", "how's the bot", "win rate", "result"):
        return await pnl_text()
    if _has(ql, "status", "halt", "running", "alive", "service", "online", "stopped", "resume"):
        return status_text()
    if _has(ql, "risk", "profile", "hier", "scalp", "setting"):
        return status_text()
    if _has(ql, "forex", "fx", "currenc"):
        return await forex_briefing()
    if _has(ql, "sentiment", "fear", "greed", "mood", "funding"):
        return await sentiment_text()
    if _has(ql, "news", "headline"):
        return await news_text("forex" if _has(ql, "forex", "fx") else "crypto")
    if _has(ql, "best", "strong", "weak", "rank", "setup", "opportunit", "top", "watch"):
        return await ranking_text()
    if _has(ql, "crypto", "market", "overview", "brief", "summary", "today", "now", "outlook", "altcoin"):
        return await crypto_briefing()
    return HELP


async def typewriter(text, size=36, delay=0.012):
    for i in range(0, len(text), size):
        yield text[i:i + size]
        await asyncio.sleep(delay)
