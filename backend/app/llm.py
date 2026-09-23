import os
import asyncio
import random
import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_state = {"ok": None, "error": None, "calls": 0, "overloaded": False}

RETRYABLE_STATUS = {503, 429}

def cfg():
    return {"key": os.getenv("GEMINI_API_KEY", "").strip(), "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()}

def available():
    return bool(cfg()["key"])

def info():
    c = cfg()
    return {"configured": bool(c["key"]), "model": c["model"] if c["key"] else None,
             "ok": _state["ok"], "error": _state["error"], "calls": _state["calls"],
             "overloaded": _state["overloaded"]}

def _history_contents(history):
    contents = []
    for m in (history or [])[-6:-1]:
        role = m.get("role")
        if role in ("user", "assistant") and (m.get("content") or "").strip():
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": m["content"][:2000]}]})
    return contents

async def _call(system, contents, max_tokens, timeout, max_retries=3, base_delay=1.5):
    c = cfg()
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as h:
                r = await h.post(f"{API_BASE}/{c['model']}:generateContent",
                                 headers={"x-goog-api-key": c["key"], "content-type": "application/json"},
                                 json={"contents": contents, "systemInstruction": {"parts": [{"text": system}]},
                                       "generationConfig": {"maxOutputTokens": max_tokens}})
            if r.status_code != 200:
                if r.status_code in RETRYABLE_STATUS and attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    _state.update(ok=False, error=f"HTTP {r.status_code}, retrying ({attempt+1}/{max_retries})", overloaded=True)
                    await asyncio.sleep(delay)
                    continue
                _state.update(ok=False, error=f"HTTP {r.status_code}: {r.text[:200]}", overloaded=r.status_code in RETRYABLE_STATUS)
                return None
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                reason = data.get("promptFeedback", {}).get("blockReason")
                _state.update(ok=False, error=f"no candidates{f' (blocked: {reason})' if reason else ''}", overloaded=False)
                return None
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            if not text:
                _state.update(ok=False, error=f"empty response (finishReason: {candidates[0].get('finishReason')})", overloaded=False)
                return None
            _state.update(ok=True, error=None, calls=_state["calls"] + 1, overloaded=False)
            return text
        except httpx.TimeoutException:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue
            _state.update(ok=False, error="timed out", overloaded=False)
            return None
        except Exception as e:
            _state.update(ok=False, error=f"{type(e).__name__}: {str(e)[:160]}", overloaded=False)
            return None
    return None

async def rewrite(question, data_text, history=None, max_tokens=500, timeout=20):
    if not cfg()["key"]:
        return None
    contents = _history_contents(history)
    contents.append({"role": "user", "parts": [{"text": f"MARKET DATA:\n{data_text[:6000]}\n\nQUESTION: {question}"}]})
    return await _call("You are a professional financial trading assistant.", contents, max_tokens, timeout)

async def chat(question, history=None, max_tokens=400, timeout=20):
    if not cfg()["key"]:
        return None
    contents = _history_contents(history)
    contents.append({"role": "user", "parts": [{"text": question}]})
    return await _call("You are a helpful trading companion assistant.", contents, max_tokens, timeout)
