"""
server.py — FastAPI skeleton for MuftyKare Voice Agent API.

Outbound call triggers and Plivo webhooks are wired in Component 6.
"""

from fastapi import FastAPI
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
# TODO Component 6: POST /webhook/plivo — receive and process Plivo events
# TODO Component 6: GET /orders/{phone} — order status lookup by phone number


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
