"""Optional natural-language layer for the Assistant, on top of Google Gemini.

Off by default: nothing in the app requires this. The rule-based functions in engine.py remain the only
source of numbers (price, RSI, BOS/CHoCH, support/resistance, PnL) - this module never invents data, it only
rewrites an already-computed report into a natural reply, or (for chat()) replies conversationally grounded in
what the app can do and the user's real current state. If GEMINI_API_KEY isn't set in backend/.env, or the API
call fails for any reason (bad key, rate limit, network), the caller gets None back and falls back to plain
text - nothing breaks if you never add a key.

Add to backend/.env yourself:
  GEMINI_API_KEY=AIza...
  GEMINI_MODEL=gemini-3.5-flash     (optional - this is the default: fast, cheap, generally available since
                                     May 2026. gemini-2.5-flash still works too but Google is shutting it down
                                     on 2026-10-16, so it's a poor long-term default.)
"""
import asyncio
import os
import random
import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_state = {"ok": None, "error": None, "calls": 0, "overloaded": False, "truncated": False}

RETRYABLE_STATUS = {503, 429}  # 503 = model overloaded, 429 = rate limited - both transient

# Shared by both prompts below: the instruction that actually fixes the reported bug - without this, nothing
# stops the model producing (and then repeating, once it's in its own recent history) a generic greeting or
# "I'm ready to help" opener instead of substantive analysis.
_NO_GREETING = (
    "Never open with a greeting, an introduction, or a statement that you're ready to help - the person is "
    "already mid-conversation with a working tool, not meeting you for the first time. Jump straight into the "
    "substantive answer to their current question. If an earlier turn in this conversation was a greeting or "
    "a generic readiness statement, that was a mistake - do not repeat or continue that pattern; always answer "
    "the CURRENT question directly and specifically, every time."
)

SYSTEM = (
    "You are the trading assistant inside Trade Companion, a crypto/forex analysis app. You will be given "
    "MARKET DATA (already computed by the app's own rule-based analyst - prices, indicators, structure, PnL) "
    "and the user's question. Write a natural, conversational reply in plain English.\n"
    f"{_NO_GREETING}\n"
    "Rules:\n"
    "- Use ONLY the numbers and facts in the MARKET DATA. Never invent a price, indicator value, or figure "
    "that isn't there.\n"
    "- Don't just reformat the data as a list - synthesize it into what it actually means, the way a trader "
    "would explain it to a colleague.\n"
    "- Keep it tight: a few sentences for a simple question, a short paragraph for a fuller one. No headers, "
    "no bullet-point dumps of every field.\n"
    "- If the data shows a clear setup, you can state a view, but don't be more confident than the data "
    "supports, and don't give financial advice framed as certainty.\n"
    "- If MARKET DATA doesn't actually answer the question, say so plainly instead of padding."
)

CHAT_SYSTEM = (
    "You are the trading assistant inside Trade Companion, a crypto/forex analysis app. The person's message "
    "didn't match one of the app's specific built-in commands, so you're replying directly instead.\n"
    f"{_NO_GREETING}\n"
    "What this app can actually do - only mention things from this list, never claim anything else:\n"
    "- analyze a specific crypto or forex asset (structure, order blocks, FVGs, support/resistance, RSI)\n"
    "- show the best current setups, a crypto or forex market briefing, sentiment, news, the economic calendar\n"
    "- show the person's open positions, PnL, bot status, risk settings, journal stats, or a trade x-ray\n"
    "- run or show a backtest, a weekly digest, or the screener\n"
    "You may also be given CURRENT APP STATE - a real, live snapshot of the person's actual positions and bot "
    "status. If it's there, use it directly to answer questions like \"how am I doing\" with specifics from it, "
    "not a generic description of what the app can do.\n"
    "If their message is a general market/trading question you can reasonably answer from your own general "
    "knowledge (not this app's live data), answer it briefly and say plainly you're not pulling live data for "
    "that particular answer. If it looks like they want one of this app's own commands, point them to the "
    "closest one in your own words - don't recite the list verbatim. Keep it short and conversational. Never "
    "invent a specific number (a price, a PnL figure, an indicator value) that wasn't given to you above."
)


