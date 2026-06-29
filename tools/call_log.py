"""
tools/call_log.py — Call logging tools for MuftyKare voice agent.

Note: These are @function_tool wrappers around db.queries functions.
They exist so agents can trigger logging via GPT-4o tool calls if needed,
but the primary call logging happens directly in agent.py entrypoint
via ctx.add_shutdown_callback — not through GPT-4o tool calls.
"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext
from livekit.agents.llm import function_tool
from db.queries import log_call_start, log_call_end
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


@function_tool
async def log_call_start_tool(
    context: RunCtx,
) -> str:
    """
    Log the start of a call to voice_call_log.
    Called automatically in agent.py — not typically called by GPT-4o directly.
    """
    pool = context.userdata.db_pool
    ud = context.userdata

    if not ud.call_id:
        return "No call_id set in userdata."

    log_id = await log_call_start(
        pool,
        call_id=ud.call_id,
        caller_phone=ud.caller_phone,
        customer_id=ud.customer_id,
        direction=ud.call_direction,
        language=ud.language,
    )
    context.userdata.call_log_id = log_id
    return f"Call logged with ID {log_id}."


@function_tool
async def log_call_end_tool(
    context: RunCtx,
    outcome: Annotated[str, Field(description="Call outcome: 'booking_created', 'status_provided', 'escalated', 'rewash_created', 'no_action', 'missed', 'wrong_number'")],
) -> str:
    """
    Log the end of a call with outcome.
    Called automatically in agent.py shutdown callback — not typically by GPT-4o.
    """
    pool = context.userdata.db_pool
    ud = context.userdata

    if not ud.call_id:
        return "No call_id to log."

    from datetime import date
    transcript_path = f"logs/muftykare_{date.today().isoformat()}.log"

    await log_call_end(
        pool,
        call_id=ud.call_id,
        intent=ud.intent,
        order_id=ud.current_order_id,
        outcome=outcome,
        transcript_path=transcript_path,
    )

    context.userdata.outcome = outcome
    return f"Call end logged. Outcome: {outcome}."
