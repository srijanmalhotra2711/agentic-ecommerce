"""POST /ai/chat — the agentic shopping assistant endpoint."""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logger import get_logger
from ..services.agent import run_agent_turn

router = APIRouter(prefix="/ai", tags=["chat"])
log = get_logger(__name__)


class ChatRequest(BaseModel):
    user_id: int = Field(..., description="ID of the authenticated user")
    session_id: str = Field(..., min_length=1, max_length=128,
                            description="Stable identifier for this conversation")
    message: str = Field(..., min_length=1, max_length=2000)


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    tool_calls_executed: list[ToolCallRecord]
    iterations: int
    warning: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest) -> dict[str, Any]:
    log.info(
        "chat_request",
        session_id=req.session_id,
        user_id=req.user_id,
        message_len=len(req.message),
    )
    try:
        return await run_agent_turn(
            session_id=req.session_id,
            user_id=req.user_id,
            user_message=req.message,
        )
    except Exception as e:
        log.error("chat_failed", session_id=req.session_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"agent error: {e}")
