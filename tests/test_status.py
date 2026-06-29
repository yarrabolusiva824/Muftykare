"""
tests/test_status.py — Tests for StatusAgent order status and billing.

Covers:
- T1.3: Status to complaint pivot (most critical mid-call pivot)
- Bill query returns correct amount spoken naturally
- Raw boolean values never spoken to customer
- Payment dispute redirects to support number
"""
import pytest
from livekit.agents import AgentSession
from livekit.agents.voice.run_result import mock_tools

from agents import StatusAgent, ComplaintAgent, BookingAgent
from userdata import MuftyKareUserData


@pytest.mark.asyncio
async def test_status_to_complaint_pivot(judge_llm, base_userdata, real_customer, real_order):
    """
    T1.3: CRITICAL — After hearing status, customer says clothes are damaged.
    Agent MUST immediately pivot to ComplaintAgent without asking questions.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]
    base_userdata.caller_phone = f"+91{real_customer['phone_num']}"

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(StatusAgent())

        # Turn 1: Get status
        with mock_tools(StatusAgent, {
            "get_order_status": lambda: (
                "Order #1234: మీ బట్టలు deliver అయ్యాయి. payment pending ఉంది."
            )
        }):
            result = await sess.run(user_input="Naa order status cheppu")
            result.expect[:].contains_function_call(name="get_order_status")

        # Turn 2: Customer raises complaint after hearing status
        result = await sess.run(user_input="Kaani shirt damage ayyindi")

        # MUST transfer to ComplaintAgent immediately
        result.expect[:].contains_function_call(name="to_complaint")
        result.expect[:].contains_agent_handoff(new_agent_type=ComplaintAgent)


@pytest.mark.asyncio
async def test_bill_spoken_correctly(judge_llm, base_userdata, real_customer):
    """
    Bill amount must be spoken as natural Telugu sentence.
    Must never say raw numbers without context.
    """
    base_userdata.customer_id = real_customer["id"]
    base_userdata.customer_name = real_customer["name"]

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(StatusAgent())

        with mock_tools(StatusAgent, {
            "get_bill": lambda: "Order #1659 bill: ₹450. payment pending ఉంది."
        }):
            result = await sess.run(user_input="Naa bill enta?")
            result.expect[:].contains_function_call(name="get_bill")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must speak the bill amount clearly (₹450) in a natural sentence. "
                "Must mention payment status. "
                "Must NOT read raw field names like 'total_price' or 'bill: 450' without context."
            )
        )


@pytest.mark.asyncio
async def test_status_never_reads_raw_booleans(judge_llm, base_userdata, real_customer):
    """
    Agent must translate status=False into Telugu phrase, never say 'False' or 'TRUE'.
    """
    base_userdata.customer_id = real_customer["id"]

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(StatusAgent())

        with mock_tools(StatusAgent, {
            "get_order_status": lambda: (
                "Order #100: మీ బట్టలు cleaning లో ఉన్నాయి, కొంచెం సమయం పడుతుంది. payment pending ఉంది."
            )
        }):
            result = await sess.run(user_input="Naa babbulu ekkada unnaayi?")

    response_text = " ".join(
        e.item.text_content for e in result.events
        if e.type == "message" and e.item.role == "assistant"
        and e.item.text_content
    )

    # Must NEVER contain raw boolean values
    assert "False" not in response_text, "Agent spoke raw 'False' to customer"
    assert "True" not in response_text, "Agent spoke raw 'True' to customer"
    # case-insensitive guard — allow the word only if clearly contextual
    assert "false" not in response_text.lower() or "meaning" in response_text.lower()
    assert "true" not in response_text.lower() or "meaning" in response_text.lower()


@pytest.mark.asyncio
async def test_payment_dispute_redirects_to_support(judge_llm, base_userdata, real_customer):
    """
    Payment disputes must redirect to support number 7075232425.
    Agent must NOT attempt to resolve payment issues.
    """
    base_userdata.customer_id = real_customer["id"]

    async with judge_llm as llm, AgentSession(
        llm=llm, userdata=base_userdata
    ) as sess:
        await sess.start(StatusAgent())
        result = await sess.run(user_input="Refund kavali, wrong amount charge chesaaru")

        await result.expect[-1].is_message(role="assistant").judge(
            llm,
            intent=(
                "must direct the customer to call support at 7075232425 for payment issues. "
                "Must NOT promise a refund. "
                "Must NOT say 'I will resolve this' or 'we will refund you'."
            )
        )
