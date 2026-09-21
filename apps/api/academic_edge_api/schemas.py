"""Pydantic v2 response contracts for every ``/v1`` endpoint.

These schemas are the API contract: the Next.js client must mirror them (the
platform brief explicitly ships them to the frontend). Nothing here exposes a
secret, a raw provider passthrough or an unlabelled synthetic row -- every
object that can hold provider data carries ``is_synthetic``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from academic_edge_domain.enums import (
    AlertSeverity,
    AlertStatus,
    DeVigMethod,
    FreshnessLabel,
    LedgerStatus,
    MarketPeriod,
    MarketType,
    OpportunityType,
    OutcomeKind,
    ReviewStatus,
    TeamScope,
    VenueKind,
)
from pydantic import BaseModel, Field


class SourceHealthOut(BaseModel):
    """One row of GET /v1/sources/health."""

    source_id: str = Field(description="Source id from the policy registry.")
    display_name: str = Field(description="Human-readable provider name.")
    ok: bool = Field(description="The most recent health check passed.")
    mode: Literal["live", "fixture"] = Field(description="How this source is running.")
    checked_at: dt.datetime = Field(description="UTC timestamp of the check.")
    latency_ms: int | None = Field(default=None, description="Adapter latency.")
    quota_used: int | None = Field(default=None, description="Consumed quota, if reported.")
    quota_limit: int | None = Field(default=None, description="Quota ceiling, if known.")
    parser_drift: bool = Field(default=False, description="A payload disagreed with the contract.")
    message: str | None = Field(default=None, description="Human-readable detail.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "source_id": "api_football",
                "display_name": "API-Football (api-sports.io)",
                "ok": True,
                "mode": "fixture",
                "checked_at": "2026-09-15T12:00:00Z",
                "latency_ms": 3,
                "quota_used": None,
                "quota_limit": 100,
                "parser_drift": False,
                "message": "fixture mode: labelled frozen payload",
            }
        }
    }


class EventOut(BaseModel):
    """Canonical event for GET /v1/events and /v1/events/{id}."""

    id: uuid.UUID
    sport: str = Field(default="football")
    competition: str = Field(description="Canonical competition name.")
    season: str | None = Field(default=None)
    home: str = Field(description="Canonical home participant.")
    away: str = Field(description="Canonical away participant.")
    venue: str | None = Field(default=None)
    start_time_utc: dt.datetime = Field(description="Kickoff, UTC.")
    status: str = Field(description="scheduled | live | finished | ...")
    round_label: str | None = Field(default=None)
    home_score: int | None = Field(default=None)
    away_score: int | None = Field(default=None)
    is_synthetic: bool
    provider_ids: dict[str, str] = Field(
        default_factory=dict, description="source_id -> provider event id."
    )

    model_config = {"extra": "forbid"}


class MarketOut(BaseModel):
    """Canonical market definition for GET /v1/markets."""

    id: uuid.UUID
    event_id: uuid.UUID
    market_type: MarketType
    period: MarketPeriod
    line_value: str = Field(description="Decimal as string; 0 for line-less markets.")
    team_scope: TeamScope
    overtime_included: bool
    settlement_version: str
    identity_key: str = Field(description="The canonical identity hash input.")
    settlement_rule: str = Field(description="Exact settlement rule shown on every alert.")
    display_name: str
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class OutcomeOut(BaseModel):
    """One side of a market."""

    id: uuid.UUID
    market_id: uuid.UUID
    outcome_kind: OutcomeKind
    label: str

    model_config = {"extra": "forbid"}


class QuoteOut(BaseModel):
    """One observed price for GET /v1/quotes/latest.

    Provenance is mandatory, not optional: ``observed_at``, ``age_seconds``,
    ``latency_ms`` and ``freshness`` let any consumer decide whether a number
    is still trustworthy.
    """

    id: uuid.UUID
    market_id: uuid.UUID
    outcome_id: uuid.UUID
    outcome_kind: OutcomeKind
    source_id: str
    venue_kind: VenueKind
    venue_name: str
    decimal_odds: str = Field(description="Decimal odds as string.")
    available_size: str = Field(default="0", description="Quoted size, as string.")
    currency: str = Field(default="EUR")
    observed_at: dt.datetime = Field(description="When we saw it, UTC.")
    age_seconds: float = Field(description="Seconds between observed_at and now.")
    provider_timestamp: dt.datetime | None = Field(default=None)
    latency_ms: int | None = Field(default=None)
    freshness: FreshnessLabel
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class QuoteSnapshotOut(BaseModel):
    """Point-in-time aggregate behind the odds timeline."""

    outcome_id: uuid.UUID
    outcome_kind: OutcomeKind
    as_of: dt.datetime
    best_decimal_odds: str
    best_source_id: str
    implied_probability: str
    fair_probability: str | None = Field(default=None)
    de_vig_method: DeVigMethod | None = Field(default=None)
    overround: str | None = Field(default=None)
    quote_count: int
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class OpportunityLegOut(BaseModel):
    """One leg of an opportunity: where it is, what it pays, how old it is."""

    outcome_kind: OutcomeKind
    label: str
    source_id: str
    venue_name: str
    decimal_odds: str
    stake: str = Field(description="Equalised stake, as string.")
    payoff: str = Field(description="Equalised payoff, as string.")
    age_seconds: float
    freshness: FreshnessLabel
    available_size: str = Field(default="0")

    model_config = {"extra": "forbid"}


class OpportunityOut(BaseModel):
    """A detected signal with the evidence that caused it."""

    id: uuid.UUID
    event_id: uuid.UUID
    market_id: uuid.UUID
    opportunity_type: OpportunityType
    is_actionable: bool = Field(description="False means: read the reasons.")
    net_edge_bps: int
    gross_edge_bps: int
    confidence: float
    best_legs: list[OpportunityLegOut]
    friction: dict[str, Any] = Field(description="Cost breakdown per leg.")
    de_vig_method: DeVigMethod | None = Field(default=None)
    model_probability: str | None = Field(default=None)
    model_version: str | None = Field(default=None, description="name@version.")
    uncertainty: float | None = Field(default=None)
    total_stake: str
    expected_profit: str
    currency: str
    detected_at: dt.datetime
    expires_at: dt.datetime | None = Field(default=None)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    settlement_rule: str = Field(description="The rule pinned to this market.")
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class ReviewItemOut(BaseModel):
    """One row of the resolver review queue."""

    map_id: uuid.UUID
    source_id: str
    provider_event_id: str
    competition: str
    candidate_home: str
    candidate_away: str
    candidate_start_time_utc: dt.datetime
    matched_event_id: uuid.UUID | None = Field(default=None)
    score: str = Field(description="Match score, decimal as string.")
    status: ReviewStatus
    hard_rejects: list[str] = Field(default_factory=list)
    component_scores: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ReviewDecisionIn(BaseModel):
    """Analyst decision on a review item."""

    action: Literal["accept", "reject"] = Field(description="Link to the match, or reject.")
    note: str | None = Field(default=None, description="Why, in one sentence.")

    model_config = {"extra": "forbid"}


class PredictionOut(BaseModel):
    """Model probability for one outcome."""

    event_id: uuid.UUID
    model: str = Field(description="Model name@version.")
    market_type: MarketType
    outcome_kind: OutcomeKind
    probability: str
    fair_odds: str
    uncertainty: float | None = Field(default=None)
    abstained: bool
    abstain_reason: str | None = Field(default=None)
    market_free: bool
    as_of: dt.datetime
    explanation: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class ModelMetricsOut(BaseModel):
    """Walk-forward metrics for one registered model."""

    model: str = Field(description="Model name@version.")
    algorithm: str
    trained_at: dt.datetime
    train_window: dict[str, str | None]
    calibration_window: dict[str, str | None]
    metrics: dict[str, Any] = Field(
        description="log_loss, brier, rps, ece, clv, net_roi, turnover, max_drawdown..."
    )
    is_active: bool
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class AlertOut(BaseModel):
    """A rule firing, snapshotting its evidence."""

    id: uuid.UUID
    rule: str = Field(description="The alert rule name.")
    event_id: uuid.UUID
    market_id: uuid.UUID | None = Field(default=None)
    opportunity_id: uuid.UUID | None = Field(default=None)
    status: AlertStatus
    severity: AlertSeverity
    message: str
    raised_at: dt.datetime
    evidence: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class AlertAcknowledgeIn(BaseModel):
    """Analyst acknowledgement."""

    note: str | None = Field(default=None)

    model_config = {"extra": "forbid"}


class PaperLedgerOut(BaseModel):
    """A paper-trading entry. Research only: no real stake exists."""

    id: uuid.UUID
    event_id: uuid.UUID
    market_id: uuid.UUID
    outcome_id: uuid.UUID
    source_id: str
    stake: str
    decimal_odds: str
    currency: str
    status: LedgerStatus
    placed_at: dt.datetime
    settled_at: dt.datetime | None = Field(default=None)
    pnl: str | None = Field(default=None)
    is_synthetic: bool

    model_config = {"extra": "forbid"}


class HealthOut(BaseModel):
    """GET /v1/health."""

    ok: bool
    env: str
    fixture_mode: bool = Field(description="True when no live credentials exist.")
    dev_auth: bool = Field(description="True when API_KEYS is empty (dev mode).")
    database: str = Field(description="ok | degraded.")
    time_utc: dt.datetime

    model_config = {"extra": "forbid"}
