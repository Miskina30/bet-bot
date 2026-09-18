"""Canonical SQLAlchemy model (brief: CANONICAL MODEL).

Design rules enforced here:
* Every row carries UTC timestamps (``UtcDateTime``).
* Enum-typed columns use ``native_enum=False`` so Postgres 16, SQLite and CI all
  behave identically, and adding a value never needs DDL.
* Synthetic (fixture-derived) rows are explicitly flagged ``is_synthetic`` so
  fixture data can never masquerade as a live market.
* Relationships are expressed as foreign keys plus explicit service queries --
  no lazy-loading surprises in web handlers or graders.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from academic_edge_domain.db import Base
from academic_edge_domain.enums import (
    AlertSeverity,
    AlertStatus,
    AuditAction,
    AutomationScope,
    DeVigMethod,
    FreshnessLabel,
    LedgerStatus,
    MarketPeriod,
    MarketType,
    OpportunityType,
    OutcomeKind,
    ReviewStatus,
    Role,
    SettlementStatus,
    SourceTier,
    Sport,
    TeamScope,
    VenueKind,
)
from academic_edge_domain.ids import new_id
from academic_edge_domain.time import UtcDateTime, utcnow

ODDS = Numeric(18, 6)
PROBABILITY = Numeric(12, 9)
MONEY = Numeric(18, 6)
RATE = Numeric(9, 6)


def enum_column(enum_cls: type[Any], *, length: int = 32) -> Enum[Any]:
    """Portable enum column: stored as VARCHAR, validated on the way in."""
    return Enum(enum_cls, native_enum=False, length=length, validate_strings=True)


class TimestampMixin:
    """``created_at``/``updated_at`` in UTC for every canonical entity."""

    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class SportRow(TimestampMixin, Base):
    """Canonical sport. Modelled as a table so FK integrity is real, not implicit."""

    __tablename__ = "sport"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    code: Mapped[Sport] = mapped_column(enum_column(Sport), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class Competition(TimestampMixin, Base):
    __tablename__ = "competition"
    __table_args__ = (
        UniqueConstraint("sport_id", "canonical_key", name="uq_competition_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sport.id"), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country: Mapped[str | None] = mapped_column(String(80))
    provider_tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Season(TimestampMixin, Base):
    __tablename__ = "season"
    __table_args__ = (UniqueConstraint("competition_id", "label", name="uq_season_label"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competition.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_on: Mapped[dt.date | None] = mapped_column(nullable=True)
    ends_on: Mapped[dt.date | None] = mapped_column(nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Venue(TimestampMixin, Base):
    __tablename__ = "venue"
    __table_args__ = (UniqueConstraint("canonical_key", name="uq_venue_canonical_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class Participant(TimestampMixin, Base):
    """A team (later: a player). Home/away is an *event* property, not a team's."""

    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint("sport_id", "canonical_key", name="uq_participant_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sport.id"), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="team", nullable=False)
    country: Mapped[str | None] = mapped_column(String(80))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ParticipantAlias(TimestampMixin, Base):
    """Provider/alternate spellings that resolve onto a canonical participant."""

    __tablename__ = "participant_alias"
    __table_args__ = (
        UniqueConstraint("alias_normalized", "source_id", name="uq_alias_source"),
        Index("ix_participant_alias_lookup", "alias_normalized"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participant.id"), nullable=False)
    alias_raw: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    created_by: Mapped[str] = mapped_column(String(64), default="system", nullable=False)


class Event(TimestampMixin, Base):
    """One canonical fixture. ``start_time_utc`` is kickoff, always UTC."""

    __tablename__ = "event"
    __table_args__ = (
        Index("ix_event_start_time", "start_time_utc"),
        Index("ix_event_competition_start", "competition_id", "start_time_utc"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sport.id"), nullable=False)
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competition.id"), nullable=False)
    season_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("season.id"))
    home_participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("participant.id"), nullable=False
    )
    away_participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("participant.id"), nullable=False
    )
    venue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("venue.id"))
    start_time_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", nullable=False)
    round_label: Mapped[str | None] = mapped_column(String(64))
    home_score: Mapped[int | None] = mapped_column()
    away_score: Mapped[int | None] = mapped_column()
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProviderEventMap(TimestampMixin, Base):
    """Cross-provider identity link plus the evidence that produced it."""

    __tablename__ = "provider_event_map"
    __table_args__ = (
        UniqueConstraint("source_id", "provider_event_id", name="uq_provider_event"),
        Index("ix_provider_event_map_review", "review_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_competition_id: Mapped[str | None] = mapped_column(String(64))
    provider_home_id: Mapped[str | None] = mapped_column(String(64))
    provider_away_id: Mapped[str | None] = mapped_column(String(64))
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus), default=ReviewStatus.AUTO_ACCEPTED, nullable=False
    )
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    hard_reject_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    decided_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_payload.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Market(TimestampMixin, Base):
    """A canonical market definition -- the thing two providers must agree on.

    Identity (brief, CANONICAL MODEL) = event + market_type + period + line_value
    + team_scope + overtime_included + settlement_version.

    ``line_value`` is ``0`` (not NULL) for line-less markets so the unique
    constraint actually bites on both Postgres and SQLite, where NULL never
    compares equal and would silently permit duplicate markets.
    """

    __tablename__ = "market"
    __table_args__ = (
        UniqueConstraint("event_id", "identity_key", name="uq_market_identity"),
        Index("ix_market_event_type", "event_id", "market_type"),
        CheckConstraint("line_value >= 0", name="ck_market_line_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sport.id"), nullable=False)
    market_type: Mapped[MarketType] = mapped_column(enum_column(MarketType), nullable=False)
    period: Mapped[MarketPeriod] = mapped_column(
        enum_column(MarketPeriod), default=MarketPeriod.FULL_TIME, nullable=False
    )
    line_value: Mapped[Decimal] = mapped_column(ODDS, default=Decimal("0"), nullable=False)
    team_scope: Mapped[TeamScope] = mapped_column(
        enum_column(TeamScope), default=TeamScope.NEUTRAL, nullable=False
    )
    overtime_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    settlement_version: Mapped[str] = mapped_column(String(24), default="v1", nullable=False)
    identity_key: Mapped[str] = mapped_column(String(200), nullable=False)
    settlement_rule: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Outcome(TimestampMixin, Base):
    """One selectable side of a market (home/draw/away, over/under, yes/no)."""

    __tablename__ = "outcome"
    __table_args__ = (
        UniqueConstraint("market_id", "outcome_kind", name="uq_outcome_kind"),
        CheckConstraint("label <> ''", name="ck_outcome_label_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    outcome_kind: Mapped[OutcomeKind] = mapped_column(enum_column(OutcomeKind), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)


class Quote(TimestampMixin, Base):
    """An observed price for one outcome at one venue.

    Provenance is mandatory (brief, SAFETY #5): source, observed_at,
    provider_timestamp, received_at, latency and freshness all live here so the
    UI can show age and latency for every number it renders.
    """

    __tablename__ = "quote"
    __table_args__ = (
        Index("ix_quote_market_observed", "market_id", "observed_at"),
        Index("ix_quote_outcome_observed", "outcome_id", "observed_at"),
        Index("ix_quote_source_observed", "source_id", "observed_at"),
        CheckConstraint("decimal_odds > 1.0", name="ck_quote_odds_above_one"),
        CheckConstraint("available_size >= 0", name="ck_quote_size_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcome.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    venue_kind: Mapped[VenueKind] = mapped_column(enum_column(VenueKind), nullable=False)
    venue_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_market_id: Mapped[str | None] = mapped_column(String(160))
    provider_outcome_id: Mapped[str | None] = mapped_column(String(160))
    decimal_odds: Mapped[Decimal] = mapped_column(ODDS, nullable=False)
    available_size: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    commission_bps: Mapped[int] = mapped_column(default=0)
    observed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    provider_timestamp: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    received_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column()
    freshness: Mapped[FreshnessLabel] = mapped_column(
        enum_column(FreshnessLabel), default=FreshnessLabel.FRESH, nullable=False
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_payload.id"))


class QuoteSnapshot(TimestampMixin, Base):
    """Point-in-time aggregate of quotes for one outcome.

    Snapshots are the ONLY input to feature building and backtests, which is how
    the pipeline stays point-in-time safe (see tests/test_leakage.py).
    """

    __tablename__ = "quote_snapshot"
    __table_args__ = (
        UniqueConstraint("outcome_id", "as_of", name="uq_quote_snapshot_point"),
        Index("ix_quote_snapshot_market_asof", "market_id", "as_of"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcome.id"), nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    best_decimal_odds: Mapped[Decimal] = mapped_column(ODDS, nullable=False)
    best_source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    implied_probability: Mapped[Decimal] = mapped_column(PROBABILITY, nullable=False)
    fair_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY)
    de_vig_method: Mapped[DeVigMethod | None] = mapped_column(enum_column(DeVigMethod))
    overround: Mapped[Decimal | None] = mapped_column(PROBABILITY)
    quote_count: Mapped[int] = mapped_column(default=0)
    freshest_observed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RawPayload(TimestampMixin, Base):
    """Index row for an immutable, content-addressed raw payload.

    The bytes live in the raw archive (filesystem or S3) under ``object_key``;
    this row makes provenance queryable without touching object storage. Payloads
    are append-only: a re-fetch that yields different bytes gets a NEW row.
    """

    __tablename__ = "raw_payload"
    __table_args__ = (
        UniqueConstraint("content_fingerprint", name="uq_raw_payload_fingerprint"),
        Index("ix_raw_payload_source_fetched", "source_id", "fetched_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    http_status: Mapped[int | None] = mapped_column()
    content_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(default=0)
    fetched_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    provider_timestamp: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redaction_notes: Mapped[str | None] = mapped_column(String(256))
    ingest_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingest_run.id"))


class IngestRun(TimestampMixin, Base):
    """One execution of an adapter (audit trail for every data change)."""

    __tablename__ = "ingest_run"
    __table_args__ = (Index("ix_ingest_run_source_started", "source_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), default="fixture", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    records_seen: Mapped[int] = mapped_column(default=0)
    records_upserted: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SourceHealthSnapshot(TimestampMixin, Base):
    """Time series behind GET /v1/sources/health."""

    __tablename__ = "source_health_snapshot"
    __table_args__ = (Index("ix_source_health_source_checked", "source_id", "checked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column()
    mode: Mapped[str] = mapped_column(String(24), default="live", nullable=False)
    quota_used: Mapped[int | None] = mapped_column()
    quota_limit: Mapped[int | None] = mapped_column()
    parser_drift_count: Mapped[int] = mapped_column(default=0)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class InjuryAvailability(TimestampMixin, Base):
    """Injury/suspension record. Optional for a given event (never invented)."""

    __tablename__ = "injury_availability"
    __table_args__ = (Index("ix_injury_event_reported", "event_id", "reported_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participant.id"), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("event.id"))
    player_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256))
    expected_return: Mapped[dt.date | None] = mapped_column()
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Lineup(TimestampMixin, Base):
    """Expected or confirmed XI for one participant in one event."""

    __tablename__ = "lineup"
    __table_args__ = (
        UniqueConstraint("event_id", "participant_id", "is_confirmed", name="uq_lineup_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participant.id"), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    formation: Mapped[str | None] = mapped_column(String(16))
    coach: Mapped[str | None] = mapped_column(String(120))
    players: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class FeatureSnapshot(TimestampMixin, Base):
    """Point-in-time feature vector for one event.

    ``as_of`` is when the features were computable from data available then.
    ``is_point_in_time_safe`` is set false only by the leakage checker; a
    snapshot flagged unsafe must never be used for training.
    """

    __tablename__ = "feature_snapshot"
    __table_args__ = (
        UniqueConstraint("event_id", "as_of", "feature_set_version", name="uq_feature_point"),
        Index("ix_feature_event_asof", "event_id", "as_of"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    missing_features: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_point_in_time_safe: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ModelVersion(TimestampMixin, Base):
    """A registered model: what it is, what it was trained on, how it scored."""

    __tablename__ = "model_version"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    trained_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    train_window_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    train_window_end: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    calibration_window_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    calibration_window_end: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Prediction(TimestampMixin, Base):
    """Model probability for one outcome, with explicit abstention support."""

    __tablename__ = "prediction"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "model_version_id",
            "market_type",
            "outcome_kind",
            name="uq_prediction_target",
        ),
        Index("ix_prediction_event_created", "event_id", "created_at"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_prediction_prob"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_version.id"), nullable=False
    )
    market_type: Mapped[MarketType] = mapped_column(enum_column(MarketType), nullable=False)
    outcome_kind: Mapped[OutcomeKind] = mapped_column(enum_column(OutcomeKind), nullable=False)
    probability: Mapped[Decimal] = mapped_column(PROBABILITY, nullable=False)
    fair_odds: Mapped[Decimal] = mapped_column(ODDS, nullable=False)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(256))
    market_free: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Opportunity(TimestampMixin, Base):
    """A detected market signal (arbitrage or value) with full evidence.

    ``is_actionable`` is only ever true when every leg is fresh, settlement rules
    match, quoted size covers the stake and the net edge survives conservative
    friction (see academic_edge_pricing.friction).
    """

    __tablename__ = "opportunity"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "market_id",
            "opportunity_type",
            "detected_at",
            name="uq_opportunity_point",
        ),
        Index("ix_opportunity_detected", "detected_at"),
        Index("ix_opportunity_type_detected", "opportunity_type", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    opportunity_type: Mapped[OpportunityType] = mapped_column(
        enum_column(OpportunityType), nullable=False
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_version.id"))
    gross_edge_bps: Mapped[int] = mapped_column(default=0)
    net_edge_bps: Mapped[int] = mapped_column(default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    best_legs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    friction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_stake: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    expected_profit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    is_actionable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AlertRule(TimestampMixin, Base):
    """Analyst-authored rule; nothing alerts unless a rule says so."""

    __tablename__ = "alert_rule"
    __table_args__ = (UniqueConstraint("name", name="uq_alert_rule_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    opportunity_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    market_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    min_net_edge_bps: Mapped[int] = mapped_column(default=0)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_quote_age_seconds: Mapped[int] = mapped_column(default=180)
    require_actionable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity), default=AlertSeverity.WATCH, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), default="system", nullable=False)


class Alert(TimestampMixin, Base):
    """A rule firing, snapshotting the evidence that caused it."""

    __tablename__ = "alert"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_alert_dedupe"),
        Index("ix_alert_status_raised", "status", "raised_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    alert_rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rule.id"), nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity.id"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    market_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("market.id"))
    status: Mapped[AlertStatus] = mapped_column(
        enum_column(AlertStatus), default=AlertStatus.OPEN, nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(enum_column(AlertSeverity), nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raised_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Settlement(TimestampMixin, Base):
    """Grading of a market, pinned to the settlement rule version used."""

    __tablename__ = "settlement"
    __table_args__ = (
        UniqueConstraint("market_id", "rule_version", name="uq_settlement_market_rule"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    outcome_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outcome.id"))
    status: Mapped[SettlementStatus] = mapped_column(
        enum_column(SettlementStatus), default=SettlementStatus.PENDING, nullable=False
    )
    rule_version: Mapped[str] = mapped_column(String(24), default="v1", nullable=False)
    home_score: Mapped[int | None] = mapped_column()
    away_score: Mapped[int | None] = mapped_column()
    settled_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512))


class PaperLedgerEntry(TimestampMixin, Base):
    """Paper trading only -- no wallet, no bookmaker account, no real stake."""

    __tablename__ = "paper_ledger_entry"
    __table_args__ = (
        Index("ix_paper_ledger_status_placed", "status", "placed_at"),
        CheckConstraint("stake > 0", name="ck_paper_ledger_stake_positive"),
        CheckConstraint("decimal_odds > 1.0", name="ck_paper_ledger_odds_above_one"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event.id"), nullable=False)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id"), nullable=False)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcome.id"), nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity.id"))
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stake: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    decimal_odds: Mapped[Decimal] = mapped_column(ODDS, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    status: Mapped[LedgerStatus] = mapped_column(
        enum_column(LedgerStatus), default=LedgerStatus.OPEN, nullable=False
    )
    placed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    settled_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    notes: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(TimestampMixin, Base):
    """Append-only record of consequential actions (who/what/when/why)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_occurred", "occurred_at"),
        Index("ix_audit_action_occurred", "action", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    actor_role: Mapped[Role | None] = mapped_column(enum_column(Role))
    source_id: Mapped[str | None] = mapped_column(String(64))
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class SourcePolicyRecord(TimestampMixin, Base):
    """Persisted copy of config/source_policies.yaml, queryable at runtime."""

    __tablename__ = "source_policy"
    __table_args__ = (UniqueConstraint("source_id", name="uq_source_policy_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor_url: Mapped[str | None] = mapped_column(String(256))
    docs_url: Mapped[str | None] = mapped_column(String(256))
    tier: Mapped[SourceTier] = mapped_column(enum_column(SourceTier), nullable=False)
    license: Mapped[str] = mapped_column(String(512), nullable=False)
    auth: Mapped[str] = mapped_column(String(40), nullable=False)
    quota_notes: Mapped[str | None] = mapped_column(String(512))
    automation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automation_scope: Mapped[AutomationScope] = mapped_column(
        enum_column(AutomationScope), nullable=False
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(default=0)
    terms_reviewed_by: Mapped[str | None] = mapped_column(String(120))
    terms_reviewed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_classes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    registry_version: Mapped[int] = mapped_column(default=1)
