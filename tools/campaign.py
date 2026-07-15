"""
tools/campaign.py — Outbound prospecting campaign tools for MuftyKare voice agent.

Used by: OutboundAgent (call_type=CALL_TYPE_PROSPECTING)
"""
from __future__ import annotations

from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from config.constants import (
    OUTCOME_BOOKED,
    OUTCOME_INTERESTED,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_BUSY,
    OUTCOME_EXISTING_QUERY,
    OUTCOME_MISSED,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

VALID_CAMPAIGN_OUTCOMES = {
    OUTCOME_BOOKED,
    OUTCOME_INTERESTED,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_BUSY,
    OUTCOME_EXISTING_QUERY,
    OUTCOME_MISSED,
}


@function_tool
async def log_campaign_outcome(context: RunCtx, outcome: str, notes: str = "") -> str:
    """
    Log the outcome of this outbound prospecting call. Must be called before
    the call ends — via end_call_gracefully or before session shutdown.

    outcome: one of — booked, interested, not_interested, busy, missed, existing_query
    notes: optional short note about what happened
    """
    if outcome not in VALID_CAMPAIGN_OUTCOMES:
        raise ToolError(
            f"Invalid outcome '{outcome}'. Use one of: {', '.join(sorted(VALID_CAMPAIGN_OUTCOMES))}"
        )

    context.userdata.outcome = outcome
    logger.info(
        "campaign outcome logged",
        extra={
            "outcome": outcome,
            "customer_id": context.userdata.customer_id,
            "notes": notes or None,
        },
    )
    return f"Outcome '{outcome}' logged."
