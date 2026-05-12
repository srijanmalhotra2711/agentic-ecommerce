"""The agent loop: read conversation history → call LLM → if it returned tool
calls, execute them and feed results back → repeat until LLM produces a plain
text response or we hit the max iteration cap.

Conversation history lives in Postgres so sessions survive service restarts."""
import json
from typing import Any

from ..db import get_pool
from ..logger import get_logger
from .ollama import get_ollama_client
from .tool_executor import execute_tool
from .tools import TOOLS

log = get_logger(__name__)

MAX_TOOL_ITERATIONS = 6  # safety cap so the LLM can't loop forever

SYSTEM_PROMPT = """You are a shopping assistant for an e-commerce platform. \
You can search the product catalog, look up products, propose orders, and place \
orders for the user.

CRITICAL RULES (FOLLOW EXACTLY):

1. NEVER invent products that did not appear in a tool result. ONLY recommend \
products that came back from semantic_search_products or get_product in this \
conversation. If the user asks for something and the search returns no matches, \
say so honestly — do not fill in fictitious products.

2. NEVER invent prices, descriptions, or stock levels. Only state values that \
appeared in a tool result. If the search result is missing a price, call \
get_product to get the real price before mentioning one.

3. NEVER call confirm_order without the user EXPLICITLY confirming (e.g. \
"yes", "confirm", "place it", "go ahead"). The flow is always: propose_order \
→ show summary in your reply → wait for confirmation message → confirm_order.

4. When proposing an order, ALWAYS write a clear summary in your reply listing \
each item, its real price from the tool result, the quantity, and the total. \
Then ask "Should I place this order?".

5. If a tool returns an error, explain the issue to the user briefly in plain \
language. Don't expose raw error strings.

6. Keep replies concise — 2-4 sentences unless detail is needed."""


# ============================================================
# Conversation persistence
# ============================================================

async def _load_history(session_id: str, max_turns: int = 20) -> list[dict[str, Any]]:
    """Load the conversation history in OpenAI/Ollama message format."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content, tool_calls, tool_call_id, tool_name
            FROM conversations
            WHERE session_id = $1
            ORDER BY created_at ASC
            """,
            session_id,
        )

    messages: list[dict[str, Any]] = []
    for r in rows:
        if r["role"] == "user":
            messages.append({"role": "user", "content": r["content"]})
        elif r["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": r["content"] or ""}
            if r["tool_calls"]:
                tc = r["tool_calls"]
                if isinstance(tc, str):
                    tc = json.loads(tc)
                msg["tool_calls"] = tc
            messages.append(msg)
        elif r["role"] == "tool":
            messages.append(
                {
                    "role": "tool",
                    "content": r["content"] or "",
                    "tool_call_id": r["tool_call_id"] or "",
                }
            )

    return messages[-max_turns:]


async def _persist_message(
    session_id: str,
    user_id: int | None,
    role: str,
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations
              (session_id, user_id, role, content, tool_calls, tool_call_id, tool_name)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
            """,
            session_id,
            user_id,
            role,
            content,
            json.dumps(tool_calls) if tool_calls else None,
            tool_call_id,
            tool_name,
        )


# ============================================================
# Agent loop
# ============================================================

async def run_agent_turn(
    session_id: str,
    user_id: int,
    user_message: str,
) -> dict[str, Any]:
    """Process one user message. Returns {reply, tool_calls_executed}."""
    await _persist_message(session_id, user_id, "user", content=user_message)

    history = await _load_history(session_id)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)

    ollama = get_ollama_client()
    tool_calls_executed: list[dict[str, Any]] = []

    for iteration in range(MAX_TOOL_ITERATIONS):
        log.debug("agent_iteration", iteration=iteration, session_id=session_id)
        resp = await ollama.chat(messages=messages, tools=TOOLS)

        assistant_msg = resp.get("message", {})
        content = assistant_msg.get("content", "") or ""
        tool_calls = assistant_msg.get("tool_calls") or []

        if not tool_calls:
            await _persist_message(session_id, user_id, "assistant", content=content)
            return {
                "reply": content,
                "tool_calls_executed": tool_calls_executed,
                "iterations": iteration + 1,
            }

        normalized_tool_calls: list[dict[str, Any]] = []
        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tc_id = tc.get("id") or f"call_{iteration}_{idx}"
            normalized_tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            )

        await _persist_message(
            session_id,
            user_id,
            "assistant",
            content=content,
            tool_calls=normalized_tool_calls,
        )
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": normalized_tool_calls,
            }
        )

        for tc in normalized_tool_calls:
            fn = tc["function"]
            name = fn["name"]
            args = fn["arguments"]
            log.info("executing_tool", tool=name, args=args, session_id=session_id)
            result = await execute_tool(
                name=name,
                arguments=args,
                session_id=session_id,
                user_id=user_id,
            )
            tool_calls_executed.append({"name": name, "arguments": args, "result": result})

            result_str = json.dumps(result)
            await _persist_message(
                session_id,
                user_id,
                "tool",
                content=result_str,
                tool_call_id=tc["id"],
                tool_name=name,
            )
            messages.append(
                {
                    "role": "tool",
                    "content": result_str,
                    "tool_call_id": tc["id"],
                }
            )

    fallback = (
        "I tried multiple steps but couldn't complete that request in one go. "
        "Could you rephrase or break it into smaller asks?"
    )
    await _persist_message(session_id, user_id, "assistant", content=fallback)
    return {
        "reply": fallback,
        "tool_calls_executed": tool_calls_executed,
        "iterations": MAX_TOOL_ITERATIONS,
        "warning": "max_iterations_reached",
    }