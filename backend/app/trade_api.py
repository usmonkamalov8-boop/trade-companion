"""Companion API routes under /api/trade/*: a thin, authenticated proxy to the execution service (tcexec, 127.0.0.1:8100).

The app never talks to tcexec directly (it only has the companion's own API token); this router forwards using the internal
EXEC_TOKEN. Kept in its own file so main.py's own import list does not need to grow."""
import os

import httpx
from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/api/trade")
EXEC_URL = os.getenv("EXEC_URL", "http://127.0.0.1:8100")


def _tok():
    tok = os.getenv("EXEC_TOKEN", "")
    if not tok:
        raise HTTPException(503, "the execution service is not configured yet (run the step 19 installer)")
    return tok


async def _fwd(method, path, json=None, params=None):
    try:
        async with httpx.AsyncClient(timeout=45) as h:
            r = await h.request(method, f"{EXEC_URL}{path}", json=json, params=params, headers={"X-Exec-Token": _tok()})
    except httpx.TransportError:
        raise HTTPException(503, "the execution service (tcexec) is not reachable")
    if r.status_code >= 400:
        try:
            raise HTTPException(r.status_code, r.json().get("detail", r.text))
        except ValueError:
            raise HTTPException(r.status_code, r.text[:300])
    return r.json()


@router.get("/status")
async def status():
    return await _fwd("GET", "/status")


@router.get("/config")
async def get_config():
    return await _fwd("GET", "/config")


@router.post("/config")
async def set_config(patch: dict = Body(...)):
    return await _fwd("POST", "/config", json=patch)


@router.get("/env/check")
async def env_check(mode: str = "live", allow_any_ip: bool = False):
    return await _fwd("GET", "/env/check", params={"mode": mode, "allow_any_ip": allow_any_ip})


@router.post("/env")
async def env_switch(b: dict = Body(...)):
    return await _fwd("POST", "/env", json=b)


@router.get("/arm/check")
async def arm_check(allow_any_ip: bool = False):
    return await _fwd("GET", "/arm/check", params={"allow_any_ip": allow_any_ip})


@router.post("/arm")
async def arm(body: dict = Body(...)):
    return await _fwd("POST", "/arm", json=body)


@router.post("/disarm")
async def disarm():
    return await _fwd("POST", "/disarm")


@router.post("/order/preview")
async def order_preview(t: dict = Body(...)):
    return await _fwd("POST", "/order/preview", json=t)


@router.post("/order")
async def order(t: dict = Body(...)):
    return await _fwd("POST", "/order", json=t)


@router.post("/position/close")
async def position_close(b: dict = Body(...)):
    return await _fwd("POST", "/position/close", json=b)


@router.post("/position/stop")
async def position_stop(b: dict = Body(...)):
    return await _fwd("POST", "/position/stop", json=b)


@router.post("/orders/cancel")
async def orders_cancel(b: dict = Body(...)):
    return await _fwd("POST", "/orders/cancel", json=b)


@router.post("/leverage")
async def leverage(b: dict = Body(...)):
    return await _fwd("POST", "/leverage", json=b)


@router.get("/proposals")
async def proposals(status: str = "pending"):
    return await _fwd("GET", "/proposals", params={"status": status})


@router.post("/proposals/{pid}/approve")
async def proposal_approve(pid: str):
    return await _fwd("POST", f"/proposals/{pid}/approve")


@router.post("/proposals/{pid}/reject")
async def proposal_reject(pid: str):
    return await _fwd("POST", f"/proposals/{pid}/reject")


@router.post("/kill")
async def kill(b: dict = Body(...)):
    return await _fwd("POST", "/kill", json=b)


@router.post("/resume")
async def resume(b: dict = Body(default={})):
    return await _fwd("POST", "/resume", json=b)


@router.get("/wallet")
async def wallet():
    return await _fwd("GET", "/wallet")


@router.get("/stats")
async def stats():
    return await _fwd("GET", "/stats")


@router.get("/trades")
async def trades(limit: int = 50):
    return await _fwd("GET", "/trades", params={"limit": limit})


@router.get("/events")
async def events(limit: int = 60):
    return await _fwd("GET", "/events", params={"limit": limit})


@router.get("/symbols")
async def symbols(kind: str = "fut", q: str = ""):
    return await _fwd("GET", "/symbols", params={"kind": kind, "q": q})


@router.get("/price/{symbol}")
async def price(symbol: str, kind: str = "fut"):
    return await _fwd("GET", f"/price/{symbol}", params={"kind": kind})


@router.post("/grid/plan")
async def grid_plan(cfg: dict = Body(...)):
    return await _fwd("POST", "/grid/plan", json=cfg)


@router.post("/grid/start")
async def grid_start(cfg: dict = Body(...)):
    return await _fwd("POST", "/grid/start", json=cfg)


@router.post("/grid/{gid}/stop")
async def grid_stop(gid: str, b: dict = Body(default={})):
    return await _fwd("POST", f"/grid/{gid}/stop", json=b)


@router.get("/grids")
async def grids():
    return await _fwd("GET", "/grids")


@router.get("/grid/{gid}")
async def grid_detail(gid: str):
    return await _fwd("GET", f"/grid/{gid}")
