import asyncio, secrets, time
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from . import bot, engine, market, config as C

app = FastAPI(title="Trade Companion API")
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
    for k in ("enabled", "risk_pct", "max_positions"):
        v = getattr(b, k)
        if v is not None:
            st["profiles"][b.profile][k] = v
    bot.save(st)
    return st["profiles"]


@api.post("/command/{cmd}")
async def command(cmd: str):
    st = bot.load()
    if cmd in ("halt", "resume"):
        st["halted"] = cmd == "halt"
        bot.save(st)
        return {"ok": True, "halted": st["halted"]}
    if cmd == "closeall":
        st["halted"] = True  # stop new entries first
        bot.save(st)
        try:
            res = await bot.close_all()
        except Exception as e:
            raise HTTPException(502, str(e))
        return {"ok": all(r["ok"] for r in res), "halted": True, "results": res}
    raise HTTPException(404, "unknown command")


# ---------------------------------------------------------------- markets


def _kind(m: str) -> str:
    if m not in ("crypto", "forex"):
        raise HTTPException(400, "market must be crypto or forex")
    return m


@api.get("/scanner")
async def scanner(m: str = Query("crypto", alias="market")):
    return engine.public_rows(await engine.scan(_kind(m)))


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
