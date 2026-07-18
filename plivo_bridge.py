"""
plivo_bridge.py — Bridges Plivo bidirectional audio stream to MuftyKare agent.

Audio path:
  Plivo -> base64 mulaw 8kHz -> PCM 16kHz -> Sarvam STT -> GPT-4.1-mini
  Sarvam TTS -> PCM -> mulaw 8kHz -> base64 -> Plivo -> Caller

No LiveKit SIP bridge, no LiveKit room -- eliminates Issue #608 audio artifacts.

NOTE: because there is no LiveKit room on this path, GreeterAgent.to_human /
_warm_transfer() (agents/base.py) cannot merge a human manager into the call --
WarmTransferTask requires a room. It degrades gracefully (apology + hangup)
via its own except-Exception handling; nothing here needs to catch that.
"""
import asyncio
import audioop
import base64
import json
import traceback

from fastapi import WebSocket
from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.voice import io as agent_io
from livekit.plugins import sarvam
from livekit.plugins import openai as lk_openai

from logger import get_logger
from db.connection import create_pool, close_pool
from db.queries import fetch_customer_by_phone, log_call_start, log_call_end
from userdata import MuftyKareUserData
from agents import build_agent_registry, GreeterAgent
from config.constants import (
    SARVAM_STT_MODEL, SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER,
    SARVAM_LANGUAGE, SARVAM_ENDPOINTING_MS, LLM_MODEL,
    USER_AWAY_TIMEOUT_SECS, DIRECTION_INBOUND,
)

logger = get_logger(__name__)

# Audio constants
PLIVO_SAMPLE_RATE = 8000    # Plivo sends/receives mulaw at 8kHz
AGENT_SAMPLE_RATE = 16000   # Sarvam STT expects 16kHz PCM


# ── Custom AudioInput — queue-backed, fed by Plivo media events ────────────

class PlivoAudioInput(agent_io.AudioInput):
    """Pull-based AudioInput. Plivo media events push frames in via push_frame();
    the STT pipeline pulls them out via __anext__()."""

    def __init__(self) -> None:
        super().__init__(label="plivo_input")
        self._queue: "asyncio.Queue[rtc.AudioFrame | None]" = asyncio.Queue(maxsize=200)

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        """Non-blocking — called from the Plivo media event handler."""
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass  # drop rather than block if the STT pipeline falls behind

    async def __anext__(self) -> rtc.AudioFrame:
        frame = await self._queue.get()
        if frame is None:
            raise StopAsyncIteration
        return frame

    async def aclose(self) -> None:
        await self._queue.put(None)


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
        super().flush()
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
        while not self._mulaw_queue.empty():
            await asyncio.sleep(0.02)


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
        self._audio_input: PlivoAudioInput | None = None
        self._audio_out_queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=200)
        self._closed = False
        self._agent_ready = False
        self._stream_sid: str | None = None
        self._send_task: asyncio.Task | None = None
        self._agent_start_task: asyncio.Task | None = None

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
                if payload and self._audio_input:
                    mulaw_bytes = base64.b64decode(payload)
                    pcm_bytes = self._mulaw_to_pcm16(mulaw_bytes)
                    frame = rtc.AudioFrame(
                        data=pcm_bytes,
                        sample_rate=AGENT_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(pcm_bytes) // 2,
                    )
                    self._audio_input.push_frame(frame)

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
                    "no LiveKit room on this call path — human warm-transfer (to_human) "
                    "will not be able to connect a manager",
                    extra={"call_uuid": self.call_uuid},
                )

                # Build custom I/O
                self._audio_input = PlivoAudioInput()
                audio_output = PlivoAudioOutput(self._audio_out_queue)

                # Build session — no room/audio kwargs on AgentSession's constructor
                # in this livekit-agents version. Custom I/O is wired below via
                # session.input.audio / session.output.audio before start().
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

                # Must be set before start() — start() only skips RoomIO's audio
                # setup when input.audio/output.audio are already non-None, and
                # we never pass room=, so RoomIO is never created at all.
                self._session.input.audio = self._audio_input
                self._session.output.audio = audio_output

                await self._session.start(agent=GreeterAgent())
                self._session.output.set_audio_enabled(True)
                self._agent_ready = True
                logger.info("agent started", extra={"call_uuid": self.call_uuid})

                # Keep the http_context alive for the entire call duration.
                # TTS/STT WebSocket sessions require an active aiohttp session
                # (via http_session()) throughout — not just during startup.
                # self._closed is set to True by close() when the call ends.
                while not self._closed:
                    await asyncio.sleep(1)

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
                        "contentType": "audio/x-mulaw;rate=8000",
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

        if self._audio_input:
            await self._audio_input.aclose()

        if self._agent_start_task:
            try:
                await self._agent_start_task
            except Exception:
                pass

        intent = outcome = order_id = None
        try:
            if self._session:
                userdata: MuftyKareUserData = self._session.userdata
                intent = userdata.intent
                outcome = userdata.outcome
                order_id = userdata.current_order_id
                await self._session.aclose()
        except Exception as e:
            logger.warning("session close error", extra={"error": str(e)})

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
