"""
tools/sms.py — SMS confirmation tool.

Docstrings are intentionally in English — GPT-4o reads these to decide when
to invoke each tool. Telugu/mixed-language docstrings cause incorrect invocation.

Implementation uses Plivo SMS API — wired in Component 5.
"""

from livekit.agents import function_tool, RunContext

from logger import get_logger

logger = get_logger(__name__)


@function_tool
async def send_sms_confirmation(
    context: RunContext,
    phone: str,
    order_id: str,
    pickup_slot: str,
) -> dict:
    """
    Send an SMS booking confirmation to the customer.

    Args:
        phone: Customer phone number in E.164 format (e.g. +919876543210)
        order_id: The booking order ID (e.g. MK-2847)
        pickup_slot: Human-readable slot string e.g. "Tomorrow 8-11am"

    Returns:
        Dict with sent (bool) and message_id
    """
    logger.info(
        "Tool called: send_sms_confirmation",
        extra={
            "phone_last4": phone[-4:] if phone else None,
            "order_id": order_id,
            "pickup_slot": pickup_slot,
        },
    )
    # TODO: implement with Plivo SMS API in Component 5
    # import plivo
    # client = plivo.RestClient(auth_id, auth_token)
    # response = client.messages.create(src=PLIVO_PHONE_NUMBER, dst=phone, text=msg)
    result = {"sent": True, "message_id": "stub"}
    logger.info(
        "Tool result: send_sms_confirmation",
        extra={
            "phone_last4": phone[-4:] if phone else None,
            "order_id": order_id,
            "sent": result["sent"],
            "message_id": result["message_id"],
        },
    )
    return result
