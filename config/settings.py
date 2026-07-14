"""
config/settings.py — All environment variables for MuftyKare voice agent.
Validated at import time. Import this module everywhere instead of os.getenv().

Usage:
    from config.settings import LIVEKIT_URL, SARVAM_API_KEY, DATABASE_URL
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Get env var or raise clear error at startup."""
    val = os.getenv(key)
    if not val:
        raise ValueError(
            f"[MuftyKare] Required environment variable '{key}' is not set. "
            f"Check your .env file."
        )
    return val


def _optional(key: str, default: str = "") -> str:
    """Get optional env var with default."""
    return os.getenv(key, default)


# ── LiveKit ────────────────────────────────────────────────────────────────
LIVEKIT_URL         = _require("LIVEKIT_URL")
LIVEKIT_API_KEY     = _require("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET  = _require("LIVEKIT_API_SECRET")

# ── AI providers ──────────────────────────────────────────────────────────
OPENAI_API_KEY      = _require("OPENAI_API_KEY")
SARVAM_API_KEY      = _require("SARVAM_API_KEY")

# ── Database ──────────────────────────────────────────────────────────────
DATABASE_URL        = _require("DATABASE_URL")

# ── SIP / Telephony ────────────────────────────────────────────────────────
# Optional during development — required for production phone calls
PLIVO_AUTH_ID       = _optional("PLIVO_AUTH_ID")
PLIVO_AUTH_TOKEN    = _optional("PLIVO_AUTH_TOKEN")
PLIVO_PHONE_NUMBER  = _optional("PLIVO_PHONE_NUMBER")

# SIP outbound trunk ID (from LiveKit dashboard) — required for outbound calls
SIP_OUTBOUND_TRUNK_ID = _optional("SIP_OUTBOUND_TRUNK_ID")

# Manager phone number for WarmTransfer escalation
MANAGER_PHONE       = _optional("MANAGER_PHONE", "7075232425")

# ── Language ───────────────────────────────────────────────────────────────
# Which language the agent speaks/listens in for this deployment.
# "te-IN" (Telugu, default) or "en-IN" (English).
AGENT_LANGUAGE      = _optional("AGENT_LANGUAGE", "te-IN").strip()

# ── Application ────────────────────────────────────────────────────────────
LOG_LEVEL           = _optional("LOG_LEVEL", "INFO")
LOG_DIR             = _optional("LOG_DIR", "logs")
FASTAPI_PORT        = int(_optional("FASTAPI_PORT", "8000"))

# Agent name registered in LiveKit dashboard
AGENT_NAME          = _optional("AGENT_NAME", "muftykare-agent")
