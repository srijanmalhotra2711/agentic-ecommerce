"""Kafka consumer that listens for ProductCreated events. For each event:
  1. Generates and stores an embedding in product_embeddings (Phase 1)
  2. Runs the enrichment pipeline (SEO description + attributes) (Phase 3)
  3. Publishes a ProductEnriched event so other services can react

Idempotency: if the same event_id arrives twice (Kafka at-least-once
guarantee), the embedding and enrichment upserts handle it cleanly because
they're keyed on product_id. We also dedupe at the consumer level via
source_event_id tracking.

Failure isolation: if enrichment fails for one product, the consumer logs
and continues to the next message rather than poisoning the partition.
"""
import asyncio
import json
from typing import Any, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from ..config import settings
from ..logger import get_logger, set_correlation_id
from ..services.embeddings import upsert_product_embedding
from ..services.enrichment import enrich_product

log = get_logger(__name__)


class ProductEventConsumer:
    """Consumes ProductCreated, publishes ProductEnriched."""

    def __init__(self) -> None:
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "ProductCreated",
            bootstrap_servers=settings.kafka_brokers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        log.info("kafka_consumer_started", topics=["ProductCreated"])

        # Producer for publishing ProductEnriched events
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)
        await self._producer.start()
        log.info("kafka_producer_started", topics=["ProductEnriched"])

        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        assert self._consumer is not None
        try:
            async for msg in self._consumer:
                if self._stopped:
                    break
                await self._handle_message(msg)
        except asyncio.CancelledError:
            log.info("kafka_consumer_cancelled")

    async def _handle_message(self, msg: Any) -> None:
        # Restore correlation context from message headers
        headers = {k: v.decode() for k, v in (msg.headers or [])}
        set_correlation_id(headers.get("x-correlation-id"))
        event_id = headers.get("event-id", "")

        try:
            payload = json.loads(msg.value.decode())
            product_id = int(payload["product_id"])
            name = payload["name"]
            description = payload.get("description", "")
            category = payload.get("category", "general")

            # Step 1: embedding (Phase 1 behavior, preserved)
            try:
                await upsert_product_embedding(product_id, name, description, category)
            except Exception as e:
                log.error(
                    "embedding_failed",
                    product_id=product_id, event_id=event_id, error=str(e),
                )
                # We continue to enrichment even if embedding failed —
                # enrichment doesn't depend on embedding.

            # Step 2: enrichment (Phase 3 — SEO description + attributes)
            enrichment = await enrich_product(
                product_id=product_id,
                name=name,
                description=description,
                category=category,
                event_id=event_id,
            )

            # Step 3: publish ProductEnriched so other services can react
            if enrichment["status"] in ("success", "partial"):
                await self._publish_enriched(
                    product_id=product_id,
                    name=name,
                    seo_description=enrichment.get("seo_description"),
                    attributes=enrichment.get("attributes"),
                    correlation_id=headers.get("x-correlation-id", ""),
                )

        except Exception as e:
            log.error(
                "event_handler_failed",
                topic=msg.topic, offset=msg.offset, event_id=event_id, error=str(e),
            )
        finally:
            set_correlation_id(None)

    async def _publish_enriched(
        self,
        product_id: int,
        name: str,
        seo_description: Optional[str],
        attributes: Optional[dict[str, Any]],
        correlation_id: str,
    ) -> None:
        assert self._producer is not None
        payload = {
            "product_id": product_id,
            "name": name,
            "seo_description": seo_description,
            "attributes": attributes,
        }
        headers = []
        if correlation_id:
            headers.append(("x-correlation-id", correlation_id.encode()))

        await self._producer.send_and_wait(
            "ProductEnriched",
            key=str(product_id).encode(),
            value=json.dumps(payload).encode(),
            headers=headers,
        )
        log.info("product_enriched_published", product_id=product_id)

    async def stop(self) -> None:
        self._stopped = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        log.info("kafka_consumer_stopped")


_consumer_instance: Optional[ProductEventConsumer] = None


def get_consumer() -> ProductEventConsumer:
    global _consumer_instance
    if _consumer_instance is None:
        _consumer_instance = ProductEventConsumer()
    return _consumer_instance
