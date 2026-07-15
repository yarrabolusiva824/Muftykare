"""
agents/outbound.py — OutboundAgent: agent-initiated calls.

Used for:
- Pickup reminders (30 min before scheduled slot)
- Delivery confirmations (clothes ready for delivery)
- Payment reminders (pending payment)

Dispatched via POST /call/outbound with call_type parameter.
"""
from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from agents.base import MuftyKareBaseAgent
from tools.booking import reschedule_slot
from tools.status import get_bill
from tools.campaign import log_campaign_outcome
from prompts.outbound import (
    OUTBOUND_REMINDER_PROMPT,
    OUTBOUND_DELIVERY_PROMPT,
    OUTBOUND_PAYMENT_PROMPT,
    OUTBOUND_PROSPECTING_PROMPT,
)
from config.constants import (
    AGENT_BOOKING, AGENT_COMPLAINT,
    CALL_TYPE_REMINDER, CALL_TYPE_DELIVERY, CALL_TYPE_PAYMENT, CALL_TYPE_PROSPECTING,
    OUTCOME_MISSED,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

# Prompt map by call type
_PROMPT_MAP = {
    CALL_TYPE_REMINDER:    OUTBOUND_REMINDER_PROMPT,
    CALL_TYPE_DELIVERY:    OUTBOUND_DELIVERY_PROMPT,
    CALL_TYPE_PAYMENT:     OUTBOUND_PAYMENT_PROMPT,
    CALL_TYPE_PROSPECTING: OUTBOUND_PROSPECTING_PROMPT,
}

_DRY_CLEAN_OPENER_TE = (
    "నమస్కారం {name} గారూ! MuftyKare నుండి Kavya మాట్లాడుతున్నాను. "
    "మీరు మాతో Dry Cleaning చేశారు — మళ్ళీ ఈ వారం అవసరమా?"
)
_NO_DRY_CLEAN_OPENER_TE = (
    "నమస్కారం {name} గారూ! MuftyKare నుండి Kavya మాట్లాడుతున్నాను. "
    "మీరు మాతో Regular Wash చేస్తున్నారు — మీకు Dry Cleaning గురించి చెప్పనా?"
)
_DRY_CLEAN_OPENER_EN = (
    "Hello {name}! This is Kavya from MuftyKare. "
    "You've used our Dry Cleaning service before — do you need it again this week?"
)
_NO_DRY_CLEAN_OPENER_EN = (
    "Hello {name}! This is Kavya from MuftyKare. "
    "You've been using our regular wash service — can I tell you about our Dry Cleaning service?"
)


def _build_prospecting_opener(customer_context: dict, is_english: bool) -> str:
    name = customer_context.get("name") or ("there" if is_english else "గారూ")
    if customer_context.get("has_used_dry_cleaning"):
        template = _DRY_CLEAN_OPENER_EN if is_english else _DRY_CLEAN_OPENER_TE
    else:
        template = _NO_DRY_CLEAN_OPENER_EN if is_english else _NO_DRY_CLEAN_OPENER_TE
    return template.format(name=name)


class OutboundAgent(MuftyKareBaseAgent):
    """
    Agent for agent-initiated outbound calls.
    Prompt selected at construction time based on call_type from userdata.
    """

    def __init__(
        self,
        call_type: str = CALL_TYPE_REMINDER,
        customer_context: dict | None = None,
    ) -> None:
        prompt = _PROMPT_MAP.get(call_type, OUTBOUND_REMINDER_PROMPT)
        tools = [reschedule_slot, get_bill]

        if call_type == CALL_TYPE_PROSPECTING:
            from prompts.shared import _IS_ENGLISH
            ctx = customer_context or {}
            prompt = prompt.format(
                opening_line=_build_prospecting_opener(ctx, _IS_ENGLISH),
                address=ctx.get("address") or ("your address" if _IS_ENGLISH else "మీ address"),
            )
            tools = [reschedule_slot, log_campaign_outcome]

        super().__init__(
            instructions=prompt,
            tools=tools,
        )
        self.call_type = call_type

    async def on_enter(self) -> None:
        """
        Outbound on_enter: speak the opening line immediately.
        The agent called the customer — start talking, don't wait.
        """
        logger.info(f"agent:outbound on_enter call_type={self.call_type}")
        # Generate opening — the prompt defines the exact opening line
        self.session.generate_reply(tool_choice="none")

    @function_tool
    async def to_booking(self, context: RunCtx) -> tuple:
        """
        Transfer to BookingAgent if user wants to reschedule.

        Call when:
        - User is not home and wants a different pickup time
        - User wants to change delivery slot
        - Any rescheduling request during outbound call

        Telugu triggers:
        - "Inkaa 2 hours wait chesandi"
        - "Repu raagalara?"
        - "Different time lo raandi"
        """
        logger.info("agent:outbound → booking (reschedule)")
        return await self._transfer_to_agent(AGENT_BOOKING, context)

    @function_tool
    async def to_complaint(self, context: RunCtx) -> tuple:
        """
        Transfer to ComplaintAgent if user raises a complaint on the outbound call.

        Call when user mentions any issue during the outbound call:
        - During pickup reminder: "actually last order lo problem undi"
        - During delivery call: "delivered clothes lo damage undi"

        Never ignore complaints raised during outbound calls.
        """
        logger.info("agent:outbound → complaint")
        return await self._transfer_to_agent(AGENT_COMPLAINT, context)

    @function_tool
    async def end_call_gracefully(self, context: RunCtx) -> None:
        """
        End the outbound call gracefully after goal is achieved.

        Call when:
        - Customer confirmed they are home (pickup/delivery calls)
        - Customer acknowledged payment reminder
        - Customer said thanks/bye
        - Goal of the outbound call is complete

        Always say a brief goodbye before ending.
        """
        logger.info("agent:outbound → end_call")
        userdata = context.userdata

        await self.session.say(
            "Dhanyavaadaalu! MuftyKare ni choose chessinanduku thanks. Have a great day!",
            allow_interruptions=False,
        )
        self.session.shutdown()

    @function_tool
    async def log_no_answer(self, context: RunCtx) -> str:
        """
        Log a missed outbound call when user doesn't answer.

        Call when:
        - User doesn't pick up after ringing
        - User disconnects without speaking
        - After silence timeout fires (user_away_timeout)
        """
        logger.info("agent:outbound → no_answer logged")
        context.userdata.outcome = OUTCOME_MISSED
        self.session.shutdown()
        return "Missed call logged."
