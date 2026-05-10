"""FastAPI application entry point for the AI service."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .correlation import CorrelationMiddleware
from .db import close_pool, init_pool
from .events.consumer import get_consumer
from .logger import configure_logging, get_logger
from .routers import health as health_router
from .routers import search as search_router
from .services.ollama import close_ollama_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown hooks. Order matters:
    DB pool first, then Kafka consumer (which uses the DB).
    On shutdown, reverse: stop consumer, then close DB.
    """
    configure_logging("ai-service", level=settings.log_level)
    log = get_logger(__name__)
    log.info("starting_ai_service", port=settings.port, env=settings.env)

    await init_pool()
    log.info("db_pool_initialized")

    consumer = get_consumer()
    try:
        await consumer.start()
    except Exception as e:
        # Kafka being unavailable at startup shouldn't kill the service —
        # readiness probe will report it as not_ready until reconnected
        log.warning("kafka_consumer_start_failed", error=str(e))

    yield

    log.info("shutting_down_ai_service")
    health_router.mark_shutting_down()
    try:
        await consumer.stop()
    except Exception as e:
        log.warning("kafka_consumer_stop_failed", error=str(e))
    await close_ollama_client()
    await close_pool()
    log.info("shutdown_complete")


app = FastAPI(
    title="agentic-commerce AI service",
    description="Semantic product search and AI enrichment via local Ollama models",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationMiddleware)
app.include_router(health_router.router)
app.include_router(search_router.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_config=None,  # We configure logging ourselves via configure_logging()
    )
