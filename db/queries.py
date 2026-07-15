"""
db/queries.py — asyncpg query functions for MuftyKare voice agent.

Rules:
1. All SQL strings imported from db.schema.QUERIES — never hardcode SQL here
2. Every function logs entry at DEBUG and result at INFO
3. Phone numbers logged as last 4 digits only (PII protection)
4. Functions return dict | list[dict] | int | None — never raw asyncpg Records
5. Use async with pool.acquire() as conn — never pool.fetchrow() directly
"""
from __future__ import annotations

from datetime import date
from typing import Any

import asyncpg

from db.schema import QUERIES
from logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_customer_by_phone(
    pool: asyncpg.Pool,
    phone: str,
) -> dict[str, Any] | None:
    """
    Look up a customer by phone number.

    Normalizes: strips +91, matches last 10 digits against customer.phone_num.
    Returns dict with keys: id, name, phone_num, address
    Returns None if not found.
    """
    masked = f"****{phone[-4:]}" if len(phone) >= 4 else "****"
    logger.debug("fetch_customer_by_phone", extra={"phone": masked})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(QUERIES["lookup_customer_by_phone"], phone)

    if not row:
        logger.info("customer not found", extra={"phone": masked})
        return None

    result = dict(row)
    logger.info(
        "customer found",
        extra={"customer_id": result["id"], "customer_name": result.get("name", "unknown")},
    )
    return result


async def insert_customer(
    pool: asyncpg.Pool,
    name: str,
    phone: str,
    address: str,
) -> int:
    """
    Insert a new customer record.
    Returns the new customer_id (integer).
    """
    masked = f"****{phone[-4:]}" if len(phone) >= 4 else "****"
    logger.debug("insert_customer", extra={"phone": masked, "customer_name": name})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(QUERIES["insert_customer"], name, phone, address)

    customer_id = row["id"]
    logger.info("customer created", extra={"customer_id": customer_id})
    return customer_id


# ─────────────────────────────────────────────────────────────────────────────
# ORDER QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_latest_order(
    pool: asyncpg.Pool,
    customer_id: int,
) -> dict[str, Any] | None:
    """
    Get the most recent order for a customer.

    Returns dict with keys:
        id, total_price, discount, other_charges, bill (computed),
        status (bool), ready_to_deliver (bool), pmt_status,
        recieved_on, delivered_on
    Returns None if no orders found.
    """
    logger.debug("fetch_latest_order", extra={"customer_id": customer_id})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(QUERIES["get_latest_order"], customer_id)

    if not row:
        logger.info("no orders found", extra={"customer_id": customer_id})
        return None

    result = dict(row)
    logger.info(
        "order fetched",
        extra={
            "order_id": result["id"],
            "bill": result.get("bill"),
            "status": result.get("status"),
            "pmt_status": result.get("pmt_status"),
        },
    )
    return result


async def fetch_all_orders(
    pool: asyncpg.Pool,
    customer_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Get the N most recent orders for a customer.
    Used when customer says "rendu orders ichaamu" (I gave two orders).
    Returns list of order dicts (same shape as fetch_latest_order).
    """
    logger.debug("fetch_all_orders", extra={"customer_id": customer_id, "limit": limit})

    # Inline SQL: dynamic LIMIT parameter not in QUERIES dict
    sql = """
        SELECT
            o.id,
            o.total_price,
            o.discount,
            o.other_charges,
            (COALESCE(o.total_price,0) - COALESCE(o.discount,0) + COALESCE(o.other_charges,0)) AS bill,
            o.status,
            o.ready_to_deliver,
            o.pmt_status,
            o.recieved_on,
            o.delivered_on
        FROM orders o
        WHERE o.cust_id = $1
        ORDER BY o.recieved_on DESC, o.id DESC
        LIMIT $2
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, customer_id, limit)

    result = [dict(r) for r in rows]
    logger.info("orders fetched", extra={"customer_id": customer_id, "count": len(result)})
    return result


