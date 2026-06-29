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
from prompts.outbound import (
    OUTBOUND_REMINDER_PROMPT,
    OUTBOUND_DELIVERY_PROMPT,
    OUTBOUND_PAYMENT_PROMPT,
)
from config.constants import (
    AGENT_BOOKING, AGENT_COMPLAINT,
    CALL_TYPE_REMINDER, CALL_TYPE_DELIVERY, CALL_TYPE_PAYMENT,
    OUTCOME_MISSED,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

# Prompt map by call type
_PROMPT_MAP = {
    CALL_TYPE_REMINDER: OUTBOUND_REMINDER_PROMPT,
    CALL_TYPE_DELIVERY: OUTBOUND_DELIVERY_PROMPT,
    CALL_TYPE_PAYMENT:  OUTBOUND_PAYMENT_PROMPT,
}


class OutboundAgent(MuftyKareBaseAgent):
    """
    Agent for agent-initiated outbound calls.
    Prompt selected at construction time based on call_type from userdata.
    """

    def __init__(self, call_type: str = CALL_TYPE_REMINDER) -> None:
        prompt = _PROMPT_MAP.get(call_type, OUTBOUND_REMINDER_PROMPT)
        super().__init__(
            instructions=prompt,
            tools=[
                reschedule_slot,
                get_bill,
            ],
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
