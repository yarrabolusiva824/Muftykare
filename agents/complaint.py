"""
agents/complaint.py — ComplaintAgent: handles complaints with empathy + severity triage.
"""
from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from agents.base import MuftyKareBaseAgent
from tools.complaint import log_complaint
from prompts.complaint import COMPLAINT_PROMPT
from config.constants import (
    AGENT_GREETER, AGENT_BOOKING,
    COMPLAINT_CRITICAL_KEYWORDS, COMPLAINT_MEDIUM_KEYWORDS,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


class ComplaintAgent(MuftyKareBaseAgent):
    """
    Handles all complaints with empathy-first approach.
    Triages severity: low → rewash, medium/critical → warm transfer.
    """

    def __init__(self) -> None:
        super().__init__(
            instructions=COMPLAINT_PROMPT,
            tools=[
                log_complaint,
            ],
        )

    @function_tool
    async def to_greeter(self, context: RunCtx) -> tuple:
        """
        Return to GreeterAgent after LOW severity complaint is logged and customer is satisfied.

        Call ONLY when:
        - Low severity complaint (stain/smell/button) was logged
        - Customer says "ok thanks" or is satisfied after you inform them the team will review it

        Do NOT call for medium/critical complaints — those go to warm_transfer.
        """
        logger.info("agent:complaint → greeter (low severity logged)")
        return await self._transfer_to_agent(AGENT_GREETER, context)

    @function_tool
    async def escalate_to_manager(self, context: RunCtx) -> None:
        """
        Escalate to human manager via warm transfer.

        Call for MEDIUM or CRITICAL severity complaints:
        - CRITICAL: damaged clothes, missing items, wrong clothes, color bleed, shrinkage
        - MEDIUM: rude delivery staff, significant delay (3+ days), payment dispute
        - ANY explicit manager request

        Always call log_complaint BEFORE calling this tool.
        Always say "hold lo undi" before initiating transfer (allow_interruptions=False).

        NEVER call for low severity — use to_greeter after rewash instead.
        """
        logger.info(
            "agent:complaint → warm_transfer",
            extra={
                "severity": context.userdata.complaint_severity,
                "type": context.userdata.complaint_type,
            },
        )
        await self._warm_transfer(context)