async def fetch_order_items(
    pool: asyncpg.Pool,
    order_id: int,
) -> list[dict[str, Any]]:
    """
    Get all items for an order (ordered_items UNION other_items).

    Returns list of dicts with keys:
        category, item_type, service, num_of_items, price
    Used when customer asks "enta items ichaanu?" or requests itemized bill.
    """
    logger.debug("fetch_order_items", extra={"order_id": order_id})

    async with pool.acquire() as conn:
        rows = await conn.fetch(QUERIES["get_order_items"], order_id)

    result = [dict(r) for r in rows]
    logger.info(
        "order items fetched",
        extra={"order_id": order_id, "item_count": len(result)},
    )
    return result


async def fetch_delivery_status(
    pool: asyncpg.Pool,
    customer_id: int,
) -> dict[str, Any] | None:
    """
    Get delivery status of the latest order.

    Returns dict with keys:
        id, is_delivered (bool), ready_to_deliver (bool),
        delivered_on, pmt_status, recieved_on
    Returns None if no orders.
    """
    logger.debug("fetch_delivery_status", extra={"customer_id": customer_id})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(QUERIES["get_delivery_status"], customer_id)

    if not row:
        logger.info("no orders for delivery status", extra={"customer_id": customer_id})
        return None

    result = dict(row)
    logger.info(
        "delivery status fetched",
        extra={
            "order_id": result["id"],
            "is_delivered": result.get("is_delivered"),
            "ready": result.get("ready_to_deliver"),
        },
    )
    return result


async def insert_order(
    pool: asyncpg.Pool,
    customer_id: int,
) -> int:
    """
    Create a new blank order for a customer.
    Returns the new order_id (integer).

    Creates order with zero amounts — items/service added via ordered_items
    after booking is confirmed. This follows the existing schema pattern
    where the WhatsApp chatbot also creates orders this way.
    """
    logger.debug("insert_order", extra={"customer_id": customer_id})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(QUERIES["create_order"], customer_id)

    order_id = row["id"]
    logger.info("order created", extra={"order_id": order_id, "customer_id": customer_id})
    return order_id


# ─────────────────────────────────────────────────────────────────────────────
# SLOT QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_slot_availability(
    pool: asyncpg.Pool,
    slot_date: str,
) -> list[dict[str, Any]]:
    """
    Get available pickup slots for a given date.

    Args:
        slot_date: Date string in "YYYY-MM-DD" format

    Returns list of available slots with keys:
        slot_name, slot_label, capacity, booked, remaining
    Returns empty list if no slots available on that date.
    """
    logger.debug("fetch_slot_availability", extra={"date": slot_date})

    parsed_date = date.fromisoformat(slot_date)

    async with pool.acquire() as conn:
        rows = await conn.fetch(QUERIES["check_slot_availability"], parsed_date)

    result = [dict(r) for r in rows]
    logger.info(
        "slots fetched",
        extra={"date": slot_date, "available_slots": len(result)},
    )
    return result


