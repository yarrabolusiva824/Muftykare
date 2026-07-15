"""
agent.py — MuftyKare Voice Agent Entrypoint (LiveKit Agents v1.6.x)

Run commands:
    python agent.py dev                    # dev mode, hot-reload, GreeterAgent
    python agent.py dev                    # set TEST_AGENT=booking in .env for BookingAgent
    python agent.py start                  # production

Agent selection (dev only — set in .env):
    TEST_AGENT=greeter    (default)
    TEST_AGENT=booking
    TEST_AGENT=status
    TEST_AGENT=complaint
    TEST_AGENT=outbound
"""

# ── Logging FIRST — before any imports that might log ──────────────────────
from logger import setup_logging, get_logger
setup_logging()
logger = get_logger(__name__)

# ── Standard imports ────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv()

# ── LiveKit imports ─────────────────────────────────────────────────────────
from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    BackgroundAudioPlayer,
    AudioConfig,
    BuiltinAudioClip,
    JobContext,
    cli,
)
from livekit.plugins import sarvam
from livekit.plugins import openai as lk_openai
from livekit.plugins import noise_cancellation
from livekit.agents.voice import room_io
# ── MuftyKare imports ───────────────────────────────────────────────────────
from userdata import MuftyKareUserData
from db.connection import create_pool, close_pool
from db.queries import log_call_start, log_call_end
from audio_cache import make_ambient_generator
from agents import (
    GreeterAgent,
    BookingAgent,
    StatusAgent,
    ComplaintAgent,
    OutboundAgent,
    build_agent_registry,
)
from config.constants import (
    DIRECTION_INBOUND,
    SIP_ATTR_PHONE,
    SIP_ATTR_CALL_ID,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    SARVAM_TTS_SPEAKER,
    SARVAM_LANGUAGE,
    SARVAM_ENDPOINTING_MS,
    LLM_MODEL,
    USER_AWAY_TIMEOUT_SECS,
    CALL_TYPE_REMINDER,
)

# ── Agent map for TEST_AGENT selection ──────────────────────────────────────
_AGENT_MAP = {
    "greeter":   GreeterAgent,
    "booking":   BookingAgent,
    "status":    StatusAgent,
    "complaint": ComplaintAgent,
    "outbound":  OutboundAgent,
}

# ── AgentServer ─────────────────────────────────────────────────────────────
server = AgentServer()


