"""
plivo_bridge.py — Bridges Plivo bidirectional audio stream to MuftyKare agent.

Audio path:
  Plivo -> base64 mulaw 8kHz -> PCM 16kHz -> rtc.AudioSource -> LiveKit room
    -> RoomIO (BVCTelephony) -> Sarvam STT -> GPT-4.1-mini
  Sarvam TTS -> PlivoAudioOutput -> PCM -> mulaw 8kHz -> base64 -> Plivo -> Caller

Two LiveKit room connections are used (see PlivoBridge._start_agent):
  - self._caller_room, identity "plivo-caller-*", publishes the caller's
    audio as a track. RoomIO only ever treats a *remote* participant's
    track as input, so this must be a separate identity from the agent's.
  - self._agent_room, identity "agent-*", is passed as room= to
    AgentSession.start() and is what RoomIO/BVCTelephony/BackgroundAudioPlayer
    /Egress all operate on. TTS output still goes through PlivoAudioOutput
    (not RoomIO's own audio output track) straight to Plivo.

NOTE: GreeterAgent.to_human / _warm_transfer() (agents/base.py) still cannot
merge a human manager into the call on this path. WarmTransferTask calls
get_job_context(), which is only populated inside the real LiveKit worker
dispatch loop (cli.run_app / AgentServer). This bridge is a standalone
FastAPI WebSocket handler that never enters that dispatch flow, so
get_job_context() raises regardless of whether a room exists. It degrades
gracefully (apology + hangup) via its own except-Exception handling; nothing
here needs to catch that.
"""
import asyncio
import audioop
import base64
import json
import time
import traceback

from fastapi import WebSocket
from livekit import rtc
from livekit.agents import AgentSession, BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip
from livekit.agents.voice import io as agent_io, room_io
from livekit.api import AccessToken, VideoGrants
from livekit.plugins import sarvam
from livekit.plugins import openai as lk_openai
from livekit.plugins import noise_cancellation

from logger import get_logger
from db.connection import create_pool, close_pool
from db.queries import fetch_customer_by_phone, log_call_start, log_call_end
from userdata import MuftyKareUserData
from agents import build_agent_registry, GreeterAgent
from audio_cache import make_ambient_generator
from agent import start_call_recording, stop_call_recording
from config.settings import LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
from config.constants import (
    SARVAM_STT_MODEL, SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER,
    SARVAM_LANGUAGE, SARVAM_ENDPOINTING_MS, LLM_MODEL,
    USER_AWAY_TIMEOUT_SECS, DIRECTION_INBOUND,
)

logger = get_logger(__name__)

# Audio constants
PLIVO_SAMPLE_RATE = 8000    # Plivo sends/receives mulaw at 8kHz
AGENT_SAMPLE_RATE = 16000   # Sarvam STT expects 16kHz PCM


# ── Custom AudioOutput — captures TTS frames, enqueues mulaw for Plivo ─────

