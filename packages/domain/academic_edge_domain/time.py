"""UTC time handling.

Rule (brief, ARCHITECTURE): *all* timestamps are UTC. Providers send naive local
strings, epoch seconds, epoch milliseconds and ISO strings with random offsets.
Everything is normalised here so the rest of the system can assume
``datetime`` objects that are timezone-aware and in UTC.

SQLite does not preserve tzinfo, so :class:`UtcDateTime` re-attaches UTC on load.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

UTC = dt.UTC


class TimestampParseError(ValueError):
    """Raised when a provider timestamp cannot be interpreted unambiguously."""


def utcnow() -> dt.datetime:
    """Timezone-aware ``now`` in UTC (single clock source for the codebase)."""
    return dt.datetime.now(tz=UTC)


def ensure_utc(value: dt.datetime) -> dt.datetime:
    """Return ``value`` as an aware UTC datetime.

    Naive datetimes are *assumed* to be UTC. That assumption is safe here because
    every naive value in the system originated from one of our own UTC writers or
    from :func:`parse_timestamp`, which never returns naive values.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_timestamp(raw: Any) -> dt.datetime:
    """Parse a provider timestamp into an aware UTC datetime.

    Accepts: aware/naive datetime, ISO-8601 (with ``Z`` or offset), and epoch
    seconds/milliseconds (int, float or numeric string). Anything else raises
    :class:`TimestampParseError` -- we never silently guess ("never invent
    provider fields").
    """
    if isinstance(raw, dt.datetime):
        return ensure_utc(raw)

    if isinstance(raw, bool):  # bool is an int subclass; reject explicitly
        raise TimestampParseError(f"unsupported timestamp type: {type(raw)!r}")

    if isinstance(raw, (int, float)):
        return _from_epoch(float(raw))

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise TimestampParseError("empty timestamp string")
        try:
            return _from_epoch(float(text))
        except ValueError:
            pass
        candidate = text.replace("Z", "+00:00") if text.endswith(("Z", "z")) else text
        try:
            return ensure_utc(dt.datetime.fromisoformat(candidate))
        except ValueError as exc:  # try a couple of documented provider formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M"):
                try:
                    parsed = dt.datetime.strptime(text, fmt)
                except ValueError:
                    continue
                return ensure_utc(parsed)
            raise TimestampParseError(f"cannot parse timestamp {raw!r}") from exc

    raise TimestampParseError(f"unsupported timestamp type: {type(raw)!r}")


def _from_epoch(value: float) -> dt.datetime:
    """Epoch seconds, epoch milliseconds, or epoch microseconds."""
    magnitude = abs(value)
    if magnitude >= 1e17:  # nanoseconds
        seconds = value / 1e9
    elif magnitude >= 1e14:  # microseconds
        seconds = value / 1e6
    elif magnitude >= 1e11:  # milliseconds
        seconds = value / 1e3
    else:
        seconds = value
    try:
        return dt.datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimestampParseError(f"epoch value out of range: {value!r}") from exc


def seconds_between(later: dt.datetime, earlier: dt.datetime) -> float:
    """Signed seconds from ``earlier`` to ``later``, both normalised to UTC."""
    return (ensure_utc(later) - ensure_utc(earlier)).total_seconds()


class UtcDateTime(TypeDecorator[dt.datetime]):
    """``DateTime(timezone=True)`` that always round-trips as aware UTC.

    ``cache_ok = True`` is safe: the type has no mutable state.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Dialect) -> dt.datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    def process_result_value(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        return ensure_utc(value)
