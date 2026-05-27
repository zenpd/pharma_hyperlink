"""structlog configuration.

Emits JSON-formatted structured logs by default (ready for Splunk / Elastic).
Console mode is available for local development.

Usage:
    from hyperlink_engine.config.logging_setup import configure_logging, get_logger
    configure_logging()  # call once at process start
    log = get_logger(__name__)
    log.info("link_injected", doc="m2.5.docx", count=42)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from hyperlink_engine.config.settings import get_settings


def _add_app_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Inject app-wide context into every log line."""
    event_dict.setdefault("app", "hyperlink-engine")
    return event_dict


def configure_logging() -> None:
    """Configure structlog + stdlib logging based on settings.

    Idempotent — safe to call multiple times.
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_app_context,
    ]

    if settings.log_format == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger; configures lazily if not already configured."""
    if not structlog.is_configured():
        configure_logging()
    return structlog.get_logger(name)
