"""Deterministic, stdlib-only Elo with time decay and an explicit draw model.

Elo ratings are updated chronologically; a draw probability is modelled
explicitly (never by splitting a win probability into three equal parts).
The model is deterministic (no randomness) and fit from a list of results.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One historical result used to fit an Elo model."""

    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    played_on: dt.date


@dataclass
class EloModel:
    """Time-decayed Elo with a home advantage term and margin-of-victory boost."""

    base_rating: float = 1500.0
    k: float = 30.0
    home_advantage: float = 100.0
    half_life_days: float = 365.0
    draw_scale: float = 120.0

    _ratings: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _match_count: int = field(default=0, init=False, repr=False)

    @property
    def ratings(self) -> dict[str, float]:
        return dict(self._ratings)

    def _rating(self, team: str) -> float:
        return self._ratings.get(team, self.base_rating)

    def fit(self, results: list[MatchResult]) -> EloModel:
        """Update ratings chronologically through a list of results."""
        for result in sorted(results, key=lambda r: r.played_on):
            self._update(result)
        return self

    def _update(self, result: MatchResult) -> None:
        home_r = self._rating(result.home_team)
        away_r = self._rating(result.away_team)
        expected_home = self._expected_score(home_r, away_r)
        actual_home = self._actual_score(result)
        goal_diff = abs(result.home_goals - result.away_goals)
        mov_mult = 1.0 + max(0, goal_diff - 1) * 0.15
        if self.half_life_days > 0:
            age = max(0, (dt.date(2026, 12, 31) - result.played_on).days)
            decay = max(0.05, 0.5 ** (age / self.half_life_days))
        else:
            decay = 1.0
        delta = self.k * mov_mult * decay * (actual_home - expected_home)
        self._ratings[result.home_team] = home_r + delta
        self._ratings[result.away_team] = away_r - delta
        self._match_count += 1

    def _expected_score(self, home_r: float, away_r: float) -> float:
        eff_home = home_r + self.home_advantage
        return 1.0 / (1.0 + 10.0 ** ((away_r - eff_home) / 400.0))

    def _actual_score(self, result: MatchResult) -> float:
        if result.home_goals > result.away_goals:
            return 1.0
        if result.away_goals > result.home_goals:
            return 0.0
        return 0.5

    def predict(self, home_team: str, away_team: str, *, neutral: bool = False) -> dict[str, float]:
        home_r = self._rating(home_team)
        away_r = self._rating(away_team)
        ha = 0.0 if neutral else self.home_advantage
        diff = (home_r + ha) - away_r
        expected_home_win = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        draw_prob = _draw_probability(diff, self.draw_scale)
        remaining = 1.0 - draw_prob
        if expected_home_win <= 0.0:
            return {"p_home": 0.0, "p_draw": draw_prob, "p_away": remaining}
        if expected_home_win >= 1.0:
            return {"p_home": remaining, "p_draw": draw_prob, "p_away": 0.0}
        odds_home = expected_home_win / max(1e-12, 1.0 - expected_home_win)
        p_home = remaining * odds_home / (1.0 + odds_home)
        return {"p_home": p_home, "p_draw": draw_prob, "p_away": remaining - p_home}


def _draw_probability(elo_diff: float, draw_scale: float) -> float:
    if draw_scale <= 0:
        return 0.0
    sigma = draw_scale / 3.0
    z = elo_diff / sigma
    return min(0.35, math.exp(-0.5 * z * z) * 0.30)
