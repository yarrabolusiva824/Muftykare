"""
server.py — FastAPI skeleton for MuftyKare Voice Agent API.

Outbound call triggers and Plivo webhooks are wired in Component 6.
"""
import asyncio
import os
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
import uvicorn
from urllib.parse import quote
from logger import setup_logging, get_logger
from dotenv import load_dotenv

load_dotenv()

# Initialise file + console handlers BEFORE any module uses get_logger()
setup_logging()

logger = get_logger(__name__)

app = FastAPI(title="MuftyKare Voice Agent API")


@app.on_event("startup")
async def startup():
    logger.info("MuftyKare FastAPI server started", extra={"port": 8000})


@app.get("/health")
async def health():
    logger.debug("Health check called")
    return {"status": "ok", "agent": "muftykare-voice-agent", "version": "0.1.0"}


# TODO Component 6: POST /call/outbound — trigger outbound call via Plivo SIP
# TODO Component 6: GET /orders/{phone} — order status lookup by phone number


# ── Plivo Answer URL (Component 6) ──────────────────────────────────────────
@app.post("/plivo/answer")
async def plivo_answer(request: Request):
    """
    Plivo calls this when an inbound call arrives.

    We deliberately pre-warm Sarvam STT/TTS connections and decode the ambient
    audio cache *before* returning the XML response. While this handler runs,
    Plivo keeps the phone ringing — so the caller hears ringing, not silence.
    The total delay is ~1s, well within Plivo's 15s answer-URL timeout.
    By the time the WebSocket opens, everything is already initialised and
    Kavya can speak within 1-2s of the call connecting.
    """
    form = await request.form()
    call_uuid = form.get("CallUUID", str(uuid.uuid4()))
    caller_phone = form.get("From", "").replace(" ", "+")

    logger.info(
        "inbound call — pre-warming while ringing",
        extra={"call_uuid": call_uuid, "from": f"****{caller_phone[-4:]}" if caller_phone else "unknown"},
    )

    # Pre-warm Sarvam connections and ambient cache while phone is still ringing.
    # Caller experiences ringing — not dead silence.
    await asyncio.gather(
        _prewarm_sarvam(),
        _prewarm_ambient_cache(),
    )

    base_url = os.getenv("SERVER_BASE_URL", "")
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream
    keepCallAlive="true"
    bidirectional="true"
    contentType="audio/x-mulaw;rate=8000"
    streamTimeout="86400"
    callbackUrl="{base_url}/plivo/stream/status">
    {ws_url}/plivo/stream/{call_uuid}?caller={quote(caller_phone, safe="")}
  </Stream>
</Response>"""

    return PlainTextResponse(xml, media_type="application/xml")


async def _prewarm_sarvam() -> None:
    """Open and immediately close Sarvam STT + TTS WebSockets to warm connections."""
    try:
        import aiohttp
        api_key = os.getenv("SARVAM_API_KEY", "")
        headers = {"api-subscription-key": api_key}
        stt_url = (
            "wss://api.sarvam.ai/speech-to-text/ws"
            "?language-code=unknown&model=saaras:v3"
            "&vad_signals=true&sample_rate=16000&flush_signal=true&mode=transcribe"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(
                    stt_url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as ws:
                    await ws.close()
                logger.debug("sarvam STT pre-warm done")
            except Exception as e:
                logger.debug("sarvam STT pre-warm skipped", extra={"reason": str(e)})
            try:
                async with session.ws_connect(
                    "wss://api.sarvam.ai/text-to-speech/ws",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as ws:
                    await ws.close()
                logger.debug("sarvam TTS pre-warm done")
            except Exception as e:
                logger.debug("sarvam TTS pre-warm skipped", extra={"reason": str(e)})
    except Exception as e:
        logger.debug("sarvam pre-warm failed", extra={"error": str(e)})


async def _prewarm_ambient_cache() -> None:
    """Pre-decode office ambience audio into the in-memory cache."""
    try:
        from audio_cache import _get_cached_frames
        from livekit.agents import BuiltinAudioClip
        await _get_cached_frames(BuiltinAudioClip.OFFICE_AMBIENCE.path())
        logger.debug("ambient cache pre-warm done")
    except Exception as e:
        logger.debug("ambient pre-warm skipped", extra={"error": str(e)})


@app.post("/plivo/stream/status")
async def plivo_stream_status(request: Request):
    """Plivo stream lifecycle events."""
    try:
        data = await request.json()
        logger.info("stream status", extra={"event": data.get("event")})
    except Exception:
        pass
    return {"status": "ok"}


@app.post("/plivo/hangup")
async def plivo_hangup(request: Request):
    """Plivo call ended notification."""
    form = await request.form()
    logger.info("call ended", extra={
        "call_uuid": form.get("CallUUID"),
        "duration": form.get("Duration"),
    })
    return PlainTextResponse("OK")


@app.websocket("/plivo/stream/{call_uuid}")
async def plivo_stream(websocket: WebSocket, call_uuid: str):
    """
    Plivo bidirectional audio stream.
    Receives mulaw 8kHz audio from caller, sends mulaw 8kHz audio back from agent.
    """
    from plivo_bridge import PlivoBridge

    await websocket.accept()
    caller_phone = websocket.query_params.get("caller", "")

    bridge = PlivoBridge(
        websocket=websocket,
        call_uuid=call_uuid,
        caller_phone=caller_phone,
    )

    try:
        await bridge.run()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"call_uuid": call_uuid})
    except Exception as e:
        logger.error("WebSocket error", extra={"error": str(e), "call_uuid": call_uuid})
    finally:
        await bridge.close()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=True)
