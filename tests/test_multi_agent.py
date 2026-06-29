"""
tests/test_multi_agent.py — End-to-end multi-agent conversation flows.

These tests start at GreeterAgent and flow through multiple agent handoffs,
testing the full conversation path as a real customer would experience it.

Covers:
- Full inbound booking: Greeter → Booking → confirmation
- Status then new booking: Greeter → Status → Booking
- Context (customer_id) preserved across all agent handoffs
"""
import pytest
from datetime import date, timedelta
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import GreeterAgent, BookingAgent, StatusAgent, ComplaintAgent
from userdata import MuftyKareUserData


@pytest.mark.asyncio
async def test_full_inbound_booking_flow(db_pool, judge_llm, base_userdata, real_customer):
    """
    Complete inbound booking flow:
    1. Greeter identifies caller
    2. Greeter routes to BookingAgent
    3. BookingAgent collects details and confirms
    All in one continuous session.
    """
    phone = real_customer["phone_num"]
    name = real_customer["name"]
    base_userdata.caller_phone = f"+91{phone}"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())

        # Turn 1: Greet and express intent
        with mock_tools(GreeterAgent, {
            "lookup_customer": lambda: f"Customer identified: {name}, ID {real_customer['id']}."
        }):
            result = await sess.run(
                user_input="Namaskaram, pickup book cheskovadam kavali"
            )

        # Must route to BookingAgent
        result.expect[:].contains_function_call(name="to_booking")
        result.expect[:].contains_agent_handoff(new_agent_type=BookingAgent)

        # Turn 2: Provide service type (now in BookingAgent)
        result = await sess.run(user_input="Dry cleaning")
        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent="must ask for pickup address or confirm the saved address"
        )

        # Turn 3: Address
        result = await sess.run(user_input="Same address ki raandi")

        # Turn 4: Slot with availability check
        with mock_tools(BookingAgent, {
            "check_slot_availability": lambda: f"Slot available: morning on {tomorrow}. 5 remaining."
        }):
            result = await sess.run(user_input="Tomorrow morning")

        # Turn 5: Confirm
        with mock_tools(BookingAgent, {
            "create_booking": lambda: "Booking confirmed! Order ID: MK-9999.",
            "send_sms_confirmation": lambda: "SMS sent."
        }):
            result = await sess.run(user_input="Ha, correct cheskovadam")

        result.expect[:].contains_function_call(name="create_booking")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent="must confirm booking is complete and provide order ID"
        )


@pytest.mark.asyncio
async def test_status_check_then_new_booking(judge_llm, base_userdata, real_customer):
    """
    Customer checks status, then decides to book a new pickup.
    Session flows: Greeter → Status → Booking.
    Context (customer ID) must be preserved across all three agents.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]
    base_userdata.caller_phone = f"+91{real_customer['phone_num']}"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())

        # Turn 1: Status request
        with mock_tools(GreeterAgent, {
            "lookup_customer": lambda: (
                f"Customer found: {real_customer['name']}, ID {real_customer['id']}."
            )
        }):
            result = await sess.run(user_input="Naa order status cheppu")

        result.expect[:].contains_agent_handoff(new_agent_type=StatusAgent)

        # Turn 2: Now in StatusAgent — get status
        with mock_tools(StatusAgent, {
            "get_order_status": lambda: (
                "Order #1659: మీ బట్టలు deliver అయ్యాయి. payment complete అయింది."
            )
        }):
            result = await sess.run(user_input="Status cheppu")
            result.expect[:].contains_function_call(name="get_order_status")

        # Turn 3: Customer wants new booking after hearing status
        result = await sess.run(user_input="Ok, ika new pickup book cheskovadam kavali")
        result.expect[:].contains_agent_handoff(new_agent_type=BookingAgent)

        # Verify customer_id preserved across agents
        assert base_userdata.customer_id == real_customer["id"], (
            "customer_id lost during multi-agent handoff"
        )
