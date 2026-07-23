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
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()
from livekit.plugins import deepgram, cartesia
# ── LiveKit imports ─────────────────────────────────────────────────────────
from livekit import rtc
from livekit import api as lkapi
from livekit.agents import (
    AgentServer,
    AgentSession,
    BackgroundAudioPlayer,
    AudioConfig,
    BuiltinAudioClip,
    JobContext,
    JobProcess,
    inference,
    cli,
)
from livekit.agents import WorkerOptions, cli
from livekit.plugins import sarvam
from livekit.plugins.sarvam import STT as SarvamSTT, TTS as SarvamTTS
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
    DIRECTION_OUTBOUND,
    SIP_ATTR_PHONE,
    SIP_ATTR_CALL_ID,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    SARVAM_TTS_SPEAKER,
    SARVAM_LANGUAGE,
    LLM_MODEL,
    USER_AWAY_TIMEOUT_SECS,
    CALL_TYPE_REMINDER,
    CALL_TYPE_PROSPECTING,
    AGENT_OUTBOUND,
)
from livekit.plugins import google as lk_google
# ── Agent map for TEST_AGENT selection ──────────────────────────────────────
_AGENT_MAP = {
    "greeter":   GreeterAgent,
    "booking":   BookingAgent,
    "status":    StatusAgent,
    "complaint": ComplaintAgent,
    "outbound":  OutboundAgent,
}

# ── Module-level pre-warm cache ─────────────────────────────────────────────
_ambient_gen_cache: object | None = None

async def start_call_recording(room_name: str, call_id: str) -> str | None:
    """Start LiveKit Egress recording to local MinIO. Returns egress_id or None on failure."""
    try:
        lk = lkapi.LiveKitAPI()
        req = lkapi.RoomCompositeEgressRequest(
            room_name=room_name,
            audio_only=True,
            file_outputs=[lkapi.EncodedFileOutput(
                file_type=lkapi.EncodedFileType.OGG,
                filepath=f"calls/{call_id}.ogg",
                s3=lkapi.S3Upload(
                    bucket=os.getenv("MINIO_BUCKET", "muftykare-calls"),
                    region="us-east-1",
                    access_key=os.getenv("MINIO_ACCESS_KEY"),
                    secret=os.getenv("MINIO_SECRET_KEY"),
                    endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
                    force_path_style=True,
                ),
            )],
        )
        res = await lk.egress.start_room_composite_egress(req)
        await lk.aclose()
        return res.egress_id
    except Exception as e:
        logger.warning("call recording failed to start", extra={"error": str(e)})
        return None


async def stop_call_recording(egress_id: str) -> None:
    """Stop LiveKit Egress recording — handles already-completed egress gracefully."""
    lk = None
    try:
        lk = lkapi.LiveKitAPI()
        await lk.egress.stop_egress(lkapi.StopEgressRequest(egress_id=egress_id))
        logger.info("call recording stopped", extra={"egress_id": egress_id})
    except Exception as e:
        error_msg = str(e)
        if "EGRESS_COMPLETE" in error_msg:
            logger.info("call recording already completed", extra={"egress_id": egress_id})
        else:
            logger.warning("call recording stop failed", extra={"error": error_msg})
    finally:
        if lk:
            try:
                await lk.aclose()
            except Exception:
                pass


# ── Call latency tracker ────────────────────────────────────────────────────
@dataclass
class CallTimings:
    call_start: float = field(default_factory=time.perf_counter)
    participant_joined: float | None = None
    customer_lookup_start: float | None = None
    customer_lookup_end: float | None = None
    db_pool_created: float | None = None
    session_start: float | None = None
    stt_connected: float | None = None
    first_transcript: float | None = None
    llm_start: float | None = None
    llm_first_token: float | None = None
    tts_start: float | None = None
    tts_first_audio: float | None = None
    first_audio_played: float | None = None

    def log_summary(self, logger, room: str) -> None:
        """Log a full latency breakdown after first audio plays."""
        def ms(start, end) -> str:
            if start is None or end is None:
                return "N/A"
            return f"{(end - start) * 1000:.0f}ms"

        ref = self.call_start
        def since(t) -> str:
            if t is None:
                return "N/A"
            return f"{(t - ref) * 1000:.0f}ms"

        logger.info(
            "call latency breakdown",
            extra={
                "room": room,
                "participant_joined_at":     since(self.participant_joined),
                "db_pool_ready_at":          since(self.db_pool_created),
                "customer_lookup":           ms(self.customer_lookup_start, self.customer_lookup_end),
                "customer_lookup_done_at":   since(self.customer_lookup_end),
                "session_start_at":          since(self.session_start),
                "stt_connected_at":          since(self.stt_connected),
                "first_transcript_at":       since(self.first_transcript),
                "llm_start_at":              since(self.llm_start),
                "llm_first_token_at":        since(self.llm_first_token),
                "llm_ttft":                  ms(self.llm_start, self.llm_first_token),
                "tts_start_at":              since(self.tts_start),
                "tts_first_audio_at":        since(self.tts_first_audio),
                "tts_latency":               ms(self.tts_start, self.tts_first_audio),
                "total_to_first_audio":      since(self.first_audio_played),
            }
        )


