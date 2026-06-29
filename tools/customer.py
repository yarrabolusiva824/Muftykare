"""
tools/customer.py — Customer identity tools for MuftyKare voice agent.

TWO separate tools for customer lookup:

1. lookup_caller — NO arguments — used at call START, reads phone from userdata.caller_phone
   GPT-4o cannot pass wrong phone because there is no phone argument.

2. lookup_customer_by_number — HAS phone arg — used when customer speaks their number verbally.

3. save_new_customer — saves a new customer after collecting name + address.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field
from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool

from db.queries import fetch_customer_by_phone, insert_customer
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


@function_tool
async def lookup_caller(context: RunCtx) -> str:
    """
    Look up the caller in MuftyKare database using their SIP phone number.

    Call this as your VERY FIRST action at the start of every inbound call,
    BEFORE speaking the greeting. No arguments needed — the phone number is
    taken automatically from the SIP caller ID already stored in the session.

    Do NOT use this when the customer provides a number verbally —
    use lookup_customer_by_number for that case instead.

    After this succeeds:
    - If customer found: greet them by name from the result
    - If not found: give generic greeting, offer to register them
    """
    phone = context.userdata.caller_phone

    if not phone:
        logger.info("tool:lookup_caller — no caller_phone available")
        context.userdata.is_new_customer = True
        return (
            "No caller ID available from this call. "
            "Ask the customer for their registered phone number, "
            "then call lookup_customer_by_number."
        )

    masked = f"****{phone[-4:]}"
    logger.info("tool:lookup_caller called", extra={"phone": masked})

    pool = context.userdata.db_pool

    try:
        result = await fetch_customer_by_phone(pool, phone)
    except Exception as e:
        logger.error("tool:lookup_caller db error", extra={"error": str(e)})
        raise ToolError("Database error during customer lookup") from e

    if not result:
        try:
            new_id = await insert_customer(pool, name="Guest", phone=phone, address="")
            context.userdata.customer_id = new_id
            context.userdata.customer_name = "Guest"
            context.userdata.customer_address = ""
            context.userdata.is_new_customer = True
            logger.info("tool:lookup_caller auto-created", extra={"customer_id": new_id})
            return (
                f"New caller automatically registered as Guest, customer ID {new_id}. "
                "Give generic greeting. You don't need to ask for their name."
            )
        except Exception as e:
            context.userdata.is_new_customer = True
            logger.error("tool:lookup_caller auto-create failed", extra={"error": str(e)})
            return "Caller not found in database. This is a new customer — give generic greeting."

    # Update shared userdata
    context.userdata.customer_id = result["id"]
    context.userdata.customer_name = result.get("name") or "Customer"
    context.userdata.customer_address = result.get("address")
    context.userdata.is_new_customer = False

    logger.info(
        "tool:lookup_caller found",
        extra={"customer_id": result["id"], "customer_name": result.get("name")},
    )
    return (
        f"Caller identified: {result['name']}, customer ID {result['id']}. "
        f"Address on file: {result.get('address') or 'not saved'}. "
        f"Greet them by name '{result['name']}' in Telugu."
    )


@function_tool
async def lookup_customer_by_number(
    context: RunCtx,
    phone: Annotated[
        str,
        Field(
            description=(
                "Phone number as spoken by the customer. "
                "Use exactly what the customer said, e.g. '9876543210' or '+919876543210'. "
                "NEVER pass masked values like '****1489' — that is a log format, not a real number."
            )
        ),
    ],
) -> str:
    """
    Look up a customer when they provide their phone number verbally mid-conversation.

    Call this ONLY when:
    - Customer says their number: "Naa number 9876543210"
    - lookup_caller returned 'no caller ID' and customer provides their number
    - Customer says "check by my number" and gives digits

    Do NOT call this at session start — use lookup_caller for that.
    Do NOT pass masked phone numbers (****XXXX) — only real digits the customer spoke.
    """
    masked = f"****{phone[-4:]}" if len(phone) >= 4 else "****"
    logger.info("tool:lookup_customer_by_number called", extra={"phone": masked})

    pool = context.userdata.db_pool

    try:
        result = await fetch_customer_by_phone(pool, phone)
    except Exception as e:
        logger.error("tool:lookup_customer_by_number db error", extra={"error": str(e)})
        raise ToolError("Database error during customer lookup") from e

    if not result:
        try:
            new_id = await insert_customer(pool, name="Guest", phone=phone, address="")
            context.userdata.customer_id = new_id
            context.userdata.customer_name = "Guest"
            context.userdata.customer_address = ""
            context.userdata.caller_phone = phone
            context.userdata.is_new_customer = True
            logger.info("tool:lookup_customer_by_number auto-created", extra={"customer_id": new_id})
            return (
                f"Customer automatically registered as Guest, ID {new_id}. "
                "You don't need to ask for their name, just proceed with their request."
            )
        except Exception as e:
            context.userdata.is_new_customer = True
            logger.error("tool:lookup_customer_by_number auto-create failed", extra={"error": str(e)})
            return (
                "Customer not found with that number. "
                "Ask them to double-check, or offer to register as new customer."
            )

    context.userdata.customer_id = result["id"]
    context.userdata.customer_name = result.get("name") or "Customer"
    context.userdata.customer_address = result.get("address")
    context.userdata.caller_phone = phone
    context.userdata.is_new_customer = False

    logger.info(
        "tool:lookup_customer_by_number found",
        extra={"customer_id": result["id"], "customer_name": result.get("name")},
    )
    return (
        f"Customer found: {result['name']}, ID {result['id']}. "
        f"Address: {result.get('address') or 'not saved'}."
    )


@function_tool
async def save_new_customer(
    context: RunCtx,
    name: Annotated[str, Field(description="Customer's full name as spoken. Confirm spelling before calling.")],
    phone: Annotated[str, Field(description="Customer's phone number. 10 digits, may include +91 prefix.")],
    address: Annotated[str, Field(description="Full pickup address including flat/door number, area, and landmark if mentioned.")],
) -> str:
    """
    Save a new customer to the database.

    Call this ONLY when:
    1. lookup_caller OR lookup_customer_by_number returned 'not found'
    2. You have collected the customer's name AND address
    3. You have CONFIRMED the name spelling with the customer

    Do NOT call before confirming name — once saved it's hard to change.

    Telugu trigger context:
    - After asking "Mee peru enti?" and getting a response
    - After asking "Mee address endi?" and getting a response
    - Only after BOTH name and address are confirmed
    """
    masked = f"****{phone[-4:]}" if len(phone) >= 4 else "****"
    logger.info("tool:save_new_customer called", extra={"phone": masked, "customer_name": name})

    pool = context.userdata.db_pool

    if context.userdata.customer_id:
        return f"Customer already exists with ID {context.userdata.customer_id}. No need to save again."

    try:
        customer_id = await insert_customer(pool, name, phone, address)
    except Exception as e:
        logger.error("tool:save_new_customer db error", extra={"error": str(e)})
        raise ToolError("Failed to save new customer") from e

    context.userdata.customer_id = customer_id
    context.userdata.customer_name = name
    context.userdata.customer_address = address
    context.userdata.caller_phone = phone
    context.userdata.is_new_customer = False

    logger.info("tool:save_new_customer saved", extra={"customer_id": customer_id})
    return f"New customer saved successfully. Customer ID: {customer_id}. Name: {name}."
