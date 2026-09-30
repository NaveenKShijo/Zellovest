"""Structured JSON logging configuration (structlog + stdlib).

All services share this configuration for consistent, parseable logs.
"""

import logging
import sys
from typing import Any

import structlog


def _add_service_name(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Add service name to all log entries."""
    import os
    event_dict["service"] = os.getenv("SERVICE_NAME", "zellovest")
    return event_dict


def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """Configure structlog for JSON output with service context.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON lines; else console-friendly.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        _add_service_name,
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level.upper())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)