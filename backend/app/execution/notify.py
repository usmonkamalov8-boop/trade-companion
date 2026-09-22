"""Telegram delivery for the trading engine: alerts, trade confirmations with buttons, and a few risk-reducing commands.

Only the allowed user (TG_ALLOWED_USER_ID, or the chat id for a private chat) can press buttons or send commands. Nothing a
message can do opens a position by itself: a button only approves one specific, already risk-checked proposal (which is
re-checked at that moment and expires), and the commands are stop / flatten (with a confirm button) / status."""
import asyncio, html, json, time

import httpx

from . import store


class Notifier:
    def __init__(self, token, chat_id, allowed_user_id=None, api="https://api.telegram.org"):
        self.token, self.chat = token, str(chat_id or "")
        self.allowed = str(allowed_user_id or chat_id or "")
        self.api = api.rstrip("/")
        self.offset = 0
        self.ok = None
        self.last_error = None
        self._lock = asyncio.Lock()
        self._http = None

    @property
    def configured(self):
        return bool(self.token and self.chat)

    async def _call(self, method, payload, timeout=15):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=40)
        r = await self._http.post(f"{self.api}/bot{self.token}/{method}", json=payload, timeout=timeout)
        try:
            d = r.json()
        except Exception:
            d = {"ok": False, "description": r.text[:100]}
        if not d.get("ok"):
            raise RuntimeError(f"telegram {method}: {d.get('description') or r.status_code}")
        return d["result"]

    async def send(self, text, buttons=None, silent=False, retries=1):
        """Send a message; returns its id (or None). Never raises: a failing alert must not stop trading logic."""
        store.event("info", "alert", text)
        if not self.configured:
            return None
        payload = {"chat_id": self.chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True, "disable_notification": silent}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        for i in range(retries + 1):
            try:
                async with self._lock:
                    r = await self._call("sendMessage", payload)
                self.ok, self.last_error = True, None
                return r.get("message_id")
            except Exception as e:
                self.ok, self.last_error = False, str(e)[:160]
                await asyncio.sleep(1 + i)
        return None

    async def edit(self, msg_id, text, buttons=None):
        if not (self.configured and msg_id):
            return
        payload = {"chat_id": self.chat, "message_id": msg_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True,
                   "reply_markup": {"inline_keyboard": buttons or []}}
        try:
            await self._call("editMessageText", payload)
        except Exception as e:
            self.last_error = str(e)[:160]

    async def answer(self, cb_id, text=""):
        try:
            await self._call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:190]})
        except Exception:
            pass

    async def poll(self, handler, stop):
        """Long-poll Telegram. handler(kind, data) is awaited for every button press or command from the allowed user."""
        while not stop.is_set():
            if not self.configured:
                await asyncio.sleep(30)
                continue
            try:
                ups = await self._call("getUpdates", {"offset": self.offset, "timeout": 25, "allowed_updates": ["callback_query", "message"]}, timeout=40)
                self.ok = True
                for u in ups:
                    self.offset = u["update_id"] + 1
                    await self._dispatch(u, handler)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.ok, self.last_error = False, str(e)[:160]
                await asyncio.sleep(5)

    async def _dispatch(self, u, handler):
        cb = u.get("callback_query")
        if cb:
            frm = str((cb.get("from") or {}).get("id", ""))
            chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
            if frm != self.allowed or chat != self.chat:
                await self.answer(cb["id"], "Not allowed")
                store.event("warning", "security", f"Telegram button from an unknown user/chat ({frm}/{chat}) ignored")
                return
            await handler("callback", {"data": cb.get("data", ""), "cb_id": cb["id"], "msg_id": (cb.get("message") or {}).get("message_id")})
            return
        m = u.get("message")
        if m and (m.get("text") or "").startswith("/"):
            frm = str((m.get("from") or {}).get("id", ""))
            if frm != self.allowed or str((m.get("chat") or {}).get("id", "")) != self.chat:
                return
            await handler("command", {"text": m["text"].strip().split("@")[0].lower(), "msg_id": m.get("message_id")})


def esc(x):
    return html.escape(str(x))


def kb(*rows):
    return [[{"text": t, "callback_data": d} for t, d in row] for row in rows]


class NullNotifier:
    """Collects messages (tests, and when Telegram is not configured)."""
    configured = False
    ok = None
    last_error = None

    def __init__(self):
        self.sent, self.edits, self.buttons = [], [], []
        self._n = 0

    async def send(self, text, buttons=None, silent=False, retries=1):
        store.event("info", "alert", text)
        self._n += 1
        self.sent.append(text)
        self.buttons.append(buttons)
        return self._n

    async def edit(self, msg_id, text, buttons=None):
        self.edits.append((msg_id, text))

    async def answer(self, cb_id, text=""):
        pass

    async def poll(self, handler, stop):
        await stop.wait()
