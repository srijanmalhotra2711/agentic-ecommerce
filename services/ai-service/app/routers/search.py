"""Endpoints for semantic search and embedding management."""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logger import get_logger
from ..services.embeddings import semantic_search, upsert_product_embedding

router = APIRouter(prefix="/ai", tags=["search"])
log = get_logger(__name__)


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class SemanticSearchResult(BaseModel):
    product_id: int
    name: str
    description: str
    category: str
    similarity: float


@router.post("/semantic-search", response_model=list[SemanticSearchResult])
async def post_semantic_search(req: SemanticSearchRequest) -> list[dict[str, Any]]:
    log.info("semantic_search_request", query=req.query, limit=req.limit)
    try:
        return await semantic_search(req.query, limit=req.limit)
    except Exception as e:
        log.error("semantic_search_failed", error=str(e))
        raise HTTPException(status_code=500, detail="semantic search failed")


class EmbedProductRequest(BaseModel):
    """Manual trigger to (re-)embed a single product. Useful for backfill
    and testing — normally embeddings happen automatically via the Kafka
    consumer for ProductCreated events.
    """
    product_id: int
    name: str
    description: str = ""
    category: str = "general"


@router.post("/embed-product", status_code=202)
async def post_embed_product(req: EmbedProductRequest) -> dict[str, Any]:
    log.info("manual_embed_request", product_id=req.product_id)
    try:
        await upsert_product_embedding(req.product_id, req.name, req.description, req.category)
        return {"status": "embedded", "product_id": req.product_id}
    except Exception as e:
        log.error("embedding_failed", product_id=req.product_id, error=str(e))
        raise HTTPException(status_code=500, detail="embedding failed")