async def prewarm_sarvam(stt_language: str = "unknown") -> None:
    """
    Open and immediately close Sarvam STT and TTS WebSockets to warm the
    connection — so the real connections at session.start() are instant.
    This runs during the ctx.connect() → wait_for_participant() window.
    """
    try:
        import aiohttp
        import os

        api_key = os.getenv("SARVAM_API_KEY", "")
        headers = {"api-subscription-key": api_key}

        # Warm STT WebSocket
        stt_url = (
            f"wss://api.sarvam.ai/speech-to-text/ws"
            f"?language-code={stt_language}&model=saaras:v3"
            f"&vad_signals=true&sample_rate=16000&flush_signal=true&mode=transcribe"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(
                    stt_url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)
                ) as ws:
                    await ws.close()
                    logger.info("sarvam STT pre-warm done")
            except Exception as e:
                logger.debug("sarvam STT pre-warm skipped", extra={"reason": str(e)})

            # Warm TTS WebSocket
            tts_url = "wss://api.sarvam.ai/text-to-speech/ws"
            try:
                async with session.ws_connect(
                    tts_url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)
                ) as ws:
                    await ws.close()
                    logger.info("sarvam TTS pre-warm done")
            except Exception as e:
                logger.debug("sarvam TTS pre-warm skipped", extra={"reason": str(e)})

    except Exception as e:
        logger.debug("sarvam pre-warm failed", extra={"error": str(e)})


async def prewarm_ambient() -> None:
    """Pre-decode the office ambience audio during the participant wait window."""
    global _ambient_gen_cache
    try:
        _ambience_path = BuiltinAudioClip.OFFICE_AMBIENCE.path()
        _ambient_gen_cache = await make_ambient_generator(_ambience_path)
        logger.info("ambient audio pre-warm done")
    except Exception as e:
        logger.debug("ambient pre-warm failed", extra={"error": str(e)})


def prewarm(proc: JobProcess) -> None:
    """Load the LiveKit-bundled (Silero) VAD model once per worker process."""
    proc.userdata["vad"] = inference.VAD(model="silero")


def get_vad_instance(ctx: JobContext):
    """Return the pre-warmed VAD from worker userdata if available."""
    proc_userdata = getattr(getattr(ctx, "proc", None), "userdata", None)
    if proc_userdata and "vad" in proc_userdata:
        return proc_userdata["vad"]

    logger.warning("no prewarmed VAD found, creating fallback VAD")
    return inference.VAD()


# ── AgentServer ─────────────────────────────────────────────────────────────
server = AgentServer()
server.setup_fnc = prewarm


