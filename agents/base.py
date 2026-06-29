"""
agents/base.py — BaseAgent for all MuftyKare agents.

All 5 agents inherit from MuftyKareBaseAgent.
Provides:
- on_enter: carries last 6 messages from prev_agent + injects userdata state
- _transfer_to_agent: standard handoff to named agent
- _warm_transfer: escalation to human manager via WarmTransferTask
"""
from __future__ import annotations

from livekit.agents import Agent, RunContext, ToolError
from livekit.agents.beta.workflows import WarmTransferTask
from config.settings import MANAGER_PHONE, SIP_OUTBOUND_TRUNK_ID
from config.constants import CHAT_CTX_MAX_ITEMS
from userdata import MuftyKareUserData
from logger import get_logger

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

# Summary shown to human manager when warm transfer connects
WARM_TRANSFER_SUMMARY = """
Introduce yourself as the MuftyKare AI assistant handing over to a human agent.
Summarize:
- WHO is calling (customer name, phone last 4 digits)
- WHY they called (original intent)
- WHAT happened in the conversation (key facts, complaint type if any)
- WHY escalation is needed
Keep summary under 150 words, spoken naturally in English.
"""


class MuftyKareBaseAgent(Agent):
    """
    Base class for all MuftyKare agents.
    Implements the restaurant_agent.py pattern for chat context carry-over
    and userdata state injection on every agent transition.
    """

    async def on_enter(self) -> None:
        """
        Called when this agent becomes the active agent.

        1. Carries last 6 messages from previous agent (so context isn't lost)
        2. Injects current userdata state as a system message
        3. Generates opening reply without calling tools (tool_choice="none")
        """
        agent_name = self.__class__.__name__
        logger.info(f"agent:on_enter {agent_name}")

        userdata: MuftyKareUserData = self.session.userdata
        chat_ctx = self.chat_ctx.copy()

        # Carry last N messages from previous agent (restaurant_agent.py pattern)
        if isinstance(userdata.prev_agent, Agent):
            truncated = userdata.prev_agent.chat_ctx.copy(
                exclude_instructions=True,
                exclude_function_call=False,
                exclude_handoff=True,
                exclude_config_update=True,
            ).truncate(max_items=CHAT_CTX_MAX_ITEMS)

            existing_ids = {item.id for item in chat_ctx.items}
            items_copy = [
                item for item in truncated.items
                if item.id not in existing_ids
            ]
            chat_ctx.items.extend(items_copy)

        # Inject current session state — agent knows who the customer is
        chat_ctx.add_message(
            role="system",
            content=(
                f"You are {agent_name}. "
                f"Current session state:\n{userdata.summarize()}"
            ),
        )
        await self.update_chat_ctx(chat_ctx)

        # Generate opening reply and allow tool calls immediately
        self.session.generate_reply()

    async def _transfer_to_agent(
        self,
        name: str,
        context: RunCtx,
    ) -> tuple[Agent, str]:
        """
        Standard handoff to a named agent.
        Sets prev_agent so the next agent's on_enter can carry chat history.
        """
        userdata = context.userdata
        current = context.session.current_agent
        next_agent = userdata.agents.get(name)

        if next_agent is None:
            logger.error(f"agent:transfer failed — '{name}' not in agents dict")
            raise ToolError(f"Agent '{name}' not available.")

        userdata.prev_agent = current
        logger.info(
            "agent:handoff",
            extra={
                "from": type(current).__name__,
                "to": name,
                "customer_id": userdata.customer_id,
                "intent": userdata.intent,
            },
        )
        return next_agent, f"Transferring to {name}."

    async def _warm_transfer(self, context: RunCtx) -> None:
        """
        Escalate to human manager via WarmTransferTask.
        Used for critical complaints, explicit human requests, payment disputes.

        Announces hold to customer, initiates transfer, announces connection,
        then shuts down the AI session.
        """
        userdata = context.userdata
        logger.info(
            "agent:warm_transfer initiated",
            extra={
                "customer_id": userdata.customer_id,
                "intent": userdata.intent,
                "complaint_severity": userdata.complaint_severity,
            },
        )

        # Announce hold — must not be interrupted
        await self.session.say(
            "ఒక్క నిమిషం hold లో ఉండండి, మా manager మీతో మాట్లాడతారు.",
            allow_interruptions=False,
        )

        if not SIP_OUTBOUND_TRUNK_ID or not MANAGER_PHONE:
            logger.warning(
                "agent:warm_transfer — SIP_OUTBOUND_TRUNK_ID or MANAGER_PHONE not set. "
                "Cannot initiate warm transfer in dev mode."
            )
            await self.session.say(
                "క్షమించండి, ప్రస్తుతం మా manager available గా లేరు. "
                f"దయచేసి {MANAGER_PHONE or '7075232425'} కి direct గా call చేయండి.",
            )
            return

        try:
            result = await WarmTransferTask(
                sip_call_to=MANAGER_PHONE,
                sip_trunk_id=SIP_OUTBOUND_TRUNK_ID,
                chat_ctx=self.chat_ctx,
                extra_instructions=WARM_TRANSFER_SUMMARY,
            )
            logger.info(
                "agent:warm_transfer connected",
                extra={"human_agent": result.human_agent_identity},
            )
            await self.session.say(
                "మీరు ఇప్పుడు మా manager తో connected అయ్యారు.",
                allow_interruptions=False,
            )
        except ToolError as e:
            logger.error("agent:warm_transfer ToolError", extra={"error": str(e)})
            await self.session.say(
                f"క్షమించండి, transfer fail అయింది. దయచేసి {MANAGER_PHONE} కి call చేయండి."
            )
        except Exception as e:
            logger.exception("agent:warm_transfer unexpected error")
            await self.session.say(
                f"క్షమించండి, technical issue వచ్చింది. దయచేసి {MANAGER_PHONE} కి call చేయండి."
            )
        finally:
            self.session.shutdown()
