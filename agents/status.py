"""
agents/status.py — StatusAgent: order status, bill, delivery ETA.
"""
from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from agents.base import MuftyKareBaseAgent
from tools.status import (
    get_order_status,
)
from prompts.status import STATUS_PROMPT
from config.constants import (
    AGENT_GREETER, AGENT_BOOKING, AGENT_COMPLAINT,
    INTENT_STATUS, INTENT_BILLING,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


class StatusAgent(MuftyKareBaseAgent):
    """Handles order status, bill queries, delivery ETA, payment status."""

    def __init__(self) -> None:
        super().__init__(
            instructions=STATUS_PROMPT,
            tools=[
                get_order_status,
            ],
        )

    @function_tool
    async def to_greeter(self, context: RunCtx) -> tuple:
        """
        Return to GreeterAgent after status is provided.

        Call when:
        - Status/bill was provided and customer says "ok", "thanks", "sare"
        - Customer asks about something outside status (wants to book new pickup)
        - Customer satisfied and conversation is wrapping up

        Always ask "inka emi kavali?" before transferring back.
        """
        logger.info("agent:status → greeter")
        return await self._transfer_to_agent(AGENT_GREETER, context)

    @function_tool
    async def to_booking(self, context: RunCtx) -> tuple:
        """
        Transfer to BookingAgent after status check.

        Call when customer wants to book a new pickup after checking status.
        Also call when missed delivery needs rescheduling.

        Telugu triggers:
        - "Ok, new pickup book cheskovadam ki"
        - "Nenu intlo ledu, repu raagalara?" (missed delivery rescheduling)
        - "Ika new order book cheyyali"
        """
        logger.info("agent:status → booking")
        return await self._transfer_to_agent(AGENT_BOOKING, context)

    @function_tool
    async def to_complaint(self, context: RunCtx) -> tuple:
        """
        Transfer to ComplaintAgent — CRITICAL: most common mid-call pivot.

        Call IMMEDIATELY when customer raises ANY issue after hearing status:
        - Hears "delivered" → "Kaani shirt damage ayyindi"
        - Hears "cleaning" → "3 rojulu ayyindi inkaa raaledu enti?"
        - Hears bill → "Inta enta enti? Overcharged chesaaru"
        - Any frustration or complaint about service quality

        This is the most important transfer in the entire system.
        Do NOT ask questions — transfer immediately when complaint signal detected.
        """
        logger.info("agent:status → complaint (mid-call pivot)")
        return await self._transfer_to_agent(AGENT_COMPLAINT, context)

    @function_tool
    async def to_human(self, context: RunCtx) -> None:
        """
        Transfer to human manager for payment disputes or refund requests.

        Call when:
        - Customer demands refund: "refund kavali"
        - Customer disputes payment: "wrong amount charge chesaaru"
        - Customer asks to speak to person/manager
        - Any payment issue you cannot resolve

        Never promise refunds. Always escalate payment disputes.
        """
        logger.info("agent:status → warm_transfer")
        await self._warm_transfer(context)
