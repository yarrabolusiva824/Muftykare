"""
agents/booking.py — BookingAgent: handles all pickup scheduling.
"""
from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from agents.base import MuftyKareBaseAgent
from tools.booking import (
    check_slot_availability,
    create_booking,
    reschedule_slot,
    cancel_booking,
)
from tools.customer import lookup_customer_by_number, save_new_customer
from tools.notification import send_sms_confirmation
from tools.pricing import get_all_prices
from prompts.booking import BOOKING_PROMPT
from config.constants import AGENT_GREETER, AGENT_COMPLAINT, INTENT_BOOKING
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


class BookingAgent(MuftyKareBaseAgent):
    """Handles pickup booking, rescheduling, and cancellation."""

    def __init__(self) -> None:
        super().__init__(
            instructions=BOOKING_PROMPT,
            tools=[
                check_slot_availability,
                create_booking,
                reschedule_slot,
                cancel_booking,
                send_sms_confirmation,
                get_all_prices,
                lookup_customer_by_number,
                save_new_customer,
            ],
        )

    @function_tool
    async def to_greeter(self, context: RunCtx) -> tuple:
        """
        Return to GreeterAgent after booking is complete or user changes topic.

        Call when:
        - Booking was successfully created and customer asks "inka emi?"
        - Customer says thanks/bye after booking
        - Customer suddenly asks about something unrelated (order status, etc.)
        - Customer says "never mind" or changes their mind entirely

        Do NOT call mid-booking — only after the task is complete or clearly abandoned.
        """
        logger.info("agent:booking → greeter")
        return await self._transfer_to_agent(AGENT_GREETER, context)

    @function_tool
    async def to_complaint(self, context: RunCtx) -> tuple:
        """
        Transfer to ComplaintAgent if complaint surfaces during booking conversation.

        Call when customer mentions damage, missing items, or quality issues
        while you are in the middle of a booking conversation.

        Example: Customer says "Actually, last order lo shirt damage ayyindi"
        while you were asking about pickup slot.

        Drop the booking flow immediately and transfer.
        """
        logger.info("agent:booking → complaint")
        return await self._transfer_to_agent(AGENT_COMPLAINT, context)

    @function_tool
    async def to_human(self, context: RunCtx) -> None:
        """
        Transfer to human manager.

        Call when:
        - Customer explicitly asks to speak to a person/manager
        - Customer asks for bulk/hotel/corporate booking (outside standard flow)
        - Any situation you cannot handle
        """
        logger.info("agent:booking → warm_transfer")
        await self._warm_transfer(context)
