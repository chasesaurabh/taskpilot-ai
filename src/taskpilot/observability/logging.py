"""Structured logging and optional LangSmith environment setup."""

from __future__ import annotations

import logging
import os

import structlog


def configure_observability(*, log_level: str, langsmith_enabled: bool) -> None:
    """Configure JSON logs and the LangChain/LangGraph tracing integration."""

    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level, force=True)
    structlog.configure(
        processors=(
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    os.environ["LANGSMITH_TRACING"] = "true" if langsmith_enabled else "false"
