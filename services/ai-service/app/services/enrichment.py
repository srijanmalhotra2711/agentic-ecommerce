"""Product enrichment pipeline. Given raw product data, runs LLM calls to:
  1. Generate a marketing-quality SEO description
  2. Extract structured attributes (color, dimensions, features) as JSON
  3. Generate an embedding (handled separately via embeddings.semantic upsert)

Each step has its own LLM call so failures are isolated — a malformed
attributes-extraction response doesn't lose the SEO description we just paid
to generate. The orchestrator records partial success in product_enrichments
and the consumer can retry just the failed step on next event arrival.
"""
import json
from typing import Any, Optional

from ..config import settings
from ..db import get_pool
from ..logger import get_logger
from .ollama import get_ollama_client

log = get_logger(__name__)


# ============================================================
# Prompts
# ============================================================

SEO_SYSTEM = (
    "You are a copywriter for an e-commerce catalog. Given product info, "
    "produce a polished, customer-facing description in 2-3 sentences. "
    "Focus on benefits, not specs. NEVER invent specifications that aren't "
    "in the input. Output ONLY the description text — no preamble, no quotes, "
    "no extra commentary."
)

ATTRS_SYSTEM = (
    "You are a product data extractor. Given product info, extract structured "
    "attributes as a JSON object. ONLY include attributes you can confidently "
    "infer from the input. Common attributes: color, material, wireless (bool), "
    "size, weight, battery_hours (number), features (list of strings).\n\n"
    "CRITICAL RULES:\n"
    "- Output ONLY valid JSON. No preamble, no markdown fences, no commentary.\n"
    "- Use the literal value `null` if you can't determine a field, OR omit it.\n"
    "- NEVER invent values. If 'battery_hours' isn't mentioned, omit it.\n"
    "- Boolean fields use true/false, not strings.\n"
    "- Empty result `{}` is acceptable if nothing is extractable."
)


def _product_context(name: str, description: str, category: str) -> str:
    return f"Product name: {name}\nCategory: {category}\nDescription: {description}"


# ============================================================
# Individual enrichment steps
# ============================================================

