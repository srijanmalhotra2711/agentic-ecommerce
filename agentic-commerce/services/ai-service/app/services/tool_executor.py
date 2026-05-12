"""Executes tool calls produced by the LLM. Each tool maps to a real backend
operation (REST call, DB query, etc). The executor returns a JSON-serializable
dict that gets fed back to the LLM as the tool result."""
import asyncio
import json
import time
from typing import Any

import httpx

from ..config import settings
from ..db import get_pool
from ..logger import get_correlation_id, get_logger
from .embeddings import semantic_search

log = get_logger(__name__)


class ToolExecutionError(Exception):
    """Recoverable error during tool execution. Returned to the LLM so it
    can decide what to do next (retry, ask user, etc)."""


def _correlation_headers() -> dict[str, str]:
    cid = get_correlation_id()
    return {"x-correlation-id": cid} if cid else {}


def _coerce_int(value: Any, default: int) -> int:
    """LLMs sometimes pass numeric args as strings — coerce defensively."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _fetch_product_details(product_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Batch-fetch product details from product-service in parallel.
    Returns a dict keyed by product_id. Missing products are absent."""
    if not product_ids:
        return {}

    async def fetch_one(client: httpx.AsyncClient, pid: int) -> tuple[int, dict[str, Any] | None]:
        try:
            resp = await client.get(
                f"{settings.product_service_url}/products/{pid}",
                headers=_correlation_headers(),
            )
            if resp.status_code == 200:
                return pid, resp.json()
            return pid, None
        except Exception as e:
            log.warning("product_fetch_failed", product_id=pid, error=str(e))
            return pid, None

    async with httpx.AsyncClient(timeout=3.0) as client:
        results = await asyncio.gather(*[fetch_one(client, pid) for pid in product_ids])

    return {pid: data for pid, data in results if data is not None}


# ============================================================
# Tool implementations
# ============================================================

async def tool_semantic_search_products(query: str, limit: int = 5) -> dict[str, Any]:
    limit = _coerce_int(limit, 5)
    limit = max(1, min(10, limit))
    results = await semantic_search(query, limit=limit)

    # Enrich with current price and stock so the LLM has real data to
    # reason about, not just names. Without this the LLM hallucinates prices.
    product_ids = [r["product_id"] for r in results]
    details = await _fetch_product_details(product_ids)

    enriched_results = []
    for r in results:
        pid = r["product_id"]
        detail = details.get(pid, {})
        enriched_results.append({
            "product_id": pid,
            "name": r["name"],
            "description": r["description"],
            "category": r["category"],
            "price": float(detail["price"]) if detail else None,
            "stock": int(detail["stock"]) if detail else None,
            "similarity": round(r["similarity"], 3),
        })

    return {
        "query": query,
        "results": enriched_results,
    }


async def tool_get_product(product_id: int) -> dict[str, Any]:
    product_id = _coerce_int(product_id, 0)
    if product_id <= 0:
        raise ToolExecutionError("invalid product_id")

    url = f"{settings.product_service_url}/products/{product_id}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers=_correlation_headers())
        if resp.status_code == 404:
            raise ToolExecutionError(f"Product {product_id} not found")
        resp.raise_for_status()
        product = resp.json()
    return {
        "product_id": int(product["id"]),
        "name": product["name"],
        "description": product["description"],
        "price": float(product["price"]),
        "stock": int(product["stock"]),
        "category": product["category"],
        "available": int(product["stock"]) > 0,
    }


