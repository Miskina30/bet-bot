"""Structured logging helpers: JSON logs with correlation ids."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from academic_edge_domain.time import utcnow

logger = logging.getLogger("academic_edge")


def new_correlation_id() -> str:
    """One id per request, propagated to every log line and AuditLog row."""
    return uuid.uuid4().hex[:16]


def log_event(
    level: int,
    message: str,
    *,
    correlation_id: str | None = None,
    source: str | None = None,
    event_id: str | None = None,
    latency_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a single-line JSON log record."""
    record: dict[str, Any] = {
        "ts": utcnow().isoformat(),
        "level": logging.getLevelName(level),
        "message": message,
        "correlation_id": correlation_id,
        "source": source,
        "event_id": event_id,
        "latency_ms": latency_ms,
    }
    if extra:
        record.update(extra)
    logger.log(level, json.dumps(record, default=str))


class Timer:
    """``with Timer() as timer: ...`` then ``timer.elapsed_ms``."""

    def __init__(self) -> None:
        self._start = time.monotonic()
        self.elapsed_ms: int = 0

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)


def configure_logging(level: str = "INFO") -> None:
    """Plain-text handler at the root; JSON lives in the message payload."""
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))