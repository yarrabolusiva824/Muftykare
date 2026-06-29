"""
tools/complaint.py — Complaint handling tools for MuftyKare voice agent.

Used by: ComplaintAgent
"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from db.queries import insert_complaint
from config.constants import OUTCOME_ESCALATED
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


@function_tool
async def log_complaint(
    context: RunCtx,
    complaint_type: Annotated[str, Field(description="Type: 'damaged', 'missing', 'stain', 'color_bleed', 'shrinkage', 'late_delivery', 'rude_staff', 'wrong_clothes', 'smell', 'button_missing', 'other'")],
    description: Annotated[str, Field(description="Brief description of the complaint in English. Include what the customer said.")],
    severity: Annotated[str, Field(description="Severity level: 'low' (stain/smell/button), 'medium' (late/rude), 'critical' (damaged/missing/wrong/color_bleed)")],
) -> str:
    """
    Log a customer complaint to the database before escalation or resolution.

    Call this for EVERY complaint, regardless of severity, BEFORE taking action.
    Logging must happen before warm transfer.

    Severity guide:
    - critical: "damage అయింది", "missing", "wrong clothes", "colour poyyindi", "shrink"
      → Always followed by warm transfer to manager
    - medium: "rude", "3 days delay", "late delivery", payment disputes
      → Log then escalate to manager
    - low: stain not removed, smell remaining, button missing
      → Log and inform customer that the team will review and contact them.

    Returns:
        Complaint ID confirming it was logged.
    """
    logger.info(
        "tool:log_complaint called",
        extra={
            "type": complaint_type,
            "severity": severity,
            "customer_id": context.userdata.customer_id,
        },
    )
    pool = context.userdata.db_pool

    if not context.userdata.customer_id:
        return "Customer not identified. Cannot log complaint without customer ID."

    try:
        complaint_id = await insert_complaint(
            pool,
            customer_id=context.userdata.customer_id,
            order_id=context.userdata.current_order_id,
            complaint_type=complaint_type,
            description=description,
            severity=severity,
        )
    except Exception as e:
        logger.error("tool:log_complaint db error", extra={"error": str(e)})
        raise ToolError("Failed to log complaint") from e

    context.userdata.complaint_type = complaint_type
    context.userdata.complaint_severity = severity
    
    if severity in ("medium", "critical"):
        context.userdata.outcome = OUTCOME_ESCALATED

    logger.info("tool:log_complaint saved", extra={"complaint_id": complaint_id, "severity": severity})
    return (
        f"Complaint logged (ID: {complaint_id}). "
        f"Type: {complaint_type}. Severity: {severity}. "
        f"{'Escalating to manager.' if severity in ('medium', 'critical') else 'Logged for team review.'}"
    )


