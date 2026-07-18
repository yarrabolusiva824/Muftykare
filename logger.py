"""
logger.py — Centralised logging for MuftyKare voice agent.

Every module calls:
    from logger import get_logger
    logger = get_logger(__name__)

Call setup_logging() ONCE at the very top of agent.py and server.py
before any other imports.
"""
import logging
import logging.handlers
import os
from datetime import datetime, timezone, timedelta

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


def setup_logging(log_dir: str = "logs", log_level: str = "INFO") -> None:
    """
    Configure logging for the entire application.
    Call once at startup — idempotent (safe to call multiple times).

    Outputs:
    - Console: human-readable, INFO+
    - File:    JSON structured, DEBUG+, daily rotating, 30-day retention
               logs/muftykare_YYYY-MM-DD.log
    """
    # Idempotency — don't add handlers twice
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # Create logs directory
    os.makedirs(log_dir, exist_ok=True)

    # ── Console handler ────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    # ── Daily rotating file handler ────────────────────────────────────────
    log_file_base = os.path.join(log_dir, "muftykare.log")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file_base,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )

    # Rename rotated files to muftykare_YYYY-MM-DD.log
    def namer(default_name: str) -> str:
        # default_name is like "logs/muftykare.log.2024-01-15"
        # we want "logs/muftykare_2024-01-15.log"
        parts = default_name.rsplit(".", 1)
        if len(parts) == 2:
            return parts[0].replace(".log", "") + "_" + parts[1] + ".log"
        return default_name

    file_handler.namer = namer
    file_handler.setLevel(logging.DEBUG)

    # JSON formatter
    try:
        from pythonjsonlogger import jsonlogger

        class _ISTJsonFormatter(jsonlogger.JsonFormatter):
            """Injects IST-localised timestamps and flattens extra= kwargs."""

            def add_fields(
                self,
                log_record: dict,
                record: logging.LogRecord,
                message_dict: dict,
            ) -> None:
                super().add_fields(log_record, record, message_dict)
                now_ist = datetime.fromtimestamp(record.created, tz=IST)
                log_record["timestamp"] = now_ist.isoformat(timespec="milliseconds")
                log_record["level"] = record.levelname
                log_record["logger"] = record.name
                for key in ("levelname", "asctime", "name"):
                    log_record.pop(key, None)

        file_formatter: logging.Formatter = _ISTJsonFormatter(
            fmt="%(timestamp)s %(level)s %(logger)s %(message)s",
        )
    except ImportError:
        # Fallback if python-json-logger not installed
        file_formatter = logging.Formatter(
            fmt='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    file_handler.setFormatter(file_formatter)

    root.addHandler(console)
    root.addHandler(file_handler)

    # ── Suppress noisy third-party loggers ─────────────────────────────────
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("livekit").setLevel(logging.INFO)   # keep LiveKit INFO
    logging.getLogger("sarvam").setLevel(logging.INFO)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)  # watches its own log file — very noisy


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger. Call at the top of every module.

    Usage:
        from logger import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
