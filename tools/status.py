"""
tools/status.py — Order status and billing tools for MuftyKare voice agent.

Used by: StatusAgent
"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from db.queries import (
    fetch_latest_order,
    fetch_all_orders,
    fetch_order_items,
    fetch_delivery_status,
)
from config.constants import (
    ORDER_STATUS_RESPONSES,
    PAYMENT_STATUS_RESPONSES,
    INTENT_STATUS,
    INTENT_BILLING,
    OUTCOME_STATUS_PROVIDED,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


@function_tool
async def get_order_status(
    context: RunCtx,
) -> str:
    """
    Get the current status of the customer's latest order.

    Call when customer asks about their order or delivery:
    - "Naa babbulu ekkada?" (Where are my clothes?)
    - "Order ready ayyindaa?" (Is my order ready?)
    - "Delivery eppudu vastundi?" (When will delivery come?)
    - "Naa order status enti?" (What's my order status?)

    Precondition: customer_id must be known (call lookup_customer first).

    Returns:
        Telugu status description ready to speak to customer.
        Never returns raw boolean values — always human-readable Telugu.
    """
    logger.info("tool:get_order_status called", extra={"customer_id": context.userdata.customer_id})
    pool = context.userdata.db_pool

    # Guard — customer must be identified
    if not context.userdata.customer_id:
        return "మీ phone number తెలియదు. Status check కోసం phone number చెప్పండి."

    try:
        order = await fetch_latest_order(pool, context.userdata.customer_id)
    except Exception as e:
        raise ToolError("Failed to fetch order status") from e

    if not order:
        return "మీ account లో ఏ order కూడా కనుగొనబడలేదు."

    # Update userdata
    context.userdata.current_order_id = order["id"]
    context.userdata.intent = INTENT_STATUS
    context.userdata.outcome = OUTCOME_STATUS_PROVIDED

    # Map booleans → Telugu status strings (NEVER return raw booleans)
    is_delivered = order.get("status", False)
    is_ready = order.get("ready_to_deliver", False)
    pmt_status = order.get("pmt_status", "not paid")

    if is_delivered:
        delivery_msg = ORDER_STATUS_RESPONSES["delivered"]
    elif is_ready:
        delivery_msg = ORDER_STATUS_RESPONSES["ready"]
    else:
        delivery_msg = ORDER_STATUS_RESPONSES["cleaning"]

    payment_msg = PAYMENT_STATUS_RESPONSES.get(pmt_status, "payment status తెలియదు")

    logger.info(
        "tool:get_order_status result",
        extra={"order_id": order["id"], "status": is_delivered, "ready": is_ready},
    )
    return f"Order #{order['id']}: {delivery_msg}. {payment_msg}."


@function_tool
async def get_bill(
    context: RunCtx,
) -> str:
    """
    Get the bill amount for the customer's latest order.

    Call when customer asks about money or billing:
    - "Naa bill enta?" (How much is my bill?)
    - "Total enta ayyindi?" (What's the total?)
    - "Enta pay cheyyali?" (How much to pay?)
    - "Bill cheppu" (Tell me the bill)

    Bill formula: total_price - discount + other_charges
    Never invent or approximate amounts — always use DB values.

    Precondition: customer_id must be known.

    Returns:
        Bill amount in Telugu-friendly format, or not-found message.
    """
    logger.info("tool:get_bill called", extra={"customer_id": context.userdata.customer_id})
    pool = context.userdata.db_pool

    if not context.userdata.customer_id:
        return "మీ phone number తెలియదు. Bill check కోసం phone number చెప్పండి."

    try:
        order = await fetch_latest_order(pool, context.userdata.customer_id)
    except Exception as e:
        raise ToolError("Failed to fetch bill") from e

    if not order:
        return "మీ account లో ఏ order కూడా కనుగొనబడలేదు."

    context.userdata.current_order_id = order["id"]
    context.userdata.intent = INTENT_BILLING

    bill = order.get("bill", 0) or 0
    total = order.get("total_price", 0) or 0
    discount = order.get("discount", 0) or 0
    other = order.get("other_charges", 0) or 0
    pmt = order.get("pmt_status", "not paid")

    payment_msg = PAYMENT_STATUS_RESPONSES.get(pmt, "")

    logger.info("tool:get_bill result", extra={"order_id": order["id"], "bill": bill})

    if discount > 0:
        return (
            f"Order #{order['id']} bill: ₹{total} - ₹{discount} discount "
            f"+ ₹{other} charges = Total ₹{bill}. {payment_msg}."
        )
    return f"Order #{order['id']} bill: ₹{bill}. {payment_msg}."


@function_tool
async def get_order_items(
    context: RunCtx,
) -> str:
    """
    Get the itemized list of clothes/items in the customer's latest order.

    Call when customer asks for item breakdown:
    - "Enta items ichaanu?" (How many items did I give?)
    - "Emi emi wash chesaaru?" (What all did you wash?)
    - "Items list cheppu" (Tell me the items list)
    - After bill query when customer questions specific charges

    Precondition: customer_id must be known.

    Returns:
        Itemized list as natural text, or not-found message.
    """
    logger.info("tool:get_order_items called", extra={"customer_id": context.userdata.customer_id})
    pool = context.userdata.db_pool

    if not context.userdata.customer_id:
        return "మీ phone number తెలియదు."

    # Get latest order first if not already known
    if not context.userdata.current_order_id:
        order = await fetch_latest_order(pool, context.userdata.customer_id)
        if not order:
            return "మీ account లో ఏ order కూడా కనుగొనబడలేదు."
        context.userdata.current_order_id = order["id"]

    try:
        items = await fetch_order_items(pool, context.userdata.current_order_id)
    except Exception as e:
        raise ToolError("Failed to fetch order items") from e

    if not items:
        return f"Order #{context.userdata.current_order_id} లో items కనుగొనబడలేదు."

    lines = []
    for item in items:
        cat = item.get("category", "")
        itype = item.get("item_type", "")
        service = item.get("service", "")
        count = item.get("num_of_items", 0)
        price = item.get("price", 0)
        lines.append(f"{count}x {cat} ({itype}) - {service}: ₹{price}")

    logger.info(
        "tool:get_order_items result",
        extra={"order_id": context.userdata.current_order_id, "count": len(items)},
    )
    return f"Order #{context.userdata.current_order_id} items: " + "; ".join(lines)


@function_tool
async def get_all_orders(
    context: RunCtx,
) -> str:
    """
    Get the last 3 orders for the customer.

    Call when customer mentions multiple orders:
    - "Rendu orders ichaamu" (I gave two orders)
    - "Anni orders status cheppu" (Tell me all orders status)
    - "Previous orders kuda cheppu" (Tell me previous orders too)

    Precondition: customer_id must be known.

    Returns:
        Summary of last 3 orders as readable text.
    """
    logger.info("tool:get_all_orders called", extra={"customer_id": context.userdata.customer_id})
    pool = context.userdata.db_pool

    if not context.userdata.customer_id:
        return "మీ phone number తెలియదు."

    try:
        orders = await fetch_all_orders(pool, context.userdata.customer_id, limit=3)
    except Exception as e:
        raise ToolError("Failed to fetch orders") from e

    if not orders:
        return "మీ account లో ఏ orders కూడా కనుగొనబడలేదు."

    lines = []
    for o in orders:
        status = "delivered" if o.get("status") else ("ready" if o.get("ready_to_deliver") else "cleaning")
        lines.append(f"Order #{o['id']}: ₹{o.get('bill', 0)} - {status} - {o.get('pmt_status', 'unknown')}")

    logger.info("tool:get_all_orders result", extra={"count": len(orders)})
    return f"Last {len(orders)} orders: " + " | ".join(lines)