async def tool_propose_order(
    session_id: str,
    user_id: int,
    items: list[dict[str, int]],
) -> dict[str, Any]:
    """Stage an order for user confirmation. Stores in `pending_orders`."""
    # LLM sometimes serializes the whole list as a JSON string. Defend.
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            raise ToolExecutionError("items must be a list of {product_id, quantity}")
    if not isinstance(items, list):
        raise ToolExecutionError("items must be a list of {product_id, quantity}")
    if not items:
        raise ToolExecutionError("items list cannot be empty")

    # Defend against bare integers: [1, 2] → [{product_id: 1, quantity: 1}, ...]
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, int):
            normalized_items.append({"product_id": item, "quantity": 1})
        elif isinstance(item, dict):
            normalized_items.append(item)
        else:
            raise ToolExecutionError(f"invalid item in list: {item}")
    items = normalized_items

    enriched: list[dict[str, Any]] = []
    total = 0.0

    async with httpx.AsyncClient(timeout=5.0) as client:
        for item in items:
            pid = _coerce_int(item.get("product_id"), 0)
            qty = _coerce_int(item.get("quantity"), 0)
            if pid <= 0:
                raise ToolExecutionError("each item needs a valid product_id")
            if qty < 1:
                raise ToolExecutionError(f"quantity for product {pid} must be >= 1")

            url = f"{settings.product_service_url}/products/{pid}"
            resp = await client.get(url, headers=_correlation_headers())
            if resp.status_code == 404:
                raise ToolExecutionError(f"Product {pid} does not exist")
            resp.raise_for_status()
            product = resp.json()

            stock = int(product["stock"])
            if stock < qty:
                raise ToolExecutionError(
                    f"Only {stock} units of '{product['name']}' available, but {qty} requested"
                )
            unit_price = float(product["price"])
            line_total = unit_price * qty
            total += line_total
            enriched.append(
                {
                    "product_id": pid,
                    "name": product["name"],
                    "quantity": qty,
                    "unit_price": unit_price,
                    "line_total": round(line_total, 2),
                }
            )

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pending_orders (session_id, user_id, items, total_amount)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (session_id) DO UPDATE
            SET user_id = EXCLUDED.user_id,
                items = EXCLUDED.items,
                total_amount = EXCLUDED.total_amount,
                created_at = NOW(),
                expires_at = NOW() + INTERVAL '15 minutes'
            """,
            session_id,
            user_id,
            json.dumps(enriched),
            round(total, 2),
        )

    log.info("order_proposed", session_id=session_id, total=total, item_count=len(enriched))
    return {
        "status": "awaiting_confirmation",
        "items": enriched,
        "total_amount": round(total, 2),
        "message": "Order proposed. Show this to the user and wait for confirmation before calling confirm_order.",
    }


async def tool_confirm_order(session_id: str) -> dict[str, Any]:
    """Place the order proposed in this session. Calls order-service."""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, items, total_amount, expires_at
            FROM pending_orders
            WHERE session_id = $1
            """,
            session_id,
        )
    if row is None:
        raise ToolExecutionError(
            "No pending order to confirm. Call propose_order first."
        )

    if row["expires_at"].timestamp() < time.time():
        raise ToolExecutionError(
            "The pending order has expired. Please propose it again."
        )

    raw_items = row["items"]
    if isinstance(raw_items, str):
        raw_items = json.loads(raw_items)
    items_payload = [
        {"product_id": int(i["product_id"]), "quantity": int(i["quantity"])}
        for i in raw_items
    ]

    url = f"{settings.order_service_url}/orders"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            json={"user_id": int(row["user_id"]), "items": items_payload},
            headers=_correlation_headers(),
        )
        if resp.status_code >= 400:
            raise ToolExecutionError(
                f"Order service rejected the order: {resp.status_code} {resp.text}"
            )
        order = resp.json()

    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM pending_orders WHERE session_id = $1", session_id)

    log.info("order_confirmed", session_id=session_id, order_id=order.get("order_id"))
    return {
        "status": "placed",
        "order_id": order["order_id"],
        "total_amount": float(order["total_amount"]),
        "order_status": order["status"],
    }


async def tool_get_user_orders(user_id: int, limit: int = 5) -> dict[str, Any]:
    limit = _coerce_int(limit, 5)
    return {
        "message": (
            "Listing orders by user is not yet implemented in order-service. "
            "Tell the user this feature is coming soon."
        ),
        "orders": [],
    }


# ============================================================
# Dispatch
# ============================================================

async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    session_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Route a tool call to its implementation."""
    try:
        if name == "semantic_search_products":
            return await tool_semantic_search_products(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
            )
        if name == "get_product":
            return await tool_get_product(product_id=arguments["product_id"])
        if name == "propose_order":
            return await tool_propose_order(
                session_id=session_id,
                user_id=user_id,
                items=arguments["items"],
            )
        if name == "confirm_order":
            return await tool_confirm_order(session_id=session_id)
        if name == "get_user_orders":
            return await tool_get_user_orders(
                user_id=user_id,
                limit=arguments.get("limit", 5),
            )
        return {"error": f"unknown tool: {name}"}
    except ToolExecutionError as e:
        log.warning("tool_execution_error", tool=name, error=str(e))
        return {"error": str(e)}
    except Exception as e:
        log.error("tool_unexpected_error", tool=name, error=str(e), exc_info=True)
        return {"error": f"internal error executing {name}: {e}"}