@server.rtc_session(agent_name="muftykare-agent-dev")
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
    timings = CallTimings()

    # ── 1. Create DB pool ───────────────────────────────────────────────────
    db_pool = await create_pool()
    timings.db_pool_created = time.perf_counter()

    # ── 1b. Parse dispatch metadata (set by outbound_campaign.py for prospecting calls) ──
    _dispatch_metadata: dict = {}
    try:
        if ctx.job.metadata:
            _dispatch_metadata = json.loads(ctx.job.metadata)
    except Exception as e:
        logger.warning("failed to parse job metadata", extra={"error": str(e)})

    _is_prospecting = _dispatch_metadata.get("call_type") == CALL_TYPE_PROSPECTING

    # ── 2. Determine starting agent ─────────────────────────────────────────
    # Prospecting: driven by dispatch metadata, not TEST_AGENT
    # Dev: read TEST_AGENT from .env to test individual agents
    # Production: always GreeterAgent
    agent_name = os.getenv("TEST_AGENT", "greeter").lower().strip()
    AgentClass = _AGENT_MAP.get(agent_name, GreeterAgent)

    # Log which agent is starting
    logger.info(
        "starting agent",
        extra={"agent": "OutboundAgent(prospecting)" if _is_prospecting else AgentClass.__name__, "room": ctx.room.name},
    )
    print(f"\n>>> MuftyKare: {'OutboundAgent(prospecting)' if _is_prospecting else AgentClass.__name__} <<<\n")

    # ── 3. Determine caller phone ────────────────────────────────────────────
    # Prospecting: phone comes from dispatch metadata (the customer is dialed
    # separately via SIP after dispatch) — do not rely on SIP attributes.
    # Inbound (dev/Agent Console + production): wait for SIP participant, extract phone.
    caller_phone = None
    call_id = ctx.room.name

    if _is_prospecting:
        caller_phone = _dispatch_metadata.get("customer_phone")
        logger.info(
            "prospecting call metadata",
            extra={"phone": f"****{caller_phone[-4:]}" if caller_phone else "unknown"},
        )
        # ── Pre-warm Sarvam + ambient during participant wait window ─────────
        await asyncio.gather(
            prewarm_sarvam(stt_language=SARVAM_LANGUAGE),
            prewarm_ambient(),
        )
        await ctx.wait_for_participant()
        timings.participant_joined = time.perf_counter()
    else:
        # ── Pre-warm Sarvam + ambient during participant wait window ─────────
        await asyncio.gather(
            prewarm_sarvam(stt_language=SARVAM_LANGUAGE),
            prewarm_ambient(),
        )
        participant = await ctx.wait_for_participant()
        timings.participant_joined = time.perf_counter()

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
    _prospecting_context = None
    if _is_prospecting and caller_phone:
        from db.queries import fetch_outbound_customer_context
        timings.customer_lookup_start = time.perf_counter()
        _prospecting_context = await fetch_outbound_customer_context(db_pool, caller_phone)
        timings.customer_lookup_end = time.perf_counter()
        customer = _prospecting_context
    elif caller_phone:
        from db.queries import fetch_customer_by_phone
        timings.customer_lookup_start = time.perf_counter()
        customer = await fetch_customer_by_phone(db_pool, caller_phone)
        timings.customer_lookup_end = time.perf_counter()

    # ── 5. Build MuftyKareUserData ──────────────────────────────────────────
    userdata = MuftyKareUserData(
        db_pool=db_pool,
        call_id=call_id,
        call_direction=DIRECTION_OUTBOUND if _is_prospecting else DIRECTION_INBOUND,
        call_type=CALL_TYPE_PROSPECTING if _is_prospecting else None,
        caller_phone=caller_phone,
        customer_id=customer["id"] if customer else None,
        customer_name=(customer["name"] if customer else None) or _dispatch_metadata.get("customer_name"),
        customer_address=customer.get("address") if customer else None,
        language=SARVAM_LANGUAGE,
    )

    # Pre-populate agents registry
    if _is_prospecting:
        userdata.agents = build_agent_registry(call_type=CALL_TYPE_PROSPECTING)
        userdata.agents[AGENT_OUTBOUND] = OutboundAgent(
            call_type=CALL_TYPE_PROSPECTING,
            customer_context=_prospecting_context or {"name": userdata.customer_name},
        )
    else:
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
            direction=DIRECTION_OUTBOUND if _is_prospecting else DIRECTION_INBOUND,
            language=SARVAM_LANGUAGE,
        )
        userdata.call_log_id = log_id
    except Exception as e:
        # Non-fatal — don't crash the call if logging fails
        logger.warning("log_call_start failed", extra={"error": str(e)})

    # Egress recording disabled — egress minutes were exhausted, failing
    # every call and leaking an aiohttp session/connector.
    # # ── 6b. Start call recording (background — does not block session start) ─
    # async def _start_recording_bg() -> None:
    #     nonlocal egress_id
    #     _id = await start_call_recording(ctx.room.name, call_id)
    #     if _id:
    #         egress_id = _id
    #         logger.info("call recording started", extra={"egress_id": _id})
    #         # ── 6c. Log recording to DB ──────────────────────────────────────
    #         try:
    #             from db.queries import log_call_recording
    #             await log_call_recording(
    #                 db_pool,
    #                 call_id=call_id,
    #                 customer_id=userdata.customer_id,
    #                 caller_phone=caller_phone,
    #                 egress_id=_id,
    #                 file_path=f"calls/{call_id}.ogg",
    #                 call_log_id=userdata.call_log_id,
    #             )
    #         except Exception as e:
    #             logger.warning("log_call_recording failed", extra={"error": str(e)})
    #
    # asyncio.create_task(_start_recording_bg())

    # ── 7. Build AgentSession ───────────────────────────────────────────────
    session = AgentSession[MuftyKareUserData](
        userdata=userdata,
        vad=get_vad_instance(ctx),

        # STT — Sarvam Saaras v3, Telugu primary
        # flush_signal=True is MANDATORY for Sarvam turn detection
        stt=sarvam.STT(
            model=SARVAM_STT_MODEL,
            language=SARVAM_LANGUAGE,
            mode="transcribe",
            # flush_signal=True,
        ),
    #     stt=sarvam.STT(
    #     model="saaras:v3",
    #     language="te-IN",
    #     mode="transcribe",
    #     flush_signal=True,       # ← disable Sarvam VAD signals
    # ),

        # LLM — GPT-4o, parallel_tool_calls=False for voice reliability
        # llm=lk_openai.LLM(
        #     model=LLM_MODEL,
        #     parallel_tool_calls=False,
        # ),
        llm=lk_google.LLM(
            model=LLM_MODEL,
        ),
        # TTS — Sarvam Bulbul v3, Telugu female voice
        # TEMP: swapped for OpenAI TTS for testing — restore this once testing is done
        tts=sarvam.TTS(
            target_language_code=SARVAM_LANGUAGE,
            model=SARVAM_TTS_MODEL,
            speaker=SARVAM_TTS_SPEAKER,
            output_audio_codec="mulaw",
        ),
    #     tts=sarvam.TTS(
    #     target_language_code="te-IN",
    #     model="bulbul:v2",        # ← try v2 instead of v3
    #     speaker="anushka",
    # ),
        # vad=ctx.proc.userdata["vad"],
        # TTS — OpenAI (testing only)
        # tts=lk_openai.TTS(
        #     model="tts-1",
        #     voice="nova",
        # ),

        # Turn detection — LiveKit (Silero) VAD, loaded once per worker in prewarm()
        turn_detection="vad",

        # Silence timeout — fires user_state_changed after N seconds of silence
        # user_away_timeout=USER_AWAY_TIMEOUT_SECS,
    )

    # ── 8. Transcript logging ───────────────────────────────────────────────
    @session.on("user_input_transcribed")
    def on_transcript(event):
        if timings.stt_connected is None:
            timings.stt_connected = time.perf_counter()
        if event.is_final:
            if timings.first_transcript is None:
                timings.first_transcript = time.perf_counter()
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
            # Egress recording disabled — see start of entrypoint, nothing to stop.
            # if egress_id:
            #     await stop_call_recording(egress_id)
            await background_audio.aclose()
            await close_pool(db_pool)

    ctx.add_shutdown_callback(on_shutdown)

    # ── 10. Background audio — pre-decoded during participant wait window ────
    background_audio = BackgroundAudioPlayer(
        ambient_sound=AudioConfig(_ambient_gen_cache, volume=2.5),
    )

    # ── 11. Start session ───────────────────────────────────────────────────
    starting_agent = userdata.agents[AGENT_OUTBOUND] if _is_prospecting else AgentClass()
    logger.info(
        "session starting",
        extra={"agent": type(starting_agent).__name__, "room": ctx.room.name},
    )

    # ── Latency tracking hooks — MUST be before session.start() ─────────────
    # The agent fires agent_speech_started for its opening greeting immediately
    # on session.start(). Handlers registered after miss that event, so
    # first_audio_played is never set and log_summary never fires.
    @session.on("agent_state_changed")
    def on_state_changed(event):
        if event.new_state == "thinking" and timings.llm_start is None:
            timings.llm_start = time.perf_counter()

    @session.on("agent_speech_started")
    def on_speech_started(event):
        if timings.tts_first_audio is None:
            timings.tts_first_audio = time.perf_counter()
        if timings.first_audio_played is None:
            timings.first_audio_played = time.perf_counter()
            timings.log_summary(logger, ctx.room.name)

    timings.session_start = time.perf_counter()
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
    cli.run_app(
        WorkerOptions(
            agent_name="muftykare-agent-dev",  # <-- Add this! It matches your previous setup
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            num_idle_processes=1,
            load_threshold=0.7,
        )
    )


