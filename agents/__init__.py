"""
agents/__init__.py — Exports all MuftyKare agent classes + factory function.
"""
from agents.base import MuftyKareBaseAgent
from agents.greeter import GreeterAgent
from agents.booking import BookingAgent
from agents.status import StatusAgent
from agents.complaint import ComplaintAgent
from agents.outbound import OutboundAgent
from config.constants import (
    AGENT_GREETER, AGENT_BOOKING, AGENT_STATUS, AGENT_COMPLAINT,
    CALL_TYPE_REMINDER,
)


def build_agent_registry(call_type: str = CALL_TYPE_REMINDER) -> dict:
    """
    Pre-instantiate all agents and return a dict for userdata.agents.

    Called in agent.py entrypoint before session.start().
    All agents are created once per call and reused across handoffs.

    Usage:
        userdata.agents = build_agent_registry(call_type=userdata.call_type or CALL_TYPE_REMINDER)
    """
    return {
        AGENT_GREETER:   GreeterAgent(),
        AGENT_BOOKING:   BookingAgent(),
        AGENT_STATUS:    StatusAgent(),
        AGENT_COMPLAINT: ComplaintAgent(),
        "outbound":      OutboundAgent(call_type=call_type),
    }


__all__ = [
    "MuftyKareBaseAgent",
    "GreeterAgent",
    "BookingAgent",
    "StatusAgent",
    "ComplaintAgent",
    "OutboundAgent",
    "build_agent_registry",
]
