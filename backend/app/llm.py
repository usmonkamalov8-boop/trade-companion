"""Optional natural-language layer for the Assistant, on top of Claude via the Anthropic API.

Off by default: nothing in the app requires this. The rule-based functions in engine.py remain the only
source of numbers (price, RSI, BOS/CHoCH, support/resistance, PnL) - this module never invents data, it only
rewrites an already-computed report into a natural reply. If ANTHROPIC_API_KEY isn't set in backend/.env, or the
API call fails for any reason (bad key, rate limit, network), the caller gets None back and falls back to the
plain report text - nothing breaks if you never add a key.

Add to backend/.env yourself:
  ANTHROPIC_API_KEY=sk-ant-...
  ANTHROPIC_MODEL=claude-haiku-4-5-20251001     (optional - this is the default: fast and cheap for this job)
"""
import os
import httpx

API_URL = "https://api.anthropic.com/v1/messages"
_state = {"ok": None, "error": None, "calls": 0}

SYSTEM = (
    "You are the trading assistant inside Trade Companion, a crypto/forex analysis app. You will be given "
    "MARKET DATA (already computed by the app's own rule-based analyst - prices, indicators, structure, PnL) "
    "and the user's question. Write a natural, conversational reply in plain English.\n"
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


def cfg():
    return {"key": os.getenv("ANTHROPIC_API_KEY", "").strip(), "model": os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()}


def available():
    return bool(cfg()["key"])


def info():
    c = cfg()
    return {"configured": bool(c["key"]), "model": c["model"] if c["key"] else None, "ok": _state["ok"], "error": _state["error"], "calls": _state["calls"]}


async def rewrite(question, data_text, history=None, max_tokens=500, timeout=20):
    """Returns a natural-language reply, or None (with _state updated) if the LLM isn't configured or the call failed."""
    c = cfg()
    if not c["key"]:
        return None
    msgs = []
    for m in (history or [])[-6:-1]:                 # a little prior context for follow-ups; excludes the current question
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip():
            msgs.append({"role": m["role"], "content": m["content"][:2000]})
    msgs.append({"role": "user", "content": f"MARKET DATA:\n{data_text[:6000]}\n\nQUESTION: {question}"})
    try:
        async with httpx.AsyncClient(timeout=timeout) as h:
            r = await h.post(API_URL, headers={"x-api-key": c["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                             json={"model": c["model"], "max_tokens": max_tokens, "system": SYSTEM, "messages": msgs})
        if r.status_code != 200:
            _state.update(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if not text:
            _state.update(ok=False, error="empty response")
            return None
        _state.update(ok=True, error=None, calls=_state["calls"] + 1)
        return text
    except httpx.TimeoutException:
        _state.update(ok=False, error="timed out")
        return None
    except Exception as e:
        _state.update(ok=False, error=f"{type(e).__name__}: {str(e)[:160]}")
        return None