# from livekit.agents import (
#     Agent,
#     AgentServer,
#     AgentSession,
#     JobContext,
#     RunContext,
#     cli,
#     function_tool,
#     inference,
# )
# from livekit.plugins import sarvam
# from livekit.plugins import google as lk_google
# from dotenv import load_dotenv
# load_dotenv()

# @function_tool
# async def lookup_weather(
#     context: RunContext,
#     location: str,
# ):
#     """Used to look up weather information."""

#     return {"weather": "sunny", "temperature": 70}


# server = AgentServer()


# @server.rtc_session(agent_name="muftykare-agent-dev")
# async def entrypoint(ctx: JobContext):
#     session = AgentSession(
#         vad=inference.VAD(),
#         # STT — Sarvam Saaras v3, Telugu primary
#         stt=sarvam.STT(
#             model="saaras:v3",
#             language="te-IN",
#             mode="transcribe",
#             flush_signal=True,
#         ),
#         # LLM — Gemini``
#         llm=lk_google.LLM(
#             model="gemini-3.1-flash-lite",
#         ),
#         # TTS — Sarvam Bulbul v2, Telugu female voice
#         tts=sarvam.TTS(
#             target_language_code="te-IN",
#             model="bulbul:v2",
#             speaker="anushka",
#         ),
#     )

#     agent = Agent(
#         instructions="You are a friendly voice assistant built by LiveKit.",
#         tools=[lookup_weather],
#     )

#     await session.start(agent=agent, room=ctx.room)
#     await session.generate_reply(instructions="greet the user and ask about their day")


# if __name__ == "__main__":
#     cli.run_app(server)