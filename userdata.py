"""
userdata.py — MuftyKareUserData: shared state for the entire call session.

Passed as AgentSession[MuftyKareUserData](userdata=userdata, ...).
Every agent and tool accesses this via context.userdata.

Design rules:
- Add fields here when state needs to survive a handoff between agents
- Never use global variables — always use userdata
- summarize() is injected into each agent's system message on on_enter()
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg
    from livekit.agents import Agent


@dataclass
class MuftyKareUserData:
    """Shared state for the entire MuftyKare voice call session."""

    # ── Infrastructure ────────────────────────────────────────────────────
    db_pool: Any = None                     # asyncpg.Pool — injected at session start

    # ── Call metadata ─────────────────────────────────────────────────────
    call_id: str | None = None              # sip.callID or room name
    call_direction: str = "inbound"         # "inbound" | "outbound"
    call_type: str | None = None            # outbound only: "reminder"|"delivery"|"payment"
    call_log_id: int | None = None          # voice_call_log.id for this call
    language: str = "te-IN"                 # detected language (updates if user switches)

    # ── Caller identity ───────────────────────────────────────────────────
    caller_phone: str | None = None         # raw from sip.phoneNumber e.g. "+919876543210"
    customer_id: int | None = None          # customer.id from DB lookup
    customer_name: str | None = None        # customer.name from DB lookup
    customer_address: str | None = None     # customer.address (used for booking)
    is_new_customer: bool = False           # True if caller not found in DB

    # ── Current session intent ────────────────────────────────────────────
    intent: str | None = None               # filled when GreeterAgent classifies
    outcome: str | None = None              # filled at call end before log_call_end

    # ── Booking context (filled by BookingAgent) ──────────────────────────
    service_type: str | None = None         # "WASH_FOLD"|"DRY_CLEAN"|"EXPRESS"|"SHOE_CLEAN"
    pickup_address: str | None = None       # address for this specific booking
    pickup_slot_date: str | None = None     # "YYYY-MM-DD"
    pickup_slot_name: str | None = None     # "morning"|"afternoon"|"evening"

    # ── Order context (filled by StatusAgent or after booking) ────────────
    current_order_id: int | None = None     # most recently referenced order
    order_status: str | None = None         # "cleaning"|"ready"|"delivered"

    # ── Complaint context (filled by ComplaintAgent) ───────────────────────
    complaint_type: str | None = None       # "damaged"|"missing"|"stain"|"late"|"rude"
    complaint_severity: str | None = None   # "low"|"medium"|"critical"

    # ── Multi-agent routing (restaurant_agent.py pattern) ─────────────────
    agents: dict[str, "Agent"] = field(default_factory=dict)
    prev_agent: "Agent | None" = None

    def summarize(self) -> str:
        """
        Returns YAML summary of current session state.
        Injected into each agent's system message on on_enter()
        so the new agent has full context without asking the user to repeat.

        Uses YAML not JSON — LLMs parse YAML more reliably (per restaurant_agent.py).
        """
        data = {
            "call": {
                "direction": self.call_direction,
                "call_type": self.call_type,
                "language": self.language,
            },
            "customer": {
                "phone_known": self.caller_phone is not None,
                "id": self.customer_id,
                "name": self.customer_name or "unknown",
                "address": self.customer_address or "unknown",
                "is_new": self.is_new_customer,
            },
            "session": {
                "intent": self.intent or "unknown",
                "outcome": self.outcome or "pending",
            },
            "booking": {
                "service_type": self.service_type,
                "pickup_address": self.pickup_address,
                "slot_date": self.pickup_slot_date,
                "slot_name": self.pickup_slot_name,
            } if any([self.service_type, self.pickup_slot_name]) else None,
            "order": {
                "order_id": self.current_order_id,
                "status": self.order_status,
            } if self.current_order_id else None,
            "complaint": {
                "type": self.complaint_type,
                "severity": self.complaint_severity,
            } if self.complaint_type else None,
        }
        # Remove None sections
        data = {k: v for k, v in data.items() if v is not None}
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)

    @property
    def is_identified(self) -> bool:
        """True if the caller has been identified in DB (customer_id is set)."""
        return self.customer_id is not None

    @property
    def masked_phone(self) -> str:
        """Phone number safe to log — last 4 digits only."""
        if not self.caller_phone:
            return "unknown"
        return f"****{self.caller_phone[-4:]}"
