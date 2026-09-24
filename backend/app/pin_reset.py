"""Email-based PIN reset for the mobile app's local PIN lock (see flutter_app/lib/pin_service.dart). A random
6-digit code is emailed to a fixed recovery address and must be entered in the app within 10 minutes.

Needs these in backend/.env - until they're all set, /request fails with a clear "not configured" error
instead of silently doing nothing:
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587                    (optional - 587/STARTTLS is the default)
  SMTP_USER=you@gmail.com
  SMTP_PASSWORD=...                (an app password, not your normal login password, for most providers)
  SMTP_FROM=you@gmail.com          (optional - defaults to SMTP_USER)
  PIN_RECOVERY_EMAIL=you@gmail.com (where the reset code is sent - can be the same address as SMTP_USER)

Both endpoints require the same Bearer API token as the rest of the app (wired in main.py exactly like
trade_api's router), so only someone who already has your API token can even trigger a reset email.
"""
import os
import random
import smtplib
import time
from email.mime.text import MIMEText
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/auth/pin-reset")

_state = {"code": None, "expires": 0.0, "attempts": 0}
MAX_ATTEMPTS = 5
CODE_TTL = 600  # 10 minutes


def _cfg():
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_addr": os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        "to_addr": os.getenv("PIN_RECOVERY_EMAIL", "").strip(),
    }


@router.post("/request")
async def request_code():
    c = _cfg()
    label = {"host": "SMTP_HOST", "user": "SMTP_USER", "password": "SMTP_PASSWORD", "to_addr": "PIN_RECOVERY_EMAIL"}
    missing = [label[k] for k in ("host", "user", "password", "to_addr") if not c[k]]
    if missing:
        raise HTTPException(503, f"PIN reset isn't configured yet - missing in .env: {', '.join(missing)}")

    code = f"{random.randint(0, 999999):06d}"
    _state.update(code=code, expires=time.time() + CODE_TTL, attempts=0)

    msg = MIMEText(f"Your Trade Companion PIN reset code is {code}. It expires in 10 minutes.\n\n"
                    "If you didn't request this, you can ignore this email.")
    msg["Subject"] = "Trade Companion: PIN reset code"
    msg["From"] = c["from_addr"]
    msg["To"] = c["to_addr"]
    try:
        with smtplib.SMTP(c["host"], c["port"], timeout=15) as s:
            s.starttls()
            s.login(c["user"], c["password"])
            s.send_message(msg)
    except Exception as e:
        _state.update(code=None, attempts=0)  # don't leave a valid code stuck around if the email never sent
        raise HTTPException(502, f"Could not send the email: {type(e).__name__}: {str(e)[:150]}")
    return {"ok": True}


class VerifyIn(BaseModel):
    code: str


@router.post("/verify")
async def verify_code(b: VerifyIn):
    if not _state["code"]:
        raise HTTPException(400, "No reset code was requested - tap \"Send code\" first")
    if time.time() > _state["expires"]:
        _state.update(code=None, attempts=0)
        raise HTTPException(400, "That code has expired - request a new one")
    if _state["attempts"] >= MAX_ATTEMPTS:
        _state.update(code=None, attempts=0)
        raise HTTPException(429, "Too many wrong attempts - request a new code")
    if b.code.strip() != _state["code"]:
        _state["attempts"] += 1
        left = MAX_ATTEMPTS - _state["attempts"]
        raise HTTPException(400, f"Incorrect code ({left} attempt{'s' if left != 1 else ''} left)")
    _state.update(code=None, attempts=0)  # one-time use
    return {"ok": True}
