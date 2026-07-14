"""
tools/booking.py — Pickup booking tools for MuftyKare voice agent.

Used by: BookingAgent
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from db.queries import (
    insert_order,
)
from config.constants import (
    SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING, SLOT_LABELS,
    SERVICE_WASH_FOLD, SERVICE_DRY_CLEAN, SERVICE_EXPRESS, SERVICE_SHOE_CLEAN,
    INTENT_BOOKING, OUTCOME_BOOKING_CREATED,
)
from prompts.shared import _IS_ENGLISH
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

# Guard/fallback strings spoken as-is (not LLM-generated) — need an explicit
# English variant alongside the Telugu default.
_MSG = {
    "no_phone_booking": "Could you share your phone number? I'll need it before I can book this."
        if _IS_ENGLISH else "మీ phone number తెలియదు. Booking చేయడానికి ముందు phone number చెప్పండి.",
    "no_order_reschedule": "We couldn't find an order to reschedule. Could you share the order ID?"
        if _IS_ENGLISH else "ఏ order కూడా found కాలేదు. Reschedule చేయడానికి order ID చెప్పండి.",
    "no_active_booking": "We couldn't find an active booking to cancel."
        if _IS_ENGLISH else "Cancel చేయడానికి active booking కనుగొనబడలేదు.",
}


@function_tool
async def check_slot_availability(
    context: RunCtx,
    slot_date: Annotated[str, Field(description="Date in YYYY-MM-DD format. 'today' and 'tomorrow' should be converted to actual dates before calling.")],
    time_preference: Annotated[str, Field(description="Preferred time or slot name (e.g., 'morning', '11 AM', 'between 2 and 4'). Must be between 10 AM and 7 PM.")],
) -> str:
    """
    Check if a specific pickup slot is available on a given date.

    Call this BEFORE create_booking to confirm the slot is open.
    Never create a booking without checking availability first.

    Slots are available Monday to Saturday between 10 AM and 7 PM.
    Sundays are closed.

    Returns:
        Availability status string. If available, proceed to create_booking.
    """
    logger.info("tool:check_slot_availability called", extra={"date": slot_date, "time": time_preference})

    try:
        parsed_date = date.fromisoformat(slot_date)
    except ValueError:
        return f"Invalid date format '{slot_date}'. Please use YYYY-MM-DD."

    # 6 corresponds to Sunday in Python's datetime (Monday is 0)
    if parsed_date.weekday() == 6:
        next_date = (parsed_date + timedelta(days=1)).isoformat()
        return f"No slots available on {slot_date} (Sunday is closed). Please check {next_date} (Monday) or another date."

    # Store in userdata for create_booking to use
    context.userdata.pickup_slot_date = slot_date
    context.userdata.pickup_slot_name = time_preference

    logger.info(
        "tool:check_slot_availability available",
        extra={"date": slot_date, "time": time_preference},
    )
    return (
        f"Slot available on {slot_date} for {time_preference}. "
        f"Please proceed to confirm booking."
    )


@function_tool
async def create_booking(
    context: RunCtx,
    service_type: Annotated[str, Field(description="Service type. One of: 'WASH_FOLD', 'DRY_CLEAN', 'EXPRESS', 'SHOE_CLEAN'")],
    pickup_address: Annotated[str, Field(description="Full pickup address. Use customer's saved address if they said 'same address as last time'.")],
    confirmed: Annotated[bool, Field(description="True only if user explicitly said 'ha', 'correct', 'yes', 'confirm chesandi' to the booking summary. Never set True without explicit confirmation.")],
) -> str:
    """
    Create a pickup booking after collecting all details and getting confirmation.

    CRITICAL: Only call this after ALL of the following:
    1. customer_id is known (lookup_customer was called)
    2. check_slot_availability confirmed slot is open
    3. service_type is known
    4. pickup_address is confirmed
    5. User explicitly confirmed the booking summary (confirmed=True)

    NEVER call this without explicit user confirmation ("ha, correct" / "yes").

    Telugu confirmation triggers:
    - "Ha, correct"
    - "Sare, book cheskovadam"
    - "Confirm chesandi"
    - "Ok, proceed cheyyandi"

    Returns:
        Booking confirmation with order ID, or error if preconditions not met.
    """
    logger.info(
        "tool:create_booking called",
        extra={
            "customer_id": context.userdata.customer_id,
            "service": service_type,
            "slot_date": context.userdata.pickup_slot_date,
            "slot_name": context.userdata.pickup_slot_name,
            "confirmed": confirmed,
        },
    )
    pool = context.userdata.db_pool

    # Guard — confirmed must be True
    if not confirmed:
        return "Booking not confirmed yet. Please summarize the details and ask the user to confirm."

    # Guard — customer must be identified
    if not context.userdata.customer_id:
        return _MSG["no_phone_booking"]

    # Guard — slot must be selected
    if not context.userdata.pickup_slot_date or not context.userdata.pickup_slot_name:
        return "Slot not selected. Please check slot availability first."

    # Validate service type
    valid_services = [SERVICE_WASH_FOLD, SERVICE_DRY_CLEAN, SERVICE_EXPRESS, SERVICE_SHOE_CLEAN]
    if service_type not in valid_services:
        return f"Invalid service type '{service_type}'. Must be one of: {', '.join(valid_services)}."

    try:
        # Create blank order
        order_id = await insert_order(pool, context.userdata.customer_id)
    except Exception as e:
        logger.error("tool:create_booking db error", extra={"error": str(e)})
        raise ToolError("Failed to create booking. Please try again.") from e

    # Update userdata
    context.userdata.current_order_id = order_id
    context.userdata.service_type = service_type
    context.userdata.pickup_address = pickup_address
    context.userdata.intent = INTENT_BOOKING
    context.userdata.outcome = OUTCOME_BOOKING_CREATED

    logger.info(
        "tool:create_booking success",
        extra={"order_id": order_id, "service": service_type},
    )
    return (
        f"Booking confirmed! Order ID: MK-{order_id}. "
        f"Service: {service_type}. "
        f"Pickup: {context.userdata.pickup_slot_date} at {context.userdata.pickup_slot_name}. "
        f"Address: {pickup_address}. "
        f"SMS confirmation will be sent."
    )


@function_tool
async def reschedule_slot(
    context: RunCtx,
    new_date: Annotated[str, Field(description="New date in YYYY-MM-DD format.")],
    new_time_preference: Annotated[str, Field(description="New preferred time (e.g., 'morning', '11 AM'). Must be between 10 AM and 7 PM.")],
) -> str:
    """
    Reschedule a pickup slot for the current order.

    Call when:
    - User wants to change their pickup time after booking
    - User was not home and wants to reschedule delivery
    - Triggered by: "Slot change cheskovadam", "Different time lo raandi"

    Requires: current_order_id must be set in userdata.

    Returns:
        Rescheduling result string.
    """
    logger.info("tool:reschedule_slot called", extra={"new_date": new_date, "new_time": new_time_preference})

    if not context.userdata.current_order_id:
        return _MSG["no_order_reschedule"]

    try:
        parsed_date = date.fromisoformat(new_date)
    except ValueError:
        return f"Invalid date format '{new_date}'. Please use YYYY-MM-DD."

    if parsed_date.weekday() == 6:
        next_date = (parsed_date + timedelta(days=1)).isoformat()
        return f"No slots available on {new_date} (Sunday is closed). Please check {next_date} (Monday) or another date."

    # Update userdata
    context.userdata.pickup_slot_date = new_date
    context.userdata.pickup_slot_name = new_time_preference

    logger.info("tool:reschedule_slot success", extra={"new_date": new_date, "new_time": new_time_preference})
    return f"Slot rescheduled to {new_time_preference} on {new_date}."


@function_tool
async def cancel_booking(
    context: RunCtx,
    confirmed: Annotated[bool, Field(description="True only if user explicitly confirmed they want to cancel.")],
) -> str:
    """
    Cancel the current pickup booking.

    Call when user wants to cancel their booking.
    Telugu triggers: "Cancel chesandi pickup", "Inkaa raakandi", "booking cancel"

    ALWAYS confirm before cancelling — ask "Meeru nijamgaa cancel cheyyalanukunnaara?"
    Only call with confirmed=True after explicit user confirmation.

    Returns:
        Cancellation confirmation or error string.
    """
    logger.info(
        "tool:cancel_booking called",
        extra={"order_id": context.userdata.current_order_id, "confirmed": confirmed},
    )
    pool = context.userdata.db_pool

    if not confirmed:
        return "Please confirm cancellation first. Ask: 'Meeru nijamgaa cancel cheyyalanukunnaara?'"

    if not context.userdata.current_order_id:
        return _MSG["no_active_booking"]

    # Mark order as cancelled — soft cancel logged to voice_call_log via outcome
    context.userdata.outcome = "booking_cancelled"

    order_id = context.userdata.current_order_id
    context.userdata.current_order_id = None
    context.userdata.pickup_slot_date = None
    context.userdata.pickup_slot_name = None

    logger.info("tool:cancel_booking success", extra={"order_id": order_id})
    return f"Booking MK-{order_id} cancelled successfully. Slot has been released."
