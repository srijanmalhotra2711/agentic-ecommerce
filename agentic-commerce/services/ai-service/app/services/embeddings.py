"""Business logic for product embeddings and semantic search."""
from typing import Any

from ..db import get_pool
from ..logger import get_logger
from .ollama import get_ollama_client

log = get_logger(__name__)


def _build_product_text(name: str, description: str, category: str) -> str:
    """Concatenate product fields into one string for embedding.
    Embedding the whole context (not just name) gives much better semantic
    search results because synonyms and related terms in the description
    contribute to the vector.
    """
    return f"{name}. Category: {category}. {description}"


async def upsert_product_embedding(
    product_id: int,
    name: str,
    description: str,
    category: str,
) -> None:
    """Generate and store an embedding for a product. Idempotent."""
    text = _build_product_text(name, description, category)
    embedding = await get_ollama_client().embed(text)

    # asyncpg expects vectors as a string in pgvector's text format
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO product_embeddings (product_id, name, description, category, embedding)
            VALUES ($1, $2, $3, $4, $5::vector)
            ON CONFLICT (product_id) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
            """,
            product_id, name, description, category, vec_literal,
        )

    log.info("embedding_upserted", product_id=product_id, dim=len(embedding))


async def semantic_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find products semantically similar to a natural-language query."""
    embedding = await get_ollama_client().embed(query)
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT product_id, name, description, category,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM product_embeddings
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal, limit,
        )
    return [dict(r) for r in rows]
