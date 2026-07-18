"""
server.py — FastAPI skeleton for MuftyKare Voice Agent API.

Outbound call triggers and Plivo webhooks are wired in Component 6.
"""
import os
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
import uvicorn

from logger import get_logger

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
    Returns XML telling Plivo to open a bidirectional audio WebSocket to us.
    """
    form = await request.form()
    call_uuid = form.get("CallUUID", str(uuid.uuid4()))
    caller_phone = form.get("From", "")

    logger.info(
        "inbound call",
        extra={"call_uuid": call_uuid, "from": f"****{caller_phone[-4:]}" if caller_phone else "unknown"},
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
    {ws_url}/plivo/stream/{call_uuid}?caller={caller_phone}
  </Stream>
</Response>"""

    return PlainTextResponse(xml, media_type="application/xml")


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
