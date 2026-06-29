"""
db/connection.py — asyncpg connection pool for MuftyKare voice agent.

Pool lifecycle:
- Each agent job creates its OWN pool via create_pool()
- The pool is injected into MuftyKareUserData.db_pool
- The job closes its own pool on shutdown via close_pool(pool)

Design: NO global singleton pool.
Reason: LiveKit runs multiple overlapping job processes. A global pool closed
by job-1's shutdown would silently break job-2 that grabbed the same reference.
Each job owns its pool → no cross-session contamination.

Never import this directly in tools — tools receive the pool
via context.userdata.db_pool. Only agent.py and server.py call create_pool().
"""
from __future__ import annotations

import asyncpg
from logger import get_logger
from config.settings import DATABASE_URL
from db.schema import DB_STATS

logger = get_logger(__name__)


async def create_pool() -> asyncpg.Pool:
    """
    Create a NEW asyncpg connection pool for this job.
    Called once per agent job in agent.py entrypoint.
    Each job gets its own isolated pool — never shared across sessions.
    """
    pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=_init_connection,
    )
    logger.info(
        "asyncpg pool created",
        extra={
            "min_size": 2,
            "max_size": 10,
            "db": "muftykare",
            "customers": DB_STATS["customer"],
            "orders": DB_STATS["orders"],
        },
    )
    return pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Called for each new connection in the pool."""
    await conn.execute("SET timezone = 'Asia/Kolkata'")


async def close_pool(pool: asyncpg.Pool) -> None:
    """
    Close the given pool instance.
    Called in ctx.add_shutdown_callback() with this job's own pool.
    """
    if pool and not pool._closed:
        await pool.close()
        logger.info("asyncpg pool closed")


async def health_check() -> bool:
    """
    Quick DB connectivity check. Used by FastAPI GET /health.
    Creates a temporary pool, checks connectivity, then closes it.
    Returns True if DB is reachable, False otherwise.
    """
    pool = None
    try:
        pool = await create_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.error("DB health check failed", extra={"error": str(e)})
        return False
    finally:
        if pool:
            await close_pool(pool)
