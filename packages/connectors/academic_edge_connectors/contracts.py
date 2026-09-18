"""Canonical connector DTOs shared by every provider adapter.

FROZEN-CONTRACT NOTE
--------------------
``base.py`` in this package is owned by the domain team and is treated here as a
frozen contract.  As delivered it defines ``Provenance`` and ``ProviderEvent``
and stops there, so the ``ProviderMarket`` DTO and the ``ProviderAdapter``
protocol that the connector layer needs are added *in this module* rather than by
editing that file.  ``Provenance``, ``ProviderEvent`` and the exception hierarchy
are re-exported below so consumers have a single import path::

    from academic_edge_connectors.contracts import ProviderAdapter, ProviderMarket

If ``base.py`` later regains those definitions, reduce this module to a
re-export; no adapter code has to change.

Conventions the DTOs enforce (the pricing layer depends on all three):

* ``decimal_odds`` is *decimal* odds and is always ``> 1.0``; ``1.0`` is not a
  price.  Adapters raise :class:`ParserDriftError` when a provider sends
  something unusable; the DTO raises :class:`ConnectorError` if a caller
  constructs a broken record directly.
* every timestamp is timezone-aware UTC (``academic_edge_domain.time``).
* ``is_synthetic`` is ``True`` for anything produced from fixtures or from a
  synthetic source and is surfaced to the UI unchanged.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from academic_edge_domain.enums import (
    MarketPeriod,
    MarketType,
    OutcomeKind,
    TeamScope,
    VenueKind,
)
from academic_edge_domain.time import ensure_utc

from academic_edge_connectors.base import (
    AdapterUnavailable,
    ConnectorError,
    ParserDriftError,
    Provenance,
    ProviderEvent,
    ProviderRateLimited,
)

__all__ = [
    "AdapterUnavailable",
    "ConnectorError",
    "HealthReport",
    "ParserDriftError",
    "Provenance",
    "ProviderAdapter",
    "ProviderEvent",
    "ProviderMarket",
    "ProviderOutcome",
    "ProviderRateLimited",
    "ProviderUpdate",
    "build_provenance",
]

ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    """One priced selection of a provider market, in canonical vocabulary.

    ``available_size`` is the depth the venue actually showed for that price
    (CLOB book level size, provider stake limit, ...).  ``None`` means *unknown*
    - never ``0`` - so the pricing layer can tell "no liquidity data" apart from
    "nothing available".  ``quoted_at`` is when the venue's price was observed
    and is what the staleness rules key off; ``None`` means the provider gave us
    no price timestamp and callers must not assume freshness.
    """

    provider_outcome_id: str
    outcome_kind: OutcomeKind
    decimal_odds: Decimal
    available_size: Decimal | None = None
    quoted_at: dt.datetime | None = None
    currency: str | None = None
    is_synthetic: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decimal_odds <= ONE:
            raise ConnectorError(
                f"outcome {self.provider_outcome_id!r}: decimal odds must be > 1.0, "
                f"got {self.decimal_odds}"
            )
        if self.available_size is not None and self.available_size < 0:
            raise ConnectorError(
                f"outcome {self.provider_outcome_id!r}: available_size cannot be negative"
            )
        if self.quoted_at is not None:
            object.__setattr__(self, "quoted_at", ensure_utc(self.quoted_at))

    @property
    def implied_probability(self) -> Decimal:
        """Raw ``1 / decimal_odds`` (still contains any venue margin)."""
        return ONE / self.decimal_odds

    def age_seconds(self, now: dt.datetime) -> float | None:
        """Seconds since ``quoted_at``, or ``None`` when the quote has no time."""
        if self.quoted_at is None:
            return None
        return (ensure_utc(now) - self.quoted_at).total_seconds()

    def is_stale(self, *, now: dt.datetime, max_age_seconds: float) -> bool:
        """True only when we *know* the quote is older than the allowed age."""
        age = self.age_seconds(now)
        return age is not None and age > max_age_seconds


@dataclass(frozen=True, slots=True)
class ProviderMarket:
    """A market as one venue describes it (pre-resolution, pre-de-vig).

    ``outcomes`` may be a *partial* set - a prediction market that only lists
    "Yes" for "will team A win?" contributes a single ``HOME``/``AWAY`` outcome
    to the FT_1X2 family and nothing else.  Adapters must never synthesise the
    missing legs to fill a market out.
    """

    provider_market_id: str
    provider_event_id: str
    venue_name: str
    venue_kind: VenueKind
    market_type: MarketType
    outcomes: tuple[ProviderOutcome, ...] = ()
    period: MarketPeriod = MarketPeriod.FULL_TIME
    team_scope: TeamScope = TeamScope.NEUTRAL
    line: Decimal | None = None
    observed_at: dt.datetime | None = None
    is_synthetic: bool = False
    provenance: Provenance | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))

    def outcome(self, kind: OutcomeKind) -> ProviderOutcome | None:
        """First outcome of ``kind``, or ``None`` when the venue did not quote it."""
        for candidate in self.outcomes:
            if candidate.outcome_kind is kind:
                return candidate
        return None

    def outcomes_by_kind(self) -> dict[OutcomeKind, ProviderOutcome]:
        return {outcome.outcome_kind: outcome for outcome in self.outcomes}

    @property
    def kinds(self) -> frozenset[OutcomeKind]:
        return frozenset(outcome.outcome_kind for outcome in self.outcomes)

    def best_odds(self) -> Decimal | None:
        """Highest price this venue offered for the market, or ``None`` if empty."""
        if not self.outcomes:
            return None
        return max(outcome.decimal_odds for outcome in self.outcomes)

    def oldest_quoted_at(self) -> dt.datetime | None:
        """Oldest known quote time across outcomes (``None`` if none are known)."""
        known = [o.quoted_at for o in self.outcomes if o.quoted_at is not None]
        return min(known) if known else None

    def is_stale(self, *, now: dt.datetime, max_age_seconds: float) -> bool:
        """True when *any* quoted outcome is older than ``max_age_seconds``."""
        return any(
            outcome.is_stale(now=now, max_age_seconds=max_age_seconds) for outcome in self.outcomes
        )


@dataclass(frozen=True, slots=True)
class ProviderUpdate:
    """One observation produced by a streaming/polling adapter."""

    provider_event_id: str
    observed_at: dt.datetime
    markets: tuple[ProviderMarket, ...] = ()
    event: ProviderEvent | None = None
    sequence: int | None = None
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Result of a read-only provider health probe.

    Quota fields stay ``None`` when the provider does not report them; ``0`` is a
    real value ("no calls left"), so the two are never conflated.
    """

    source_id: str
    ok: bool
    mode: str
    checked_at: dt.datetime
    latency_ms: int | None = None
    quota_limit: int | None = None
    quota_remaining: int | None = None
    quota_reset: dt.datetime | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", ensure_utc(self.checked_at))
        if self.quota_reset is not None:
            object.__setattr__(self, "quota_reset", ensure_utc(self.quota_reset))

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe summary for the API health endpoint."""
        return {
            "source_id": self.source_id,
            "ok": self.ok,
            "mode": self.mode,
            "checked_at": self.checked_at.isoformat(),
            "latency_ms": self.latency_ms,
            "quota_limit": self.quota_limit,
            "quota_remaining": self.quota_remaining,
            "quota_reset": self.quota_reset.isoformat() if self.quota_reset else None,
            "is_synthetic": self.is_synthetic,
            "detail": dict(self.detail),
        }


def build_provenance(
    *,
    source_id: str,
    endpoint: str,
    observed_at: dt.datetime,
    received_at: dt.datetime | None = None,
    provider_timestamp: dt.datetime | None = None,
    latency_ms: int | None = None,
    http_status: int | None = None,
    raw_bytes: bytes | None = None,
    raw_content_type: str = "application/json",
    is_synthetic: bool = False,
    redacted: bool = False,
    redaction_notes: str | None = None,
) -> Provenance:
    """Build :class:`Provenance` with every timestamp normalised to UTC."""
    return Provenance(
        source_id=source_id,
        endpoint=endpoint,
        observed_at=ensure_utc(observed_at),
        received_at=ensure_utc(received_at if received_at is not None else observed_at),
        provider_timestamp=(
            ensure_utc(provider_timestamp) if provider_timestamp is not None else None
        ),
        latency_ms=latency_ms,
        http_status=http_status,
        raw_bytes=raw_bytes,
        raw_content_type=raw_content_type,
        is_synthetic=is_synthetic,
        redacted=redacted,
        redaction_notes=redaction_notes,
    )


@runtime_checkable
class ProviderAdapter(Protocol):
    """The connector contract every adapter in this package implements.

    Adapters are read-only, never touch the database and return already
    canonicalised DTOs plus provenance.  ``mode`` is ``"live"`` or ``"fixture"``;
    a ``"fixture"`` adapter must never open a socket.
    """

    source_id: str
    mode: str

    def discover_events(
        self,
        *,
        window_start: dt.datetime | None = None,
        window_end: dt.datetime | None = None,
        competition_code: str | None = None,
        limit: int | None = None,
    ) -> list[ProviderEvent]:
        """List events in a window (provider-specific default when both are None)."""
        ...

    def fetch_event(self, provider_event_id: str) -> ProviderEvent | None:
        """Fetch one event, or ``None`` when the provider has no such event."""
        ...

    def fetch_markets(self, provider_event_id: str) -> list[ProviderMarket]:
        """Fetch priced markets for one event (empty list when unsupported)."""
        ...

    def stream_updates(
        self,
        *,
        interval_seconds: float | None = None,
        max_iterations: int | None = None,
    ) -> Iterator[ProviderUpdate]:
        """Yield polling observations; bounded by ``max_iterations`` when set."""
        ...

    def healthcheck(self) -> HealthReport:
        """Read-only probe; never raises for provider-side failures."""
        ...

    def close(self) -> None:
        """Release any underlying HTTP resources."""
        ...
