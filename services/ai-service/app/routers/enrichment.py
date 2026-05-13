"""HTTP endpoints for product enrichments.

GET  /ai/products/{id}/enrichment  — fetch current enrichment for a product
POST /ai/products/{id}/enrich      — manually trigger enrichment (for backfill / testing)
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..logger import get_logger
from ..services.enrichment import enrich_product, get_enrichment

router = APIRouter(prefix="/ai", tags=["enrichment"])
log = get_logger(__name__)


class EnrichmentResponse(BaseModel):
    product_id: int
    seo_description: Optional[str]
    attributes: Optional[dict[str, Any]]
    status: str
    llm_model: Optional[str]
    last_error: Optional[str]
    updated_at: Optional[str]


@router.get("/products/{product_id}/enrichment", response_model=EnrichmentResponse)
async def get_product_enrichment(product_id: int) -> dict[str, Any]:
    enrichment = await get_enrichment(product_id)
    if enrichment is None:
        raise HTTPException(
            status_code=404,
            detail=f"no enrichment for product {product_id}",
        )
    return enrichment


class ManualEnrichRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "general"


@router.post("/products/{product_id}/enrich", status_code=202)
async def trigger_enrichment(product_id: int, req: ManualEnrichRequest) -> dict[str, Any]:
    """Manually trigger enrichment for a product. Useful for backfill and
    testing — normally enrichment happens automatically via Kafka consumer.

    Returns synchronously after enrichment completes (~10-30s depending on
    the model). For batch backfill, a background task would be better, but
    that's out of scope for the portfolio demo.
    """
    log.info("manual_enrichment_request", product_id=product_id)
    result = await enrich_product(
        product_id=product_id,
        name=req.name,
        description=req.description,
        category=req.category,
        event_id="manual",
    )
    return result
