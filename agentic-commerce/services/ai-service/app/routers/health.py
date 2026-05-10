"""Liveness and readiness endpoints."""
import asyncio

from fastapi import APIRouter, Response

from ..db import ping as db_ping
from ..services.ollama import get_ollama_client

router = APIRouter()
_shutting_down = False


def mark_shutting_down() -> None:
    global _shutting_down
    _shutting_down = True


@router.get("/healthz")
async def healthz(response: Response) -> dict:
    if _shutting_down:
        response.status_code = 503
        return {"status": "shutting_down"}
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    if _shutting_down:
        response.status_code = 503
        return {"status": "shutting_down"}

    checks = {}
    all_ok = True

    # DB
    try:
        await asyncio.wait_for(db_ping(), timeout=2.0)
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "fail", "error": str(e)}
        all_ok = False

    # Ollama
    try:
        ok = await asyncio.wait_for(get_ollama_client().health(), timeout=3.0)
        checks["ollama"] = {"status": "ok" if ok else "fail"}
        if not ok:
            all_ok = False
    except Exception as e:
        checks["ollama"] = {"status": "fail", "error": str(e)}
        all_ok = False

    if not all_ok:
        response.status_code = 503
    return {"status": "ready" if all_ok else "not_ready", "checks": checks}