async def generate_seo_description(name: str, description: str, category: str) -> str:
    """Generate a marketing-quality description. Returns plain text."""
    ollama = get_ollama_client()
    resp = await ollama.chat(
        messages=[
            {"role": "system", "content": SEO_SYSTEM},
            {"role": "user", "content": _product_context(name, description, category)},
        ]
    )
    text = (resp.get("message", {}).get("content") or "").strip()
    # Defensive: strip common LLM preamble patterns
    for prefix in ("Description:", "SEO description:", '"', "'"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if text.endswith(('"', "'")):
        text = text[:-1].strip()
    if not text:
        raise ValueError("LLM returned empty SEO description")
    return text


async def extract_attributes(name: str, description: str, category: str) -> dict[str, Any]:
    """Extract structured attributes. Returns a dict (possibly empty)."""
    ollama = get_ollama_client()
    resp = await ollama.chat(
        messages=[
            {"role": "system", "content": ATTRS_SYSTEM},
            {"role": "user", "content": _product_context(name, description, category)},
        ]
    )
    text = (resp.get("message", {}).get("content") or "").strip()

    # LLMs sometimes wrap JSON in markdown fences despite instructions
    if text.startswith("```"):
        # Strip ```json ... ``` or ``` ... ```
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        attrs = json.loads(text)
    except json.JSONDecodeError as e:
        # Last-ditch: try to find a JSON object in the text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                attrs = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                raise ValueError(f"LLM returned invalid JSON: {text[:200]}") from e
        else:
            raise ValueError(f"LLM returned no JSON object: {text[:200]}") from e

    if not isinstance(attrs, dict):
        raise ValueError(f"LLM returned non-object JSON: {type(attrs).__name__}")

    # Drop null values to keep the JSONB compact
    return {k: v for k, v in attrs.items() if v is not None}


# ============================================================
# Persistence
# ============================================================

async def _mark_pending(product_id: int, event_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO product_enrichments
              (product_id, status, llm_model, source_event_id)
            VALUES ($1, 'pending', $2, $3)
            ON CONFLICT (product_id) DO UPDATE
            SET status = 'pending',
                source_event_id = EXCLUDED.source_event_id,
                last_error = NULL,
                updated_at = NOW()
            """,
            product_id, settings.llm_model, event_id,
        )


async def _save_success(
    product_id: int,
    seo_description: Optional[str],
    attributes: Optional[dict[str, Any]],
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE product_enrichments
            SET seo_description = COALESCE($2, seo_description),
                attributes = COALESCE($3::jsonb, attributes),
                status = 'success',
                last_error = NULL,
                updated_at = NOW()
            WHERE product_id = $1
            """,
            product_id,
            seo_description,
            json.dumps(attributes) if attributes is not None else None,
        )


async def _save_failure(product_id: int, error: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE product_enrichments
            SET status = 'failed',
                last_error = $2,
                updated_at = NOW()
            WHERE product_id = $1
            """,
            product_id, error,
        )


# ============================================================
# Orchestrator
# ============================================================

async def enrich_product(
    product_id: int,
    name: str,
    description: str,
    category: str,
    event_id: str = "",
) -> dict[str, Any]:
    """Run the full enrichment pipeline for one product.

    Steps are independent — failure of one doesn't prevent the others from
    completing. We record partial success in product_enrichments.

    Returns a dict summarizing what got generated.
    """
    log.info("enrichment_started", product_id=product_id, event_id=event_id)
    await _mark_pending(product_id, event_id)

    result: dict[str, Any] = {"product_id": product_id, "errors": []}

    # Step 1: SEO description
    try:
        seo = await generate_seo_description(name, description, category)
        result["seo_description"] = seo
        log.info("seo_generated", product_id=product_id, length=len(seo))
    except Exception as e:
        result["errors"].append(f"seo_description: {e}")
        result["seo_description"] = None
        log.warning("seo_failed", product_id=product_id, error=str(e))

    # Step 2: attributes
    try:
        attrs = await extract_attributes(name, description, category)
        result["attributes"] = attrs
        log.info("attributes_extracted", product_id=product_id, attr_count=len(attrs))
    except Exception as e:
        result["errors"].append(f"attributes: {e}")
        result["attributes"] = None
        log.warning("attributes_failed", product_id=product_id, error=str(e))

    # Step 3: embedding is already handled by the existing consumer in
    # consumer.py via upsert_product_embedding. We don't re-do it here to
    # avoid double work — see consumer.py for the full event-handling flow.

    # Persist whatever succeeded
    if result["seo_description"] or result["attributes"] is not None:
        await _save_success(product_id, result["seo_description"], result["attributes"])
        result["status"] = "success" if not result["errors"] else "partial"
    else:
        await _save_failure(product_id, "; ".join(result["errors"]) or "no enrichments produced")
        result["status"] = "failed"

    log.info("enrichment_complete", product_id=product_id, status=result["status"])
    return result


# ============================================================
# Read API — used by the new HTTP endpoint
# ============================================================

async def get_enrichment(product_id: int) -> Optional[dict[str, Any]]:
    """Fetch the latest enrichment for a product."""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT product_id, seo_description, attributes, status,
                   llm_model, last_error, updated_at
            FROM product_enrichments
            WHERE product_id = $1
            """,
            product_id,
        )
    if row is None:
        return None
    return {
        "product_id": int(row["product_id"]),
        "seo_description": row["seo_description"],
        "attributes": row["attributes"] if isinstance(row["attributes"], (dict, list))
                      else (json.loads(row["attributes"]) if row["attributes"] else None),
        "status": row["status"],
        "llm_model": row["llm_model"],
        "last_error": row["last_error"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
