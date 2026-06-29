"""
tests/conftest.py — Shared pytest fixtures for MuftyKare agent tests.

Fixtures:
- db_pool: fresh asyncpg pool per test (function-scoped — fixes Windows event loop issue)
- judge_llm: GPT-4o instance reused as judge across tests (session-scoped — stateless)
- real_customer: a real customer record from production DB
- real_order: most recent order for that customer
- base_userdata: fresh MuftyKareUserData per test (function-scoped)

NOTE on db_pool scope:
  Session-scoped db_pool causes ConnectionDoesNotExistError on Windows because
  pytest-asyncio creates a new event loop per test function, but asyncpg connections
  are bound to the loop they were created on. Function-scoped pool fixes this by
  creating a fresh pool on the same loop as the test — exactly matching production
  where the pool is created inside the entrypoint function on the LiveKit worker loop.
"""
# ── Load .env FIRST — before any livekit/openai imports ───────────────────
import pathlib
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env", override=True)
# ──────────────────────────────────────────────────────────────────────────

import asyncio
import asyncpg
import os
import pytest
import pytest_asyncio
from livekit.agents import inference
from logger import setup_logging

setup_logging()


# ── NO custom event_loop fixture ──────────────────────────────────────────
# Removed session-scoped event_loop — pytest-asyncio manages this per test.
# The custom session event_loop was the root cause of cross-loop DB errors.
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture  # function-scoped (default) — fresh pool per test
async def db_pool():
    """
    Fresh asyncpg pool per test function.
    Created on the same event loop as the test — no cross-loop issues.
    Mirrors production exactly: pool created inside entrypoint on worker loop.
    """
    pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),
        min_size=1,
        max_size=3,
        command_timeout=30,
    )
    yield pool
    await asyncio.sleep(0.1)  # let pending connections drain
    await pool.close()


@pytest_asyncio.fixture  # function-scoped
async def real_customer(db_pool):
    """
    Fetch a real customer from production DB for use in tests.
    Returns dict with id, name, phone_num, address.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, phone_num, address FROM customer "
            "WHERE phone_num IS NOT NULL AND name IS NOT NULL "
            "ORDER BY id LIMIT 1"
        )
    assert row is not None, "No customers found in DB — run migrate.py first"
    return dict(row)


@pytest_asyncio.fixture  # function-scoped
async def real_order(db_pool, real_customer):
    """
    Fetch the most recent order for the test customer.
    Returns dict with id, bill, status, pmt_status, etc. or None.
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, total_price, discount, other_charges, "
            "(COALESCE(total_price,0) - COALESCE(discount,0) + COALESCE(other_charges,0)) AS bill, "
            "status, ready_to_deliver, pmt_status "
            "FROM orders WHERE cust_id = $1 "
            "ORDER BY recieved_on DESC LIMIT 1",
            real_customer["id"]
        )
    return dict(row) if row else None


@pytest.fixture(scope="session")  # session-scoped is fine — LLM is stateless
def judge_llm():
    """
    GPT-4o instance used as judge in .judge() assertions.
    Temperature 0 for deterministic judgments.
    Session-scoped: safe because inference.LLM has no event loop binding.
    """
    return inference.LLM(
        model="openai/gpt-4o",
        extra_kwargs={"parallel_tool_calls": False, "temperature": 0.0}
    )


@pytest.fixture  # function-scoped — fresh per test, no shared state
def base_userdata(db_pool):
    """
    Base MuftyKareUserData with DB pool and agents registry.
    Function-scoped: each test gets a clean slate with no leftover state
    from previous tests (customer_id, order_id, intent, etc.).
    """
    from userdata import MuftyKareUserData
    from agents import build_agent_registry
    from config.constants import DIRECTION_INBOUND

    ud = MuftyKareUserData(
        db_pool=db_pool,
        call_direction=DIRECTION_INBOUND,
        call_id="test-room-001",
        language="te-IN",
    )
    ud.agents = build_agent_registry()
    return ud