"""Kafka consumer that listens for ProductCreated events and generates
embeddings automatically. This is the event-driven AI enrichment pattern."""
import asyncio
import json
from typing import Optional

from aiokafka import AIOKafkaConsumer

from ..config import settings
from ..logger import get_logger, set_correlation_id
from ..services.embeddings import upsert_product_embedding

log = get_logger(__name__)


class ProductEventConsumer:
    def __init__(self) -> None:
        self._consumer: Optional[AIOKafkaConsumer] = None
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
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        assert self._consumer is not None
        try:
            async for msg in self._consumer:
                if self._stopped:
                    break

                # Restore correlation context from message headers
                headers = {k: v.decode() for k, v in (msg.headers or [])}
                set_correlation_id(headers.get("x-correlation-id"))

                try:
                    payload = json.loads(msg.value.decode())
                    await upsert_product_embedding(
                        product_id=payload["product_id"],
                        name=payload["name"],
                        description=payload.get("description", ""),
                        category=payload.get("category", "general"),
                    )
                except Exception as e:
                    log.error(
                        "event_handler_failed",
                        topic=msg.topic,
                        offset=msg.offset,
                        error=str(e),
                    )
                finally:
                    set_correlation_id(None)
        except asyncio.CancelledError:
            log.info("kafka_consumer_cancelled")

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
        log.info("kafka_consumer_stopped")


_consumer_instance: Optional[ProductEventConsumer] = None


def get_consumer() -> ProductEventConsumer:
    global _consumer_instance
    if _consumer_instance is None:
        _consumer_instance = ProductEventConsumer()
    return _consumer_instance
