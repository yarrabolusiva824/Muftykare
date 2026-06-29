"""
tests/test_outbound.py — Tests for OutboundAgent initiated calls.

Covers:
- Reminder call: agent opens with correct Telugu greeting
- User not home → transfers to BookingAgent for rescheduling
- Complaint during outbound → routes to ComplaintAgent
"""
import pytest
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import OutboundAgent, BookingAgent, ComplaintAgent
from userdata import MuftyKareUserData
from config.constants import CALL_TYPE_REMINDER, CALL_TYPE_DELIVERY, CALL_TYPE_PAYMENT


@pytest.mark.asyncio
async def test_reminder_call_greeting(judge_llm, base_userdata, real_customer):
    """
    Outbound reminder call must open with MuftyKare introduction
    and ask if customer is home. Must NOT wait for customer to speak first.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]
    base_userdata.caller_phone = f"+91{real_customer['phone_num']}"
    base_userdata.call_direction = "outbound"
    base_userdata.call_type = CALL_TYPE_REMINDER
    base_userdata.pickup_slot_name = "morning"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(OutboundAgent(call_type=CALL_TYPE_REMINDER))

        # Outbound: agent speaks first without user input
        result = await sess.run(user_input="Hello?")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must introduce themselves as calling from MuftyKare. "
                "Must mention the pickup appointment. "
                "Must ask if the customer is home (inti lo unnara?). "
                "Must be brief and purposeful."
            )
        )


@pytest.mark.asyncio
async def test_reminder_call_user_not_home_reschedules(judge_llm, base_userdata, real_customer):
    """
    When user says not home during reminder call,
    agent must transfer to BookingAgent for rescheduling.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]
    base_userdata.call_direction = "outbound"
    base_userdata.call_type = CALL_TYPE_REMINDER

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(OutboundAgent(call_type=CALL_TYPE_REMINDER))

        result = await sess.run(
            user_input="Ledu, nenu office lo unnaanu. Repu raagalara?"
        )

        result.expect[:].contains_function_call(name="to_booking")
        result.expect[:].contains_agent_handoff(new_agent_type=BookingAgent)


@pytest.mark.asyncio
async def test_complaint_during_outbound_routes_correctly(judge_llm, base_userdata, real_customer):
    """
    If customer raises a complaint during an outbound call,
    agent must route to ComplaintAgent.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.call_direction = "outbound"
    base_userdata.call_type = CALL_TYPE_DELIVERY

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(OutboundAgent(call_type=CALL_TYPE_DELIVERY))

        result = await sess.run(
            user_input="Deliver chesaaru kaani clothes damage ayyindi"
        )

        result.expect[:].contains_function_call(name="to_complaint")
        result.expect[:].contains_agent_handoff(new_agent_type=ComplaintAgent)
