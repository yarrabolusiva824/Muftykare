"""
tools/notification.py — SMS notification tools for MuftyKare voice agent.

Used by: BookingAgent (after successful booking)
Note: In dev mode, SMS is logged but not actually sent (no Plivo credentials required).
"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from config.settings import PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER
from config.constants import SLOT_LABELS
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


@function_tool
async def send_sms_confirmation(
    context: RunCtx,
    order_id: Annotated[int, Field(description="The order ID returned by create_booking.")],
    slot_label: Annotated[str, Field(description="Human readable slot e.g. 'tomorrow morning (8-11am)'")],
) -> str:
    """
    Send an SMS booking confirmation to the customer.

    Call immediately after create_booking succeeds.
    Telugu context: "మీకు SMS వస్తుంది" (You will receive an SMS)

    In development mode (no Plivo credentials): logs the SMS content without sending.
    In production: sends real SMS via Plivo.

    Returns:
        Confirmation that SMS was sent (or logged in dev mode).
    """
    phone = context.userdata.caller_phone
    name = context.userdata.customer_name or "Customer"

    sms_text = (
        f"MuftyKare: Dear {name}, your laundry pickup is confirmed! "
        f"Order MK-{order_id}. Pickup: {slot_label}. "
        f"Tracking: https://muftykare.com/order/{order_id}. "
        f"Support: 7075232425"
    )

    logger.info(
        "tool:send_sms_confirmation called",
        extra={
            "order_id": order_id,
            "phone": f"****{phone[-4:]}" if phone else "unknown",
            "message_preview": sms_text[:60],
        },
    )

    # Dev mode — no Plivo credentials
    if not PLIVO_AUTH_ID or not PLIVO_AUTH_TOKEN:
        logger.info(
            "tool:send_sms_confirmation DEV MODE — SMS not sent",
            extra={"sms_text": sms_text},
        )
        return f"SMS confirmation logged (dev mode — not sent). Message: {sms_text}"

    # Production — send via Plivo
    try:
        import plivo
        client = plivo.RestClient(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN)
        response = client.messages.create(
            src=PLIVO_PHONE_NUMBER,
            dst=phone,
            text=sms_text,
        )
        logger.info(
            "tool:send_sms_confirmation sent",
            extra={"message_uuid": str(response)},
        )
        return f"SMS sent to customer. Order MK-{order_id} confirmed."
    except Exception as e:
        logger.error("tool:send_sms_confirmation failed", extra={"error": str(e)})
        return f"SMS could not be sent, but booking is confirmed. Order MK-{order_id}."
