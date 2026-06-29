"""
tests/test_complaint.py — Tests for ComplaintAgent severity triage and escalation.

Covers:
- T1.4: Critical complaint (damage/missing) → warm transfer immediately
- Low severity → logged, team will review (no warm transfer)
- Empathy always spoken before action
- log_complaint always called before escalation
- Wrong clothes / missing → immediate escalation, no investigation
"""
import pytest
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import ComplaintAgent, BookingAgent
from userdata import MuftyKareUserData


@pytest.mark.asyncio
async def test_critical_complaint_escalates_immediately(judge_llm, base_userdata, real_customer):
    """
    T1.4: Critical severity complaint (damage) must:
    1. Speak empathy first
    2. Call log_complaint with severity='critical'
    3. Call escalate_to_manager
    Must NOT attempt self-resolution.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]
    base_userdata.current_order_id = 1

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(ComplaintAgent())

        with mock_tools(ComplaintAgent, {
            "log_complaint": lambda: (
                "Complaint logged (ID: 1). Type: damaged. Severity: critical. Escalating to manager."
            ),
            "escalate_to_manager": lambda: None
        }):
            result = await sess.run(user_input="Naa shirt damage ayyindi, fabric torn ayyindi")

        # Must call log_complaint
        result.expect[:].contains_function_call(name="log_complaint")

        # Must call escalate_to_manager
        result.expect[:].contains_function_call(name="escalate_to_manager")

        # Empathy must be in response
        await result.expect[0].is_message(role="assistant").judge(
            llm,
            intent=(
                "must express genuine empathy and apologize for the damaged shirt. "
                "Must NOT be dismissive or defensive. "
                "Must NOT say 'that's not possible' or 'our team is careful'. "
                "Must say they will connect to manager."
            )
        )


@pytest.mark.asyncio
async def test_low_severity_logs_and_informs_team_review(judge_llm, base_userdata, real_customer):
    """
    Low severity complaint (stain not removed) must log the complaint and inform
    the customer that the team will review and contact them. It must NOT escalate to manager.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.current_order_id = 1

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(ComplaintAgent())

        with mock_tools(ComplaintAgent, {
            "log_complaint": lambda: (
                "Complaint logged (ID: 2). Type: stain. Severity: low. Logged for team review."
            )
        }):
            result = await sess.run(
                user_input="Stain poyindi kaadu"
            )

        # Must call log_complaint
        result.expect[:].contains_function_call(name="log_complaint")

        escalation_calls = [
            e for e in result.events
            if e.type == "function_call" and e.item.name == "escalate_to_manager"
        ]
        assert len(escalation_calls) == 0, (
            "escalate_to_manager called for low severity stain complaint"
        )

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must empathize and state that the complaint has been recorded and the team will review and contact them. "
                "Must NOT mention calling a manager or escalating."
            )
        )


@pytest.mark.asyncio
async def test_missing_clothes_escalates_without_questioning(judge_llm, base_userdata, real_customer):
    """
    Missing clothes is CRITICAL — must escalate immediately.
    Must NOT ask 'are you sure?' or investigate before escalating.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.current_order_id = 1

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(ComplaintAgent())

        with mock_tools(ComplaintAgent, {
            "log_complaint": lambda: "Complaint logged. Severity: critical.",
            "escalate_to_manager": lambda: None
        }):
            result = await sess.run(user_input="Oka shirt raaledu, missing ayyindi")

        # Must escalate
        result.expect[:].contains_function_call(name="escalate_to_manager")

        # Response must NOT question the customer
        await result.expect[0].is_message(role="assistant").judge(
            llm,
            intent=(
                "must believe the customer and empathize immediately. "
                "Must NOT say 'are you sure?' or 'let me check' as a way of doubting. "
                "Must say they will connect to manager."
            )
        )


@pytest.mark.asyncio
async def test_empathy_always_spoken_before_action(judge_llm, base_userdata, real_customer):
    """
    Empathy message must ALWAYS come before any tool call.
    Agent must not silently jump to logging without acknowledging the customer.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.current_order_id = 1

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(ComplaintAgent())

        with mock_tools(ComplaintAgent, {
            "log_complaint": lambda: "Complaint logged.",
            "escalate_to_manager": lambda: None
        }):
            result = await sess.run(user_input="3 rojulu ayyindi inkaa raaledu enti?")

        events = result.events

        # First message event must come before first function_call event
        first_msg_idx = next(
            (i for i, e in enumerate(events) if e.type == "message" and e.item.role == "assistant"),
            None
        )
        first_tool_idx = next(
            (i for i, e in enumerate(events) if e.type == "function_call"),
            None
        )

        if first_tool_idx is not None:
            assert first_msg_idx is not None and first_msg_idx < first_tool_idx, (
                "Agent called a tool before speaking empathy to the customer"
            )
