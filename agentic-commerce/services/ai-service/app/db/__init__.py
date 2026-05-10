"""Async Postgres connection pool with pgvector support."""
from typing import Optional

import asyncpg

from ..config import settings

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=10,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool


async def ping() -> None:
    async with get_pool().acquire() as conn:
        await conn.fetchval("SELECT 1")
