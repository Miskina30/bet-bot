"""Provider adapter contract (brief: ARCHITECTURE / provider adapters).

Every connector implements :class:`ProviderAdapter`:

    discover_events, fetch_event, fetch_markets, stream_updates, healthcheck

Adapters return provider-shaped, already-canonicalised DTOs (dataclasses below).
They deliberately do NOT touch the database and do NOT resolve entities: they
translate bytes into records plus provenance. The worker owns persistence,
resolution and pricing.

Two properties matter for safety and testability:

* Every DTO carries ``observed_at``/``provider_timestamp`` and ``raw_bytes`` so
  the pipeline can archive exactly what was received.
* Adapters are constructed with an explicit ``mode`` (``live`` | ``fixture``).
  ``live`` goes through the source-policy gate first; ``fixture`` reads labelled
  local payloads and never opens a socket.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


class ConnectorError(RuntimeError):
    """Base class for adapter failures."""


class AdapterUnavailable(ConnectorError):  # noqa: N818  (public API name, kept stable)
    """Credentials, network or vendor availability prevent the call."""


class ProviderRateLimited(ConnectorError):  # noqa: N818  (public API name, kept stable)
    """Provider signalled a rate limit; the caller must back off (never bypass)."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ParserDriftError(ConnectorError):
    """A payload no longer matches the frozen contract fixture.

    Raised instead of silently inventing a field (brief: "Never invent provider
    fields"). Raw bytes are still archived so the drift stays diagnosable.
    """


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a record came from and when we saw it."""

    source_id: str
    endpoint: str
    observed_at: dt.datetime
    received_at: dt.datetime
    provider_timestamp: dt.datetime | None = None
    latency_ms: int | None = None
    http_status: int | None = None
    raw_bytes: bytes | None = None
    raw_content_type: str = "application/json"
    is_synthetic: bool = False
    redacted: bool = False
    redaction_notes: str | None = None

    @property
    def latency_seconds(self) -> float | None:
        if self.latency_ms is None:
            return None
        return self.latency_ms / 1000.0


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """A fixture as the provider describes it (pre-resolution)."""

    provider_event_id: str
    competition_name: str
    competition_provider_id: str | None
    home_name: str
    away_name: str
    start_time_utc: dt.datetime
    home_provider_id: str | None = None
    away_provider_id: str | None = None
    venue_name: str | None = None
    country: str | None = None
    season_label: str | None = None
    round_label: str | None = None
    status: str = "scheduled"
    home_score: int | None = None
    away_score: int | None = None
    provider_home_away_order_trusted: bool = True
    provenance: Provenance | None = None
    extras: dict[str, Any] = field(default_factory=dict)
