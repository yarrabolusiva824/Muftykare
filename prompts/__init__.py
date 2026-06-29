"""
prompts/__init__.py — Exports all system prompts for MuftyKare agents.
"""
from prompts.shared import (
    BUSINESS_RULES_BLOCK,
    VOICE_RULES_BLOCK,
    STATUS_RESPONSES_BLOCK,
)
from prompts.greeter import GREETER_PROMPT
from prompts.booking import BOOKING_PROMPT
from prompts.status import STATUS_PROMPT
from prompts.complaint import COMPLAINT_PROMPT
from prompts.outbound import (
    OUTBOUND_REMINDER_PROMPT,
    OUTBOUND_DELIVERY_PROMPT,
    OUTBOUND_PAYMENT_PROMPT,
)

__all__ = [
    "BUSINESS_RULES_BLOCK",
    "VOICE_RULES_BLOCK",
    "STATUS_RESPONSES_BLOCK",
    "GREETER_PROMPT",
    "BOOKING_PROMPT",
    "STATUS_PROMPT",
    "COMPLAINT_PROMPT",
    "OUTBOUND_REMINDER_PROMPT",
    "OUTBOUND_DELIVERY_PROMPT",
    "OUTBOUND_PAYMENT_PROMPT",
]
