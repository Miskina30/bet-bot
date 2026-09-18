"""Canonical domain enums for Academic Edge.

Everything here is deliberately provider-agnostic. Connectors translate provider
vocabularies into these values; nothing downstream ever sees a provider string.
"""

from __future__ import annotations

from enum import StrEnum


class Sport(StrEnum):
    """MVP supports association football only (see brief: MVP SCOPE)."""

    FOOTBALL = "football"


class MarketType(StrEnum):
    """Supported market families. Adding one requires a settlement rule."""

    FT_1X2 = "ft_1x2"
    FT_TOTALS_2_5 = "ft_totals_2_5"
    FT_BTTS = "ft_btts"


class MarketPeriod(StrEnum):
    FULL_TIME = "full_time"
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


class TeamScope(StrEnum):
    """Which team a market parameterises (totals/BTTS are team-neutral)."""

    HOME = "home"
    AWAY = "away"
    NEUTRAL = "neutral"


class OutcomeKind(StrEnum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"
    OVER = "over"
    UNDER = "under"
    YES = "yes"
    NO = "no"


class VenueKind(StrEnum):
    """Where a price lives. Determines fee/commission defaults."""

    BOOKMAKER = "bookmaker"
    EXCHANGE = "exchange"
    PREDICTION_MARKET = "prediction_market"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class SourceTier(StrEnum):
    FREE = "free"
    PUBLIC = "public"
    PUBLIC_READ = "public_read"
    MANUAL = "manual"
    PAID = "paid"
    SYNTHETIC = "synthetic"


class AutomationScope(StrEnum):
    OFFICIAL_API_ONLY = "official_api_only"
    DOCUMENTED_PUBLIC_READS = "documented_public_reads"
    BULK_STATIC_DOWNLOAD = "bulk_static_download"
    MANUAL_CSV_ONLY = "manual_csv_only"
    LOCAL_FIXTURES = "local_fixtures"


class ReviewStatus(StrEnum):
    AUTO_ACCEPTED = "auto_accepted"
    REVIEW_REQUIRED = "review_required"
    MANUALLY_LINKED = "manually_linked"
    REJECTED = "rejected"


class HardRejectReason(StrEnum):
    SPORT_MISMATCH = "sport_mismatch"
    COMPETITION_MISMATCH = "competition_mismatch"
    HOME_AWAY_INVERSION = "home_away_inversion"
    PERIOD_MISMATCH = "period_mismatch"
    LINE_MISMATCH = "line_mismatch"
    OVERTIME_MISMATCH = "overtime_mismatch"
    SETTLEMENT_VERSION_MISMATCH = "settlement_version_mismatch"
    START_TIME_OUT_OF_WINDOW = "start_time_out_of_window"
    PARTICIPANT_MISMATCH = "participant_mismatch"


class DeVigMethod(StrEnum):
    """How the overround was removed to obtain fair probabilities."""

    MULTIPLICATIVE = "multiplicative"
    POWER = "power"


class OpportunityType(StrEnum):
    ARBITRAGE = "arbitrage"
    POSITIVE_EV = "positive_ev"
    MODEL_DISAGREEMENT = "model_disagreement"


class FreshnessLabel(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"
    SUPPRESSED = "suppressed"


class AlertSeverity(StrEnum):
    INFO = "info"
    WATCH = "watch"
    ACTIONABLE = "actionable"


class SettlementStatus(StrEnum):
    PENDING = "pending"
    GRADED = "graded"
    VOID = "void"
    ABANDONED = "abandoned"


class LedgerStatus(StrEnum):
    """Paper ledger only. Academic Edge never places real bets."""

    OPEN = "open"
    SETTLED = "settled"
    VOID = "void"


class Role(StrEnum):
    READER = "reader"
    ANALYST = "analyst"
    ADMIN = "admin"


class AuditAction(StrEnum):
    INGEST_RUN = "ingest_run"
    RESOLUTION_DECISION = "resolution_decision"
    ALERT_RAISED = "alert_raised"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    POLICY_CHANGE = "policy_change"
    POLICY_VIOLATION = "policy_violation"
    LEDGER_ENTRY = "ledger_entry"
    MODEL_REGISTERED = "model_registered"
    MANUAL_IMPORT = "manual_import"
