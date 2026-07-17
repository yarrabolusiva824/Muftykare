"""
agents/greeter.py — GreeterAgent: entry point for every call.

Responsibilities:
- Silently identify caller via lookup_caller (before first word)
- Greet by name if returning customer
- Classify intent and transfer to right specialist agent
- Handle general queries (timings, location, pricing) without transfer
"""
from __future__ import annotations

from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from agents.base import MuftyKareBaseAgent
from tools.customer import lookup_caller, lookup_customer_by_number, save_new_customer
from tools.pricing import get_all_prices
from tools.call_log import log_call_start_tool
from prompts.greeter import GREETER_PROMPT
from prompts.shared import _IS_ENGLISH
from config.constants import (
    AGENT_BOOKING, AGENT_STATUS, AGENT_COMPLAINT,
    INTENT_BOOKING, INTENT_STATUS, INTENT_BILLING, INTENT_COMPLAINT,
)
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]


class GreeterAgent(MuftyKareBaseAgent):
    """
    Entry point for every inbound call.
    Extends BaseAgent — inherits on_enter chat ctx carry and _transfer_to_agent.
    """

    def __init__(self) -> None:
        super().__init__(
            instructions=GREETER_PROMPT,
            tools=[
                lookup_caller,              # reads phone from userdata — no arg for GPT-4o
                lookup_customer_by_number,  # for when customer speaks their number
                save_new_customer,
                get_all_prices,
                log_call_start_tool,
            ],
        )

    async def on_enter(self) -> None:
        """
        Override: GreeterAgent speaks first without generating a reply.
        Greeting is handled by the agent's instructions + generate_reply.
        """
        agent_name = self.__class__.__name__
        logger.info(f"agent:on_enter {agent_name}")

        from livekit.agents import Agent
        userdata: MuftyKareUserData = self.session.userdata

        # Only carry chat history if coming from another agent (not first entry)
        if userdata.prev_agent is not None and isinstance(userdata.prev_agent, Agent):
            print("Coming from another agent")
            print(userdata.prev_agent.chat_ctx.items)
            chat_ctx = self.chat_ctx.copy()
            from config.constants import CHAT_CTX_MAX_ITEMS
            truncated = userdata.prev_agent.chat_ctx.copy(
                exclude_instructions=True,
                exclude_function_call=False,
                exclude_handoff=True,
                exclude_config_update=True,
            ).truncate(max_items=CHAT_CTX_MAX_ITEMS)
            existing_ids = {item.id for item in chat_ctx.items}
            items_copy = [i for i in truncated.items if i.id not in existing_ids]
            chat_ctx.items.extend(items_copy)
            chat_ctx.add_message(
                role="system",
                content=f"Returning from another agent. State: {userdata.summarize()}",
            )
            await self.update_chat_ctx(chat_ctx)
            self.session.generate_reply(tool_choice="none")
        else:
            # First entry — inject session state so LLM knows caller_phone for silent lookup
            print("First entry")
            print(userdata.summarize())
            chat_ctx = self.chat_ctx.copy()
            chat_ctx.add_message(
                role="system",
                content=(
                    f"You are {agent_name}. "
                    f"Current session state:\n{userdata.summarize()}"
                ),
            )
            await self.update_chat_ctx(chat_ctx)
            self.session.generate_reply()

    # ── Transfer tools (handoff conditions) ──────────────────────────────

    # TEMP: agent switching disabled for greeter-only testing. Re-enable by
    # un-commenting the @function_tool methods below.
    #
    # @function_tool
    # async def to_booking(self, context: RunCtx) -> tuple:
    #     """
    #     Transfer to BookingAgent when user wants to book, reschedule, or cancel a pickup.
    #
    #     Call when user expresses ANY of these:
    #     - Wants a pickup: "pickup kavali", "laundry teeskovadam", "book cheskovadam"
    #     - Mentions a service: "dry cleaning kavali", "express service", "shoe cleaning"
    #     - Wants to reschedule: "slot change", "different time", "repu raakandi"
    #     - Wants to cancel: "cancel chesandi", "inkaa raakandi"
    #     - Any scheduling or appointment-related request
    #
    #     Telugu triggers: "pickup", "babbulu teeskovadam", "wash", "dry clean",
    #     "express", "slot", "book", "schedule", "cancel pickup"
    #     """
    #     logger.info("agent:greeter → booking")
    #     context.userdata.intent = INTENT_BOOKING
    #     return await self._transfer_to_agent(AGENT_BOOKING, context)
    #
    # @function_tool
    # async def to_status(self, context: RunCtx) -> tuple:
    #     """
    #     Transfer to StatusAgent when user wants to know about their order.
    #
    #     Call when user asks about:
    #     - Order location: "babbulu ekkada", "order ekkada undi"
    #     - Delivery timing: "eppudu vastaayi", "delivery eppudu"
    #     - Order readiness: "ready ayyindaa", "complete ayyindaa"
    #     - Bill/payment: "bill enta", "enta pay cheyyali", "payment chesaanu"
    #     - Order status: "status enti", "order status"
    #
    #     IMPORTANT: If customer_id is NOT known yet, ask for phone number first,
    #     call lookup_customer_by_number (NOT lookup_caller), THEN call this transfer tool.
    #     Do NOT transfer before customer is identified.
    #
    #     Telugu triggers: "babbulu", "order", "bill", "payment", "status",
    #     "delivery", "ready", "enta", "ekkada"
    #     """
    #     userdata = context.userdata
    #
    #     # Guard — must know who customer is
    #     if not userdata.customer_id:
    #         if _IS_ENGLISH:
    #             return "Could you share your phone number? I'll check your account and give you the status."
    #         return "మీ phone number చెప్పగలరా? మీ account check చేసి status చెప్తాను."
    #
    #     logger.info("agent:greeter → status")
    #     context.userdata.intent = INTENT_STATUS
    #     return await self._transfer_to_agent(AGENT_STATUS, context)
    #
    # @function_tool
    # async def to_complaint(self, context: RunCtx) -> tuple:
    #     """
    #     Transfer to ComplaintAgent when user has ANY complaint or quality issue.
    #
    #     Call IMMEDIATELY when user mentions:
    #     - Damage: "damage ayyindi", "torn", "fabric ruined"
    #     - Missing: "piece ledu", "missing", "oka shirt raaledu"
    #     - Wrong clothes: "wrong clothes", "veere vallu babbulu"
    #     - Color issues: "colour poyyindi", "color bleed"
    #     - Shrinkage: "shrink ayyindi", "size reduced"
    #     - Quality: "stain poyindi kaadu", "smell undi", "button ledu"
    #     - Delay frustration: "3 rojulu ayyindi", "chaaala late"
    #     - Rude staff: "rude ga matladaadu"
    #     - ANY expression of frustration about service quality
    #
    #     Do NOT investigate or ask questions — transfer immediately.
    #     Do NOT attempt to resolve — ComplaintAgent handles that.
    #
    #     Telugu triggers: "damage", "missing", "stain", "colour", "wrong",
    #     "shrink", "smell", "button", "rude", "late", "problem", "complaint"
    #     """
    #     logger.info("agent:greeter → complaint")
    #     context.userdata.intent = INTENT_COMPLAINT
    #     return await self._transfer_to_agent(AGENT_COMPLAINT, context)

    @function_tool
    async def to_human(self, context: RunCtx) -> None:
        """
        Initiate warm transfer to human manager.

        Call IMMEDIATELY when user:
        - Explicitly asks for a person: "person tho matladali", "human agent kavali"
        - Asks for manager: "manager kavali", "manager tho matladali"
        - Refuses AI: "AI tho kaadu", "robot tho kaadu"
        - Says anything like "real person", "supervisor"

        Do NOT ask why. Do NOT delay. Transfer immediately.
        User's wish to speak to a human must ALWAYS be respected without question.
        """
        logger.info("agent:greeter → warm_transfer (human request)")
        await self._warm_transfer(context)
