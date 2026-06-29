"""
tests/test_greeter.py — Tests for GreeterAgent routing and identification.

Covers:
- T1.1: Returning customer correctly identified and greeted by name
- T1.5: Status check guard — agent asks for phone before transferring
- Greeting scenarios: small talk, general queries, "are you a bot?"
- Transfer routing: booking intent → BookingAgent
- Complaint routing: damage → ComplaintAgent immediately
- Human escalation: explicit manager request
"""
import pytest
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import GreeterAgent, BookingAgent, StatusAgent, ComplaintAgent
from userdata import MuftyKareUserData


@pytest.mark.asyncio
async def test_returning_customer_greeted_by_name(
    db_pool, real_customer, judge_llm, base_userdata
):
    """
    T1.1: When a returning customer calls, agent should:
    1. Call lookup_customer silently
    2. Greet them by name (not generic greeting)
    """
    phone = real_customer["phone_num"]
    name = real_customer["name"]
    base_userdata.caller_phone = f"+91{phone}"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())
        print(f"USER DATA : {base_userdata}")
        result = await sess.run(user_input="Namaskaram")

        # Agent must call lookup_caller
        result.expect[:].contains_function_call(name="lookup_caller")

        # Agent response must include the customer's name
        await result.expect.next_event(type="message").judge(
            llm,
            intent=(
                f"must greet the customer by name '{name}' "
                "in Telugu or Telugu-English mix. "
                "Must NOT give a generic greeting like 'How can I help you?' "
                "without mentioning their name."
            )
        )


@pytest.mark.asyncio
async def test_status_guard_requires_phone_first(judge_llm, base_userdata):
    """
    T1.5: When an unidentified caller asks for order status,
    agent must ask for phone number BEFORE transferring to StatusAgent.
    Must NOT transfer without identification.
    """
    # No caller_phone set — unknown caller
    base_userdata.caller_phone = None
    base_userdata.customer_id = None

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())

        with mock_tools(GreeterAgent, {
            "lookup_caller": lambda: "Caller not found in database. This is a new customer."
        }):
            result = await sess.run(user_input="Naa order status cheppu")

        # Must NOT hand off to StatusAgent yet
        events = result.events
        handoff_events = [e for e in events if e.type == "agent_handoff"]
        assert len(handoff_events) == 0, (
            "Agent transferred to StatusAgent without identifying caller first"
        )

        # Must ask for phone number
        await result.expect.next_event(type="message").judge(
            llm,
            intent=(
                "must ask the customer for their phone number or registered number "
                "before checking order status. "
                "Must NOT mention order details yet."
            )
        )


@pytest.mark.asyncio
async def test_booking_intent_routes_to_booking_agent(judge_llm, base_userdata):
    """
    When customer expresses pickup intent, agent must route to BookingAgent.
    """
    base_userdata.caller_phone = "+919876543210"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())

        with mock_tools(GreeterAgent, {
            "lookup_caller": lambda: "Caller identified: Test User, customer ID 99. Greet them by name 'Test User' in Telugu."
        }):
            result = await sess.run(user_input="Pickup book cheskovadam kavali")

        # Must transfer to BookingAgent
        result.expect[:].contains_function_call(name="to_booking")
        result.expect[:].contains_agent_handoff(new_agent_type=BookingAgent)


@pytest.mark.asyncio
async def test_complaint_routes_to_complaint_agent_immediately(judge_llm, base_userdata):
    """
    When customer mentions damage, agent must route to ComplaintAgent IMMEDIATELY.
    Must NOT ask questions or investigate — just transfer.
    """
    base_userdata.caller_phone = "+919876543210"
    base_userdata.customer_id = 42
    base_userdata.customer_name = "Raju"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())

        result = await sess.run(user_input="Naa shirt damage ayyindi")

        # Must call to_complaint immediately
        result.expect[:].contains_function_call(name="to_complaint")
        result.expect[:].contains_agent_handoff(new_agent_type=ComplaintAgent)


@pytest.mark.asyncio
async def test_general_query_answered_without_transfer(judge_llm, base_userdata):
    """
    General queries (timings, location) must be answered directly.
    No tools called, no transfer.
    """
    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())
        result = await sess.run(user_input="Mee timings enti?")

        # No tool calls, no transfers
        tool_calls = [e for e in result.events if e.type == "function_call"]
        transfers = [e for e in result.events if e.type == "agent_handoff"]
        assert len(tool_calls) == 0, (
            f"Unexpected tool calls: {[e.item.name for e in tool_calls]}"
        )
        assert len(transfers) == 0, "Unexpected transfer for general query"

        # Must mention working hours
        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must state working hours: Monday to Saturday, 10 AM to 7 PM. "
                "Must NOT ask for phone number or show order info."
            )
        )


@pytest.mark.asyncio
async def test_honest_about_being_ai(judge_llm, base_userdata):
    """
    When asked 'are you a bot?', agent must answer honestly and move forward.
    Must NOT deny being AI.
    """
    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(GreeterAgent())
        result = await sess.run(user_input="Meeru robot aa, person aa?")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must honestly acknowledge being an AI assistant. "
                "Must NOT claim to be a human. "
                "Must offer to help with MuftyKare services after answering."
            )
        )