class PlivoAudioOutput(agent_io.AudioOutput):
    """
    AudioOutput sink for the agent pipeline. Converts PCM TTS frames to 8kHz
    mulaw and enqueues them for the Plivo sender task.

    flush()/clear_buffer() and on_playback_finished() are required so the
    session's turn-taking/barge-in logic knows when a spoken segment ends —
    without them wait_for_playout() (used for interruption handling) hangs
    forever. Playout completion here is approximated as "handed off to the
    Plivo send queue" since Plivo gives us no playback ack.
    """

    def __init__(self, mulaw_queue: "asyncio.Queue[bytes]") -> None:
        super().__init__(
            label="plivo_output",
            sample_rate=AGENT_SAMPLE_RATE,
            capabilities=agent_io.AudioOutputCapabilities(pause=False),
        )
        self._mulaw_queue = mulaw_queue
        self._pushed_duration = 0.0
        self._interrupted = asyncio.Event()
        self._flush_task: asyncio.Task | None = None
        self._flush_time: float = 0.0  # monotonic timestamp when flush() was called

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        """Called by the TTS pipeline for each audio frame."""
        await super().capture_frame(frame)

        pcm_bytes = bytes(frame.data)
        if frame.sample_rate != PLIVO_SAMPLE_RATE:
            pcm_8k, _ = audioop.ratecv(
                pcm_bytes, 2, 1, frame.sample_rate, PLIVO_SAMPLE_RATE, None
            )
        else:
            pcm_8k = pcm_bytes

        mulaw_bytes = audioop.lin2ulaw(pcm_8k, 2)
        self._pushed_duration += (len(pcm_8k) // 2) / PLIVO_SAMPLE_RATE
        try:
            self._mulaw_queue.put_nowait(mulaw_bytes)
        except asyncio.QueueFull:
            pass

    def flush(self) -> None:
        import time
        super().flush()
        self._flush_time = time.monotonic()
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(self._wait_for_playout())

    def clear_buffer(self) -> None:
        while not self._mulaw_queue.empty():
            try:
                self._mulaw_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._pushed_duration:
            self._interrupted.set()

    async def _wait_for_playout(self) -> None:
        interrupted_wait = asyncio.create_task(self._interrupted.wait())
        drain_wait = asyncio.create_task(self._wait_queue_drained())
        await asyncio.wait(
            [interrupted_wait, drain_wait], return_when=asyncio.FIRST_COMPLETED
        )

        interrupted = self._interrupted.is_set()
        pushed_duration = self._pushed_duration

        for task in (interrupted_wait, drain_wait):
            if not task.done():
                task.cancel()

        self._pushed_duration = 0.0
        self._interrupted.clear()
        self.on_playback_finished(playback_position=pushed_duration, interrupted=interrupted)

    async def _wait_queue_drained(self) -> None:
        """
        Wait until Plivo has had enough time to play back all the audio we
        queued. We can't get a playback-complete ack from Plivo, so we estimate
        duration from bytes pushed (bytes / 8000 = seconds at 8kHz mulaw).

        The key insight: _send_audio_to_plivo drains the queue much faster than
        real-time. Waiting for queue-empty fires this signal almost immediately,
        which makes the session think the turn ended before Plivo has played
        even the first syllable. Instead, sleep for the remaining estimated
        playback duration minus time already elapsed since flush().
        """
        import time
        # Wait until the queue is actually drained first (frames handed to sender)
        while not self._mulaw_queue.empty():
            await asyncio.sleep(0.01)
        # Then wait for the remaining estimated playback wall-clock time
        elapsed = time.monotonic() - self._flush_time
        remaining = max(0.0, self._pushed_duration - elapsed)
        if remaining > 0:
            await asyncio.sleep(remaining)


# ── PlivoBridge — main bridge class ────────────────────────────────────────

class PlivoBridge:
    def __init__(
        self,
        websocket: WebSocket,
        call_uuid: str,
        caller_phone: str,
    ) -> None:
        self.websocket = websocket
        self.call_uuid = call_uuid
        self.caller_phone = caller_phone

        self._db_pool = None
        self._session: AgentSession | None = None
        self._room_name = f"muftykare-plivo-{call_uuid}"
        self._caller_room: rtc.Room | None = None
        self._agent_room: rtc.Room | None = None
        self._audio_source: rtc.AudioSource | None = None
        self._background_audio: BackgroundAudioPlayer | None = None
        self._egress_id: str | None = None
        self._audio_out_queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=200)
        self._intent: str | None = None
        self._outcome: str | None = None
        self._order_id: str | None = None
        self._closed = False
        self._agent_ready = False
        self._stream_sid: str | None = None
        self._send_task: asyncio.Task | None = None
        self._agent_start_task: asyncio.Task | None = None

    def _generate_token(self, identity: str, name: str) -> str:
        return (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(name)
            .with_grants(VideoGrants(
                room_join=True,
                room=self._room_name,
                can_publish=True,
                can_subscribe=True,
            ))
            .to_jwt()
        )

    async def run(self) -> None:
        """Main WebSocket event loop."""
        async for raw in self._ws_iter():
            event = json.loads(raw)
            ev_type = event.get("event")

            if ev_type == "start":
                self._stream_sid = event.get("start", {}).get("streamSid")
                logger.info("stream started", extra={
                    "call_uuid": self.call_uuid,
                    "caller": f"****{self.caller_phone[-4:]}" if self.caller_phone else "unknown",
                })
                self._agent_start_task = asyncio.create_task(self._start_agent())
                self._send_task = asyncio.create_task(self._send_audio_to_plivo())

            elif ev_type == "media":
                payload = event.get("media", {}).get("payload", "")
                if payload and self._audio_source:
                    mulaw_bytes = base64.b64decode(payload)
                    pcm_bytes = self._mulaw_to_pcm16(mulaw_bytes)
                    frame = rtc.AudioFrame(
                        data=pcm_bytes,
                        sample_rate=AGENT_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(pcm_bytes) // 2,
                    )
                    await self._audio_source.capture_frame(frame)

            elif ev_type == "stop":
                logger.info("stream stopped", extra={"call_uuid": self.call_uuid})
                break

    async def _start_agent(self) -> None:
        """Initialize DB, customer lookup, agent session."""
        from livekit.agents.utils.http_context import open as http_open
        async with http_open():
            try:
                self._db_pool = await create_pool()
                customer = await fetch_customer_by_phone(self._db_pool, self.caller_phone)

                userdata = MuftyKareUserData(
                    db_pool=self._db_pool,
                    call_id=self.call_uuid,
                    call_direction=DIRECTION_INBOUND,
                    caller_phone=self.caller_phone,
                    customer_id=customer["id"] if customer else None,
                    customer_name=customer["name"] if customer else None,
                    customer_address=customer.get("address") if customer else None,
                    language=SARVAM_LANGUAGE,
                )
                userdata.agents = build_agent_registry()

                try:
                    userdata.call_log_id = await log_call_start(
                        self._db_pool,
                        call_id=self.call_uuid,
                        caller_phone=self.caller_phone,
                        customer_id=userdata.customer_id,
                        direction=DIRECTION_INBOUND,
                        language=SARVAM_LANGUAGE,
                    )
                except Exception as e:
                    logger.warning("log_call_start failed", extra={"error": str(e)})

                logger.warning(
                    "plivo call path has a real LiveKit room but no JobContext — "
                    "human warm-transfer (to_human) still cannot connect a manager "
                    "because WarmTransferTask requires get_job_context()",
                    extra={"call_uuid": self.call_uuid},
                )

                # ── Connect the caller's room identity and publish its audio ──
                # RoomIO only treats a REMOTE participant's track as input, so
                # the caller must be a separate identity from the agent's.
                self._caller_room = rtc.Room()
                caller_token = self._generate_token(
                    f"plivo-caller-{self.call_uuid[:8]}", "Plivo Caller"
                )
                await self._caller_room.connect(LIVEKIT_URL, caller_token)

                self._audio_source = rtc.AudioSource(
                    sample_rate=AGENT_SAMPLE_RATE, num_channels=1
                )
                caller_track = rtc.LocalAudioTrack.create_audio_track(
                    "plivo-caller", self._audio_source
                )
                await self._caller_room.local_participant.publish_track(caller_track)

                # ── Connect the agent's own room identity ─────────────────────
                self._agent_room = rtc.Room()
                agent_token = self._generate_token(
                    f"agent-{self.call_uuid[:8]}", "MuftyKare Agent"
                )
                await self._agent_room.connect(LIVEKIT_URL, agent_token)

                # Build custom TTS output — RoomIO's own audio output is
                # disabled automatically once session.output.audio is set
                # before start() (see AgentSession.start()).
                audio_output = PlivoAudioOutput(self._audio_out_queue)

                self._session = AgentSession[MuftyKareUserData](
                    userdata=userdata,
                    stt=sarvam.STT(
                        model=SARVAM_STT_MODEL,
                        language=SARVAM_LANGUAGE,
                        mode="transcribe",
                        flush_signal=True,
                    ),
                    llm=lk_openai.LLM(
                        model=LLM_MODEL,
                        parallel_tool_calls=False,
                    ),
                    tts=sarvam.TTS(
                        target_language_code=SARVAM_LANGUAGE,
                        model=SARVAM_TTS_MODEL,
                        speaker=SARVAM_TTS_SPEAKER,
                    ),
                    turn_detection="stt",
                    min_endpointing_delay=SARVAM_ENDPOINTING_MS,
                    user_away_timeout=USER_AWAY_TIMEOUT_SECS,
                )

                # Must be set before start() — RoomIO checks output.audio and
                # skips creating its own audio output track when it's already set.
                self._session.output.audio = audio_output

                await self._session.start(
                    agent=GreeterAgent(),
                    room=self._agent_room,
                    room_input_options=room_io.RoomInputOptions(
                        noise_cancellation=noise_cancellation.BVCTelephony(),
                    ),
                )
                self._session.output.set_audio_enabled(True)

                # Background ambient audio — needs a real room.
                ambient_gen = await make_ambient_generator(BuiltinAudioClip.OFFICE_AMBIENCE.path())
                self._background_audio = BackgroundAudioPlayer(
                    ambient_sound=AudioConfig(ambient_gen, volume=2.5),
                )
                await self._background_audio.start(
                    room=self._agent_room, agent_session=self._session
                )

                # Egress recording — fire-and-forget, don't block session start.
                async def _start_recording_bg() -> None:
                    egress_id = await start_call_recording(self._room_name, self.call_uuid)
                    if egress_id:
                        self._egress_id = egress_id
                        logger.info(
                            "call recording started",
                            extra={"call_uuid": self.call_uuid, "egress_id": egress_id},
                        )

                asyncio.create_task(_start_recording_bg())

                self._agent_ready = True
                t_session_ready = time.perf_counter()
                logger.info("agent started", extra={"call_uuid": self.call_uuid})

                # ── Diagnostic: confirm STT→session transcript pipeline ──────
                @self._session.on("user_input_transcribed")
                def on_transcript(event) -> None:
                    if event.is_final:
                        logger.info(
                            "transcript received",
                            extra={
                                "call_uuid": self.call_uuid,
                                "transcript": event.transcript,
                            },
                        )

                # ── Latency tracking ─────────────────────────────────────────
                # Track when the LLM starts thinking and when Kavya first speaks.
                # Fires "call latency breakdown" on the first agent_speech_started.
                t_call_start = time.perf_counter()  # approx; real start is above
                t_llm_start: float | None = None
                t_first_audio: float | None = None

                @self._session.on("agent_state_changed")
                def _on_state_changed(event) -> None:
                    nonlocal t_llm_start
                    if getattr(event, "new_state", None) == "thinking" and t_llm_start is None:
                        t_llm_start = time.perf_counter()

                @self._session.on("agent_speech_started")
                def _on_speech_started(event) -> None:
                    nonlocal t_first_audio
                    if t_first_audio is not None:
                        return
                    t_first_audio = time.perf_counter()
                    logger.info(
                        "call latency breakdown",
                        extra={
                            "call_uuid": self.call_uuid,
                            "session_ready_to_first_audio_ms": round(
                                (t_first_audio - t_session_ready) * 1000
                            ),
                            "llm_start_to_first_audio_ms": (
                                round((t_first_audio - t_llm_start) * 1000)
                                if t_llm_start else "N/A"
                            ),
                        },
                    )

                # Keep the http_context alive for the entire call duration.
                # TTS/STT WebSocket sessions require an active aiohttp session
                # (via http_session()) throughout — not just during startup.
                # self._closed is set to True by close() when the call ends.
                try:
                    while not self._closed:
                        await asyncio.sleep(1)
                finally:
                    # Close the session BEFORE http_open exits.
                    # If we let http_open tear down first, the aiohttp session
                    # (which Sarvam TTS/STT WebSockets depend on) is gone and the
                    # in-flight TTS stream raises ChanClosed mid-frame.
                    if self._session:
                        try:
                            userdata: MuftyKareUserData = self._session.userdata
                            self._intent = userdata.intent
                            self._outcome = userdata.outcome
                            self._order_id = userdata.current_order_id
                        except Exception:
                            pass
                        try:
                            await self._session.aclose()
                        except Exception as e:
                            logger.debug(
                                "session aclose error",
                                extra={"error": str(e), "call_uuid": self.call_uuid},
                            )

            except Exception:
                logger.error(
                    "agent start failed\n" + traceback.format_exc(),
                    extra={"call_uuid": self.call_uuid},
                )

    async def _send_audio_to_plivo(self) -> None:
        """
        Drain outbound mulaw queue and send back to Plivo.
        During agent initialization, inject one 20ms silence frame per timeout
        cycle to keep Plivo's WebSocket alive — properly paced, no burst.
        mulaw silence byte is 0xFF (silence in G.711 u-law).
        """
        silence_chunk = b'\xff' * 160  # 20ms of G.711 u-law silence at 8kHz
        while not self._closed:
            try:
                mulaw_bytes = await asyncio.wait_for(
                    self._audio_out_queue.get(), timeout=0.02  # 20ms
                )
            except asyncio.TimeoutError:
                if not self._agent_ready:
                    # Inject one silence frame per 20ms cycle during startup.
                    # This keeps Plivo's WebSocket alive without pre-loading a
                    # burst of silence frames that Plivo would queue and play
                    # back over several seconds, delaying real TTS audio.
                    mulaw_bytes = silence_chunk
                else:
                    continue
            try:
                payload = base64.b64encode(mulaw_bytes).decode()
                await self.websocket.send_json({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": payload,
                    }
                })
            except Exception:
                break

    def _mulaw_to_pcm16(self, mulaw_bytes: bytes) -> bytes:
        """Convert 8kHz mulaw -> 16kHz 16-bit PCM for Sarvam STT."""
        pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        return pcm_16k

    async def _ws_iter(self):
        """Safe WebSocket message iterator."""
        while not self._closed:
            try:
                msg = await self.websocket.receive_text()
                yield msg
            except Exception:
                break

    async def close(self) -> None:
        """Clean up all resources on call end."""
        if self._closed:
            return
        self._closed = True

        if self._agent_start_task:
            try:
                await self._agent_start_task
            except Exception:
                pass

        intent = self._intent
        outcome = self._outcome
        order_id = self._order_id
        # session.aclose() was already called inside _start_agent's finally block
        # (while the http_context was still alive) — do not call it again here.

        if self._background_audio:
            try:
                await self._background_audio.aclose()
            except Exception as e:
                logger.debug("background audio aclose error", extra={"error": str(e)})

        if self._egress_id:
            try:
                await stop_call_recording(self._egress_id)
            except Exception as e:
                logger.debug("stop_call_recording error", extra={"error": str(e)})

        if self._caller_room:
            try:
                await self._caller_room.disconnect()
            except Exception as e:
                logger.debug("caller room disconnect error", extra={"error": str(e)})

        if self._agent_room:
            try:
                await self._agent_room.disconnect()
            except Exception as e:
                logger.debug("agent room disconnect error", extra={"error": str(e)})

        if self._send_task:
            self._send_task.cancel()

        if self._db_pool:
            try:
                await log_call_end(
                    self._db_pool,
                    call_id=self.call_uuid,
                    intent=intent,
                    order_id=order_id,
                    outcome=outcome,
                )
            except Exception as e:
                logger.warning("log_call_end failed", extra={"error": str(e)})
            await close_pool(self._db_pool)