async def increment_slot_booked(
    pool: asyncpg.Pool,
    slot_date: str,
    slot_name: str,
) -> None:
    """
    Increment the booked count for a slot after a confirmed booking.
    Called immediately after insert_order succeeds.
    """
    logger.debug(
        "increment_slot_booked",
        extra={"date": slot_date, "slot": slot_name},
    )

    parsed_date = date.fromisoformat(slot_date)

    async with pool.acquire() as conn:
        await conn.execute(
            QUERIES["increment_slot_booked"],
            parsed_date,
            slot_name,
        )

    logger.info(
        "slot booked incremented",
        extra={"date": slot_date, "slot": slot_name},
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALL LOG QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def log_call_start(
    pool: asyncpg.Pool,
    call_id: str,
    caller_phone: str | None,
    customer_id: int | None,
    direction: str,
    language: str = "te-IN",
) -> int:
    """
    Insert a new row in voice_call_log at call start.
    Returns the log row id.

    caller_phone is masked to last 4 digits before storage (PII protection).
    """
    masked_phone = (
        f"****{caller_phone[-4:]}"
        if caller_phone and len(caller_phone) >= 4
        else "unknown"
    )

    logger.debug(
        "log_call_start",
        extra={
            "call_id": call_id,
            "direction": direction,
            "phone": masked_phone,
            "customer_id": customer_id,
        },
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            QUERIES["log_call_start"],
            call_id,
            masked_phone,
            customer_id,
            direction,
            language,
        )

    log_id = row["id"]
    logger.info(
        "call log started",
        extra={"log_id": log_id, "call_id": call_id, "direction": direction},
    )
    return log_id


async def log_call_end(
    pool: asyncpg.Pool,
    call_id: str,
    intent: str | None,
    order_id: int | None,
    outcome: str | None,
    transcript_path: str | None = None,
) -> None:
    """
    Update voice_call_log with call outcome at call end.
    Called inside ctx.add_shutdown_callback() — fires even on crash.
    """
    logger.debug(
        "log_call_end",
        extra={
            "call_id": call_id,
            "intent": intent,
            "order_id": order_id,
            "outcome": outcome,
        },
    )

    async with pool.acquire() as conn:
        await conn.execute(
            QUERIES["log_call_end"],
            call_id,
            intent,
            order_id,
            outcome,
            transcript_path,
        )

    logger.info(
        "call log ended",
        extra={"call_id": call_id, "intent": intent, "outcome": outcome},
    )


async def log_call_recording(
    pool,
    call_id: str,
    customer_id: int | None,
    caller_phone: str | None,
    egress_id: str,
    file_path: str,
    call_log_id: int | None = None,
) -> int | None:
    """Insert a call recording record. Returns the new row id."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO call_recordings
                    (call_id, customer_id, caller_phone, egress_id, file_path, call_log_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                call_id,
                customer_id,
                caller_phone,
                egress_id,
                file_path,
                call_log_id,
            )
            return row["id"] if row else None
    except Exception as e:
        logger.warning("log_call_recording failed", extra={"error": str(e)})
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PRICING QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_all_item_prices(
    pool: asyncpg.Pool,
) -> list[dict[str, Any]]:
    """
    Fetch the full catalog of item prices.
    Used by the AI to locally search for a customer's requested item.

    Returns a list of dicts with keys: item_type, service, price
    """
    logger.debug("fetch_all_item_prices")

    sql = """
        SELECT
            ic.name  AS category,
            it.name  AS item_type,
            sc.name  AS service,
            ip.price AS price
        FROM item_price ip
        JOIN item_type it        ON ip.item_type_id = it.id
        JOIN item_categories ic  ON it.it_cat_id = ic.id
        JOIN service_category sc ON ip.serv_type_id = sc.id
        ORDER BY ic.name, it.name, sc.name
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    result = [dict(row) for row in rows]
    logger.info("all prices fetched", extra={"count": len(result)})
    return result


async def fetch_service_categories(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """
    Get all service categories (Dry Clean, Steam Iron, Laundry).
    Used for general pricing queries.
    """
    logger.debug("fetch_service_categories")

    # Inline SQL: simple lookup not in QUERIES dict
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM service_category ORDER BY id")

    result = [dict(r) for r in rows]
    logger.info("service categories fetched", extra={"count": len(result)})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def insert_complaint(
    pool: asyncpg.Pool,
    customer_id: int,
    order_id: int | None,
    complaint_type: str,
    description: str,
    severity: str,
) -> int:
    """
    Log a customer complaint to a complaints table.

    NOTE: complaints table does not exist in the original schema.
    This function creates it if it doesn't exist (first call creates table).
    Returns complaint_id.
    """
    logger.debug(
        "insert_complaint",
        extra={
            "customer_id": customer_id,
            "order_id": order_id,
            "type": complaint_type,
            "severity": severity,
        },
    )

    # Create table if not exists (once — subsequent calls are no-ops)
    create_sql = """
        CREATE TABLE IF NOT EXISTS complaints (
            id              SERIAL PRIMARY KEY,
            customer_id     INTEGER REFERENCES customer(id),
            order_id        INTEGER REFERENCES orders(id),
            complaint_type  TEXT,
            description     TEXT,
            severity        TEXT,
            status          TEXT DEFAULT 'open',
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """

    insert_sql = """
        INSERT INTO complaints
            (customer_id, order_id, complaint_type, description, severity)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
    """

    async with pool.acquire() as conn:
        await conn.execute(create_sql)
        row = await conn.fetchrow(
            insert_sql,
            customer_id,
            order_id,
            complaint_type,
            description,
            severity,
        )

    complaint_id = row["id"]
    logger.info(
        "complaint logged",
        extra={
            "complaint_id": complaint_id,
            "customer_id": customer_id,
            "type": complaint_type,
        },
    )
    return complaint_id
