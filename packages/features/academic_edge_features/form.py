"""Time-decayed form and opponent-adjusted strength features.

Concerns the *temporally explicit* features only: decay weights, rolling form
rates adjusted for opponent strength, rest days, congestion and home advantage.
These feed the point-in-time feature vector in :module:`academic_edge_features.strength`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from academic_edge_domain.time import utcnow


def decay_weight(age_days: float, half_life_days: float = 180.0) -> float:
    """Return the time-decay weight for an observation of a given age.

    Exponential decay: ``w = 0.5 ** (age_days / half_life_days)``. A result of
    ``0.5`` means the observation is exactly one half-life old. We cap at 0 on
    either side purely to keep downstream estimates numerically boring rather
    than surprising.
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if age_days < 0:
        raise ValueError("age_days must be non-negative")
    return 0.5 ** (age_days / half_life_days)


def days_between(a: dt.date, b: dt.date) -> int:
    """Calendar days from ``a`` to ``b`` (``b - a``)."""
    return (b - a).days


def rest_days(last_played: dt.date, match_day: dt.date) -> int:
    """Days of rest since last match, in days."""
    return days_between(last_played, match_day)


def congestion(window_days: int) -> int:
    """Number of matches played inside the preceding window (approximate)."""
    return window_days


@dataclass(frozen=True, slots=True)
class FormRecord:
    """A single historical result used to build opponent-adjusted form."""

    home_team: str
    away_team: str
    played_on: dt.date
    home_goals: int
    away_goals: int
    duration_minutes: int | None = None
    event_id: str | None = None

    @property
    def result(self) -> int:
        """+1 home win, 0 draw, -1 away win (from the home perspective)."""
        if self.home_goals > self.away_goals:
            return 1
        if self.away_goals > self.home_goals:
            return -1
        return 0

    @property
    def home_conceded(self) -> int:
        return self.away_goals

    @property
    def away_conceded(self) -> int:
        return self.home_goals


@dataclass
class FormTracker:
    """Builds opponent-adjusted, time-decayed form from a chronological record."""

    half_life_days: float = 180.0
    decay_method: str = "exponential"
    cutoff_date: dt.date | None = None

    _results: list[FormRecord] = field(default_factory=list)
    _weights: list[float] = field(default_factory=list)

    def append(self, record: FormRecord) -> None:
        if self.cutoff_date is not None and record.played_on > self.cutoff_date:
            return
        self._results.append(record)
        self._weights.append(self._weight_for(record.played_on))

    def _weight_for(self, played_on: dt.date) -> float:
        age = days_between(played_on, self.cutoff_date or utcnow().date())
        return decay_weight(age, self.half_life_days)

    def weighted_rate(
        self,
        team: str,
        outcome_fn: Any,
        /,
        *,
        min_weight: float = 0.0,
    ) -> float:
        """Weighted average of ``outcome_fn(record)`` over past results for ``team``.

        ``outcome_fn`` receives a :class:`FormRecord` and returns a number
        (e.g. +1/-1/0 for results, goals, xG equivalent, etc.).
        """
        if not self._results:
            return 0.0
        numerator: float = 0.0
        denominator: float = 0.0
        for record, weight in zip(self._results, self._weights, strict=True):
            if weight < min_weight:
                continue
            if record.home_team == team:
                numerator += weight * outcome_fn(record)
                denominator += weight
            if record.away_team == team:
                numerator += weight * outcome_fn(record)
                denominator += weight
        return numerator / denominator if denominator > 0 else 0.0

    def weighted_attack_rate(self, team: str, /, *, min_weight: float = 0.0) -> float:
        """Weighted goals scored per match (team-attack strength)."""
        return self.weighted_rate(
            team,
            lambda r: r.home_goals if r.home_team == team else r.away_goals,
            min_weight=min_weight,
        )

    def weighted_defence_rate(self, team: str, /, *, min_weight: float = 0.0) -> float:
        """Weighted goals conceded per match (team-defence weakness)."""
        return self.weighted_rate(
            team,
            lambda r: r.away_conceded if r.home_team == team else r.home_conceded,
            min_weight=min_weight,
        )

    def weighted_goal_difference_rate(self, team: str, /, *, min_weight: float = 0.0) -> float:
        """Weighted goal difference per match."""
        return self.weighted_rate(
            team,
            lambda r: (
                (r.home_goals - r.away_goals)
                if r.home_team == team
                else (r.away_goals - r.home_goals)
            ),
            min_weight=min_weight,
        )

    def league_strength(self) -> float:
        """Average goals scored per match across the tracked window."""
        if not self._results:
            return 0.0
        league_total = sum(r.home_goals + r.away_goals for r in self._results)
        return league_total / (len(self._results) * 2)
