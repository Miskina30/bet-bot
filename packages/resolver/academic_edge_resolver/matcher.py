"""Event matching: score a provider event against canonical events.

Decision rules (brief: MATCHING):

* same sport and competition, kickoff inside a bounded time window;
* **hard rejects** are absolute -- home/away inversion, participant mismatch,
  period/line/overtime/settlement conflicts, or a kickoff outside the window
  mean the pair is never auto-accepted, whatever the score;
* ``score >= auto_accept_threshold`` (0.985) with zero hard rejects -> auto-accept;
* ``review_threshold <= score < auto_accept_threshold`` (0.940-0.985) -> review;
* below that -> reject.

Every decision carries the component scores, the normalised names, the time
delta and the reject reasons, and is persisted by the worker as evidence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol, runtime_checkable

from academic_edge_domain.enums import HardRejectReason, ReviewStatus
from academic_edge_domain.time import ensure_utc, seconds_between

from academic_edge_resolver.normalize import normalize_competition, normalize_name
from academic_edge_resolver.similarity import name_similarity

# Participant pairs at or above this are "the same club" (after alias
# canonicalisation, identical clubs normalise to ~1.0, while genuinely
# different clubs -- Man Utd vs Man City, Real Madrid vs Real Sociedad --
# sit in the 0.65-0.80 band). The 0.85 bar is what keeps those apart.
PARTICIPANT_MATCH_THRESHOLD = 0.85
COMPETITION_MATCH_THRESHOLD = 0.60


@dataclass(frozen=True, slots=True)
class ResolverConfig:
    """Thresholds, window and component weights (weights must sum to 1.0)."""

    auto_accept_threshold: Decimal = Decimal("0.985")
    review_threshold: Decimal = Decimal("0.940")
    time_window_minutes: int = 180
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "participant": 0.55,
            "time": 0.20,
            "competition": 0.15,
            "venue": 0.05,
            "round": 0.05,
        }
    )

    def __post_init__(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"resolver weights must sum to 1.0, got {total}")
        if not (0 < self.review_threshold < self.auto_accept_threshold <= 1):
            raise ValueError("thresholds must satisfy 0 < review < auto-accept <= 1")
        if self.time_window_minutes <= 0:
            raise ValueError("time_window_minutes must be positive")


@runtime_checkable
class ExistingEventLike(Protocol):
    """Duck-typed canonical event (an ``Event`` row satisfies this)."""

    @property
    def home_name(self) -> str | None: ...
    @property
    def away_name(self) -> str | None: ...
    @property
    def start_time_utc(self) -> dt.datetime: ...
    @property
    def competition_name(self) -> str | None: ...
    @property
    def venue_name(self) -> str | None: ...
    @property
    def round_label(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    """A provider event before resolution."""

    provider_event_id: str
    source_id: str
    competition_name: str
    home_name: str
    away_name: str
    start_time_utc: dt.datetime
    venue_name: str | None = None
    round_label: str | None = None
    competition_provider_id: str | None = None
    home_provider_id: str | None = None
    away_provider_id: str | None = None
    # Optional market-shape attributes; when present on both sides, hard-checked.
    period: str | None = None
    line_value: float | None = None
    overtime_included: bool | None = None
    settlement_version: str | None = None


@dataclass(frozen=True, slots=True)
class MatchDecision:
    """Outcome of comparing one candidate against one canonical event."""

    status: ReviewStatus
    score: Decimal
    hard_rejects: list[HardRejectReason]
    component_scores: dict[str, float]
    evidence: dict[str, Any]
    matched_event_id: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "score": str(self.score),
            "hard_rejects": [str(r) for r in self.hard_rejects],
            "component_scores": dict(self.component_scores),
            "evidence": dict(self.evidence),
            "matched_event_id": (
                str(self.matched_event_id) if self.matched_event_id is not None else None
            ),
        }


def _time_score(delta_minutes: float, window_minutes: int) -> float:
    """Linear decay: 1.0 at the same kickoff, 0.0 at the window edge."""
    if delta_minutes >= window_minutes:
        return 0.0
    return 1.0 - (delta_minutes / window_minutes)


def _optional_similarity(
    candidate_value: str | None, existing_value: str | None, normalise: Any
) -> float | None:
    """Similarity for optional fields; ``None`` when either side is unknown."""
    if not candidate_value or not existing_value:
        return None
    return name_similarity(normalise(candidate_value), normalise(existing_value))


def match_event(
    candidate: CandidateEvent,
    existing: ExistingEventLike,
    config: ResolverConfig,
) -> MatchDecision:
    """Score ``candidate`` against one canonical ``existing`` event."""
    hard_rejects: list[HardRejectReason] = []
    evidence: dict[str, Any] = {"candidate_provider_event_id": candidate.provider_event_id}

    candidate_start = ensure_utc(candidate.start_time_utc)
    existing_start = ensure_utc(existing.start_time_utc)
    delta_minutes = abs(seconds_between(candidate_start, existing_start)) / 60.0
    evidence["start_time_delta_minutes"] = round(delta_minutes, 3)
    evidence["window_minutes"] = config.time_window_minutes

    # -- time window (hard) ---------------------------------------------------
    if delta_minutes > config.time_window_minutes:
        hard_rejects.append(HardRejectReason.START_TIME_OUT_OF_WINDOW)

    # -- participants ----------------------------------------------------------
    cand_home = normalize_name(candidate.home_name)
    cand_away = normalize_name(candidate.away_name)
    exist_home = normalize_name(existing.home_name or "")
    exist_away = normalize_name(existing.away_name or "")
    home_sim = name_similarity(cand_home, exist_home)
    away_sim = name_similarity(cand_away, exist_away)
    inverted_home = name_similarity(cand_home, exist_away)
    inverted_away = name_similarity(cand_away, exist_home)

    evidence["participant_scores"] = {
        "home": home_sim,
        "away": away_sim,
        "home_vs_existing_away": inverted_home,
        "away_vs_existing_home": inverted_away,
    }
    evidence["normalised_names"] = {
        "candidate": {"home": cand_home, "away": cand_away},
        "existing": {"home": exist_home, "away": exist_away},
    }

    # A swapped home/away pair is same-two-clubs when BOTH cross similarities
    # clear the match bar while at least one direct one does not. That is an
    # inversion, not a mismatch, and must never be auto-accepted.
    looks_inverted = (
        inverted_home >= PARTICIPANT_MATCH_THRESHOLD
        and inverted_away >= PARTICIPANT_MATCH_THRESHOLD
        and (home_sim < PARTICIPANT_MATCH_THRESHOLD or away_sim < PARTICIPANT_MATCH_THRESHOLD)
    )
    if looks_inverted:
        hard_rejects.append(HardRejectReason.HOME_AWAY_INVERSION)
    elif home_sim < PARTICIPANT_MATCH_THRESHOLD or away_sim < PARTICIPANT_MATCH_THRESHOLD:
        hard_rejects.append(HardRejectReason.PARTICIPANT_MISMATCH)

    # -- competition -----------------------------------------------------------
    comp_sim = _optional_similarity(
        candidate.competition_name, existing.competition_name, normalize_competition
    )
    if comp_sim is None or comp_sim < COMPETITION_MATCH_THRESHOLD:
        hard_rejects.append(HardRejectReason.COMPETITION_MISMATCH)

    # -- optional market-shape conflicts ---------------------------------------
    def _existing(name: str) -> Any:
        return getattr(existing, name, None)

    if (
        candidate.period is not None
        and _existing("period") is not None
        and candidate.period != _existing("period")
    ):
        hard_rejects.append(HardRejectReason.PERIOD_MISMATCH)
    if (
        candidate.line_value is not None
        and _existing("line_value") is not None
        and abs(float(candidate.line_value) - float(_existing("line_value"))) > 1e-9
    ):
        hard_rejects.append(HardRejectReason.LINE_MISMATCH)
    if (
        candidate.overtime_included is not None
        and _existing("overtime_included") is not None
        and candidate.overtime_included != _existing("overtime_included")
    ):
        hard_rejects.append(HardRejectReason.OVERTIME_MISMATCH)
    if (
        candidate.settlement_version is not None
        and _existing("settlement_version") is not None
        and candidate.settlement_version != _existing("settlement_version")
    ):
        hard_rejects.append(HardRejectReason.SETTLEMENT_VERSION_MISMATCH)

    # -- score -----------------------------------------------------------------
    # Optional components with unknown values contribute NOTHING and their
    # weight is renormalised across the known ones. Otherwise a provider that
    # omits venue/round could never reach the auto-accept threshold, and the
    # queue would fill with everything.
    weights = config.weights
    component: dict[str, float | None] = {
        "participant": (home_sim + away_sim) / 2.0,
        "time": _time_score(delta_minutes, config.time_window_minutes),
        "competition": comp_sim,
    }
    component["venue"] = _optional_similarity(
        candidate.venue_name, existing.venue_name, normalize_name
    )
    component["round"] = _optional_similarity(
        candidate.round_label, existing.round_label, normalize_name
    )

    known = {name: value for name, value in component.items() if value is not None}
    known_weight = sum(weights[name] for name in known)
    if known_weight <= 0:  # pragma: no cover - weights always sum to 1
        score = 0.0
    else:
        score = sum((known[name] * weights[name] for name in known), 0.0) / known_weight
    evidence["component_scores"] = {
        k: (round(v, 6) if v is not None else None) for k, v in component.items()
    }
    evidence["renormalised_over"] = sorted(known)
    score_decimal = Decimal(str(score)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    if hard_rejects:
        status = ReviewStatus.REJECTED
    elif score_decimal >= config.auto_accept_threshold:
        status = ReviewStatus.AUTO_ACCEPTED
    elif score_decimal >= config.review_threshold:
        status = ReviewStatus.REVIEW_REQUIRED
    else:
        status = ReviewStatus.REJECTED

    return MatchDecision(
        status=status,
        score=score_decimal,
        hard_rejects=hard_rejects,
        component_scores={
            k: (round(v, 6) if v is not None else None) for k, v in component.items()
        },
        evidence=evidence,
        matched_event_id=_existing("id") or _existing("canonical_event_id"),
    )


def best_match(
    candidate: CandidateEvent,
    existing_events: list[ExistingEventLike],
    config: ResolverConfig,
) -> MatchDecision | None:
    """Highest-scoring decision across all canonical events in scope.

    Returns ``None`` only when there is nothing to match against, which the
    worker treats as "create a new canonical event". A candidate that
    hard-rejects everywhere still returns its best-scoring decision, so the
    review queue shows *why* nothing matched.
    """
    if not existing_events:
        return None
    decisions = [match_event(candidate, event, config) for event in existing_events]
    # Prefer any non-rejected decision over a rejected one, then the higher
    # score. (max() picks the largest rank, so non-rejected must rank higher.)
    return max(
        decisions,
        key=lambda decision: (
            1 if decision.status is not ReviewStatus.REJECTED else 0,
            decision.score,
        ),
    )