def cfg():
    return {"key": os.getenv("GEMINI_API_KEY", "").strip(), "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()}


def available():
    return bool(cfg()["key"])


def info():
    c = cfg()
    return {"configured": bool(c["key"]), "model": c["model"] if c["key"] else None,
             "ok": _state["ok"], "error": _state["error"], "calls": _state["calls"],
             "overloaded": _state["overloaded"], "truncated": _state["truncated"]}


def _history_contents(history):
    """Recent turns as Gemini "contents", excluding the current question (the caller appends that itself).
    Gemini calls the assistant's own prior turns "model", not "assistant"."""
    contents = []
    for m in (history or [])[-6:-1]:
        role = m.get("role")
        if role in ("user", "assistant") and (m.get("content") or "").strip():
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": m["content"][:2000]}]})
    return contents


async def _call(system, contents, max_tokens, timeout, max_retries=3, base_delay=1.5):
    """Retries only on 503/429 (transient capacity/rate-limit issues) with exponential backoff + jitter -
    everything else (bad key, blocked content, timeout) fails immediately, since retrying those would just
    waste time. Also checks finishReason: a MAX_TOKENS cutoff means the reply is real but incomplete, not a
    failure - the partial text is still returned (better than nothing), but _state['truncated'] is set so the
    caller can label it instead of presenting a cut-off sentence as a finished thought."""
    c = cfg()
    payload_base = {"systemInstruction": {"parts": [{"text": system}]},
                     "generationConfig": {"maxOutputTokens": max_tokens}}
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as h:
                r = await h.post(f"{API_BASE}/{c['model']}:generateContent",
                                 headers={"x-goog-api-key": c["key"], "content-type": "application/json"},
                                 json={**payload_base, "contents": contents})
            if r.status_code != 200:
                if r.status_code in RETRYABLE_STATUS and attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    _state.update(ok=False, error=f"HTTP {r.status_code}, retrying ({attempt+1}/{max_retries})",
                                  overloaded=True, truncated=False)
                    await asyncio.sleep(delay)
                    continue
                _state.update(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}",
                              overloaded=r.status_code in RETRYABLE_STATUS, truncated=False)
                return None
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                reason = data.get("promptFeedback", {}).get("blockReason")
                _state.update(ok=False, error=f"no candidates{f' (blocked: {reason})' if reason else ''}",
                              overloaded=False, truncated=False)
                return None
            finish_reason = candidates[0].get("finishReason")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            if not text:
                _state.update(ok=False, error=f"empty response (finishReason: {finish_reason})",
                              overloaded=False, truncated=False)
                return None
            was_truncated = finish_reason == "MAX_TOKENS"
            _state.update(ok=True, error="truncated: hit max_tokens" if was_truncated else None,
                          calls=_state["calls"] + 1, overloaded=False, truncated=was_truncated)
            return text
        except httpx.TimeoutException:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue
            _state.update(ok=False, error="timed out", overloaded=False, truncated=False)
            return None
        except Exception as e:
            _state.update(ok=False, error=f"{type(e).__name__}: {str(e)[:160]}", overloaded=False, truncated=False)
            return None
    return None


async def rewrite(question, data_text, history=None, max_tokens=1300, timeout=20, extra_context=None):
    """Returns a natural-language reply, or None (with _state updated) if Gemini isn't configured or the call
    failed. Used for open-ended/opinion questions that already matched a specific asset or topic - data_text
    is the real, already-computed report; this only ever rephrases it, never adds to it. extra_context, when
    given, is a short real snapshot of the user's actual state (positions, bot status, remembered notes) from
    engine._quick_state_summary() - injected as its own turn first, exactly like chat() already does, so it
    reads to the model as background it already knows rather than part of the market data or the question."""
    if not cfg()["key"]:
        return None
    contents = _history_contents(history)
    if extra_context:
        contents.append({"role": "user", "parts": [{"text": f"CURRENT APP STATE (background only, not something the person said):\n{extra_context}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood, I'll use that directly when relevant."}]})
    contents.append({"role": "user", "parts": [{"text": f"MARKET DATA:\n{data_text[:6000]}\n\nQUESTION: {question}"}]})
    return await _call(SYSTEM, contents, max_tokens, timeout)


async def chat(question, history=None, max_tokens=800, timeout=20, extra_context=None):
    """Used only when no specific command matched anything (engine.HELP's old fallback) - a free-form reply
    grounded in what the app can do, not real trading data, since none applies to an unmatched message.
    extra_context, when given, is a short real snapshot of the user's actual state (positions, bot status)
    from engine._quick_state_summary() - injected as its own turn, not folded into the question text, so it
    reads to the model as background it already knows rather than something the person just said."""
    if not cfg()["key"]:
        return None
    contents = _history_contents(history)
    if extra_context:
        contents.append({"role": "user", "parts": [{"text": f"CURRENT APP STATE (background only, not something the person said):\n{extra_context}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood, I'll use that directly when relevant."}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    return await _call(CHAT_SYSTEM, contents, max_tokens, timeout)