@server.rtc_session(agent_name="muftykare-agent")
async def entrypoint(ctx: JobContext) -> None:
    """
    Entrypoint for every MuftyKare voice agent session.

    Flow:
    1. Create DB pool
    2. Build MuftyKareUserData with pool + agent registry
    3. Extract SIP phone number (production) or use TEST_AGENT (dev)
    4. Silent customer lookup before first word
    5. Start AgentSession with STT + LLM + TTS
    6. Register shutdown callback to close pool + log call end
    """
    logger.info("entrypoint called", extra={"room": ctx.room.name})

    # ── 1. Create DB pool ───────────────────────────────────────────────────
    db_pool = await create_pool()

    # ── 2. Determine starting agent ─────────────────────────────────────────
    # Dev: read TEST_AGENT from .env to test individual agents
    # Production: always GreeterAgent
    agent_name = os.getenv("TEST_AGENT", "greeter").lower().strip()
    AgentClass = _AGENT_MAP.get(agent_name, GreeterAgent)

    # Log which agent is starting
    logger.info(
        "starting agent",
        extra={"agent": AgentClass.__name__, "room": ctx.room.name},
    )
    print(f"\n>>> MuftyKare: {AgentClass.__name__} <<<\n")

    # ── 3. Extract SIP phone number (production inbound calls) ──────────────
    # In dev/Agent Console mode: no SIP participant, phone stays None
    # In production: wait for SIP participant to join, extract phone
    caller_phone = None
    call_id = ctx.room.name

    participant = await ctx.wait_for_participant()

    if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        caller_phone = participant.attributes.get(SIP_ATTR_PHONE, "")
        call_id = participant.attributes.get(SIP_ATTR_CALL_ID, ctx.room.name)
        logger.info(
            "SIP participant joined",
            extra={
                "phone": f"****{caller_phone[-4:]}" if caller_phone else "unknown",
                "call_id": call_id,
            },
        )

    # ── 4. Silent customer lookup before agent speaks ───────────────────────
    customer = None
    if caller_phone:
        from db.queries import fetch_customer_by_phone
        customer = await fetch_customer_by_phone(db_pool, caller_phone)

    # ── 5. Build MuftyKareUserData ──────────────────────────────────────────
    userdata = MuftyKareUserData(
        db_pool=db_pool,
        call_id=call_id,
        call_direction=DIRECTION_INBOUND,
        caller_phone=caller_phone,
        customer_id=customer["id"] if customer else None,
        customer_name=customer["name"] if customer else None,
        customer_address=customer.get("address") if customer else None,
        language=SARVAM_LANGUAGE,
    )

    # Pre-populate agents registry
    userdata.agents = build_agent_registry()

    logger.info(
        "userdata built",
        extra={
            "customer_id": userdata.customer_id,
            "customer_name": userdata.customer_name,
            "caller_known": userdata.is_identified,
        },
    )

    # ── 6. Log call start ───────────────────────────────────────────────────
    try:
        log_id = await log_call_start(
            db_pool,
            call_id=call_id,
            caller_phone=caller_phone,
            customer_id=userdata.customer_id,
            direction=DIRECTION_INBOUND,
            language=SARVAM_LANGUAGE,
        )
        userdata.call_log_id = log_id
    except Exception as e:
        # Non-fatal — don't crash the call if logging fails
        logger.warning("log_call_start failed", extra={"error": str(e)})

    # ── 7. Build AgentSession ───────────────────────────────────────────────
    session = AgentSession[MuftyKareUserData](
        userdata=userdata,

        # STT — Sarvam Saaras v3, Telugu primary
        # flush_signal=True is MANDATORY for Sarvam turn detection
        # Do NOT add vad= — Sarvam handles VAD internally
        stt=sarvam.STT(
            model=SARVAM_STT_MODEL,
            language=SARVAM_LANGUAGE,
            mode="transcribe",
            flush_signal=True,
        ),

        # LLM — GPT-4o, parallel_tool_calls=False for voice reliability
        llm=lk_openai.LLM(
            model=LLM_MODEL,
            parallel_tool_calls=False,
        ),

        # TTS — Sarvam Bulbul v3, Telugu female voice
        # TEMP: swapped for OpenAI TTS for testing — restore this once testing is done
        tts=sarvam.TTS(
            target_language_code=SARVAM_LANGUAGE,
            model=SARVAM_TTS_MODEL,
            speaker=SARVAM_TTS_SPEAKER,
        ),

        # TTS — OpenAI (testing only)
        # tts=lk_openai.TTS(
        #     model="tts-1",
        #     voice="nova",
        # ),

        # Turn detection — Sarvam handles VAD internally via flush_signal
        # Use top-level AgentSession kwargs (not a dict)
        turn_detection="stt",
        min_endpointing_delay=SARVAM_ENDPOINTING_MS,

        # Silence timeout — fires user_state_changed after N seconds of silence
        user_away_timeout=USER_AWAY_TIMEOUT_SECS,
    )

    # ── 8. Transcript logging ───────────────────────────────────────────────
    @session.on("user_input_transcribed")
    def on_transcript(event):
        if event.is_final:
            logger.info(
                "transcript",
                extra={"text": event.transcript, "room": ctx.room.name},
            )
            print(f"\n[TRANSCRIPT] {event.transcript}\n")
        else:
            logger.debug(
                "transcript (partial)",
                extra={"text": event.transcript},
            )

    # ── 9. Shutdown callback ────────────────────────────────────────────────
    async def on_shutdown() -> None:
        logger.info("session ending", extra={"room": ctx.room.name})
        try:
            if userdata.call_id:
                await log_call_end(
                    db_pool,
                    call_id=userdata.call_id,
                    intent=userdata.intent,
                    order_id=userdata.current_order_id,
                    outcome=userdata.outcome,
                    transcript_path=None,
                )
        except Exception as e:
            logger.warning("log_call_end failed", extra={"error": str(e)})
        finally:
            await background_audio.aclose()
            await close_pool(db_pool)

    ctx.add_shutdown_callback(on_shutdown)

    # ── 10. Background audio — office ambience for entire call ──────────────
    # ── 10. Background audio — decode once, create in-memory generator ──────────
    _ambience_path = BuiltinAudioClip.OFFICE_AMBIENCE.path()
    _ambient_gen = await make_ambient_generator(_ambience_path)
    background_audio = BackgroundAudioPlayer(ambient_sound=AudioConfig(_ambient_gen, volume=2.5),)

    # ── 11. Start session ───────────────────────────────────────────────────
    starting_agent = AgentClass()
    logger.info(
        "session starting",
        extra={"agent": AgentClass.__name__, "room": ctx.room.name},
    )

    await session.start(agent=starting_agent, room=ctx.room, room_input_options=room_io.RoomInputOptions(
        noise_cancellation=noise_cancellation.BVCTelephony(),
    ),)
    session.output.set_audio_enabled(True)
    # await warm_ambience_cache(BuiltinAudioClip.OFFICE_AMBIENCE.path())
    await background_audio.start(room=ctx.room, agent_session=session)

    logger.info(
        "session started",
        extra={"agent": AgentClass.__name__, "room": ctx.room.name},
    )


if __name__ == "__main__":
    cli.run_app(server)
