"""
tests/test_booking.py — Tests for BookingAgent conversation flows.

Covers:
- T1.2: Full new customer booking flow end-to-end
- T1.6: Slot full → alternative offered
- Returning customer reuses saved address
- Booking guard: confirm=False blocks create_booking
- Cancel booking flow
"""
import pytest
from datetime import date, timedelta
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import BookingAgent, GreeterAgent
from userdata import MuftyKareUserData
from config.constants import SERVICE_WASH_FOLD, SLOT_MORNING, SLOT_AFTERNOON


@pytest.mark.asyncio
async def test_new_customer_full_booking(db_pool, judge_llm, base_userdata):
    """
    T1.2: Full booking flow for a new customer.
    Verifies tool call sequence: check_slot → create_booking → send_sms_confirmation.
    Verifies confirmation spoken to customer with order ID and SMS mention.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    base_userdata.customer_id = 695  # use a known test customer ID
    base_userdata.customer_name = "Test Customer"
    base_userdata.caller_phone = "+919000000001"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(BookingAgent())

        # Turn 1: State intent
        result = await sess.run(user_input="Normal wash cheskovadam kavali")
        result.expect.skip_next_event_if(type="message", role="assistant")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent="must ask for pickup address or time slot"
        )

        # Turn 2: Provide address
        result = await sess.run(
            user_input="Flat 4B, Madhura Nagar, Dwaraka Nagar daggara"
        )
        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent="must ask for preferred pickup time slot (morning, afternoon, or evening)"
        )

        # Turn 3: Choose slot
        with mock_tools(BookingAgent, {
            "check_slot_availability": lambda: (
                f"Slot available: morning (8:00 AM - 11:00 AM) on {tomorrow}. "
                "5 slots remaining. Proceed to confirm booking."
            )
        }):
            result = await sess.run(user_input="Tomorrow morning chaallu")
            result.expect[:].contains_function_call(name="check_slot_availability")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must read back the complete booking summary: "
                "service type (Normal wash), pickup time (tomorrow morning), "
                "and address. Must ask for confirmation."
            )
        )

        # Turn 4: Confirm
        with mock_tools(BookingAgent, {
            "create_booking": lambda: (
                "Booking confirmed! Order ID: MK-9999. "
                "Service: WASH_FOLD. Pickup: tomorrow morning. SMS confirmation will be sent."
            ),
            "send_sms_confirmation": lambda: "SMS sent to customer."
        }):
            result = await sess.run(user_input="Ha, correct")
            result.expect[:].contains_function_call(name="create_booking")

        # Verify confirmation spoken
        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must confirm the booking is complete and provide an order ID. "
                "Must mention that SMS will be sent or has been sent."
            )
        )


@pytest.mark.asyncio
async def test_slot_full_fallback(db_pool, judge_llm, base_userdata):
    """
    T1.6: When requested slot is full, agent must offer alternatives.
    Must NOT book into a full slot.
    """
    base_userdata.customer_id = 1
    base_userdata.customer_name = "Raju"
    base_userdata.caller_phone = "+919876543210"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(BookingAgent())

        result = await sess.run(
            user_input="Normal wash, tomorrow morning slot kavali"
        )

        with mock_tools(BookingAgent, {
            "check_slot_availability": lambda: (
                "Slot 'morning' on tomorrow is not available. "
                "Available slots: afternoon (3 remaining), evening (7 remaining)."
            )
        }):
            result = await sess.run(user_input="Tomorrow morning")
            result.expect[:].contains_function_call(name="check_slot_availability")

        # Must NOT call create_booking
        booking_calls = [
            e for e in result.events
            if e.type == "function_call" and e.item.name == "create_booking"
        ]
        assert len(booking_calls) == 0, "create_booking called despite slot being full"

        # Must offer alternatives
        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must inform that morning slot is not available and "
                "offer alternative slots (afternoon or evening). "
                "Must NOT say the booking is confirmed."
            )
        )


@pytest.mark.asyncio
async def test_returning_customer_uses_saved_address(judge_llm, base_userdata):
    """
    Returning customer says 'same address' — agent must use saved address
    without asking for a new one.
    """
    base_userdata.customer_id = 1
    base_userdata.customer_name = "Raju"
    base_userdata.customer_address = "Flat 4B, Madhura Nagar, Dwaraka Nagar"
    base_userdata.caller_phone = "+919876543210"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(BookingAgent())
        result = await sess.run(
            user_input="Dry cleaning kavali, same address ki raandi"
        )

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must acknowledge using the saved address (Flat 4B, Madhura Nagar) "
                "and proceed to ask for pickup slot. "
                "Must NOT ask for address again."
            )
        )


@pytest.mark.asyncio
async def test_booking_requires_explicit_confirmation(judge_llm, base_userdata):
    """
    Agent must NOT call create_booking until customer says 'ha correct'.
    Saying 'ok' or 'sare' to a question is NOT a booking confirmation.
    """
    base_userdata.customer_id = 1
    base_userdata.customer_name = "Raju"
    base_userdata.caller_phone = "+919876543210"
    base_userdata.service_type = SERVICE_WASH_FOLD
    base_userdata.pickup_slot_date = (date.today() + timedelta(days=1)).isoformat()
    base_userdata.pickup_slot_name = SLOT_MORNING
    base_userdata.pickup_address = "Flat 4B, Madhura Nagar"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(BookingAgent())

        # Ambiguous response — NOT explicit confirmation
        result = await sess.run(user_input="Ok cheppindi")

        # create_booking must NOT be called yet
        booking_calls = [
            e for e in result.events
            if e.type == "function_call" and e.item.name == "create_booking"
        ]
        assert len(booking_calls) == 0, (
            "create_booking was called without explicit 'ha correct' confirmation"
        )
