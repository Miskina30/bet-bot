"""Poisson / Dixon-Coles attack-defence model with a low-score dependency term.

Fitted by iterative coordinate descent over attack and defence parameters using
time-decayed weights. Deterministic, converges reliably, needs no external
optimiser. The rho parameter is the Dixon-Coles low-score adjustment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from academic_edge_forecasting.elo import MatchResult

MAX_GOALS = 10
CONVERGENCE_TOL = 1e-10
DEFAULT_MAX_ITERATIONS = 500


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _dc_adjust(h: int, a: int, rho: float) -> float:
    if h == 0 and a == 0:
        return 1.0 + rho
    if h == 0 and a == 1:
        return 1.0 - rho
    if h == 1 and a == 0:
        return 1.0 - rho
    if h == 1 and a == 1:
        return 1.0 + rho
    return 1.0


@dataclass
class PoissonModel:
    """Attack/defence Poisson with Dixon-Coles rho, fitted by coordinate descent."""

    rho: float = -0.05
    half_life_days: float = 365.0
    home_advantage_goals: float = 0.25
    max_iterations: int = DEFAULT_MAX_ITERATIONS

    _attack: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _defence: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _league_mean: float = field(default=1.3, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def attack(self) -> dict[str, float]:
        return dict(self._attack)

    @property
    def defence(self) -> dict[str, float]:
        return dict(self._defence)

    def fit(self, results: list[MatchResult]) -> PoissonModel:
        """Fit attack/defence parameters from chronological results."""
        if not results:
            self._fitted = True
            return self
        teams = sorted({r.home_team for r in results} | {r.away_team for r in results})
        for t in teams:
            self._attack[t] = 0.0
            self._defence[t] = 0.0
        now = max(r.played_on for r in results)
        weights: dict[str, float] = {}
        for r in results:
            key = f"{r.home_team}|{r.away_team}|{r.played_on}"
            age = (now - r.played_on).days
            weights[key] = (
                max(0.05, 0.5 ** (age / self.half_life_days))
                if self.half_life_days > 0
                else 1.0
            )
        total_g, total_w = 0.0, 0.0
        for r in results:
            key = f"{r.home_team}|{r.away_team}|{r.played_on}"
            w = weights.get(key, 1.0)
            total_g += w * (r.home_goals + r.away_goals)
            total_w += 2 * w
        self._league_mean = total_g / total_w if total_w > 0 else 1.3
        for _ in range(self.max_iterations):
            max_change = 0.0
            for team in teams:
                num, den = 0.0, 0.0
                for r in results:
                    key = f"{r.home_team}|{r.away_team}|{r.played_on}"
                    w = weights.get(key, 1.0)
                    if r.home_team == team:
                        num += w * r.home_goals
                        den += w * max(0.1, self._league_mean + self._defence.get(r.away_team, 0.0))
                    elif r.away_team == team:
                        num += w * r.away_goals
                        den += w * max(0.1, self._league_mean + self._defence.get(r.home_team, 0.0))
                if den > 0:
                    new_a = math.log(max(0.05, num / den))
                    max_change = max(max_change, abs(new_a - self._attack.get(team, 0.0)))
                    self._attack[team] = new_a
            for team in teams:
                num, den = 0.0, 0.0
                for r in results:
                    key = f"{r.home_team}|{r.away_team}|{r.played_on}"
                    w = weights.get(key, 1.0)
                    if r.home_team == team:
                        num += w * r.away_goals
                        den += w * max(0.1, self._league_mean + self._attack.get(r.away_team, 0.0))
                    elif r.away_team == team:
                        num += w * r.home_goals
                        den += w * max(0.1, self._league_mean + self._attack.get(r.home_team, 0.0))
                if den > 0:
                    new_d = math.log(max(0.05, num / den))
                    max_change = max(max_change, abs(new_d - self._defence.get(team, 0.0)))
                    self._defence[team] = new_d
            if max_change < CONVERGENCE_TOL:
                break
        self._fitted = True
        return self

    def _lam(self, home: str, away: str) -> tuple[float, float]:
        ah = self._attack.get(home, 0.0)
        aa = self._attack.get(away, 0.0)
        dh = self._defence.get(home, 0.0)
        da = self._defence.get(away, 0.0)
        lh = max(0.1, self._league_mean + ah + da + self.home_advantage_goals)
        la = max(0.1, self._league_mean + aa + dh)
        return lh, la

    def _score_matrix(self, home: str, away: str) -> list[list[float]]:
        lh, la = self._lam(home, away)
        m = [[0.0] * (MAX_GOALS + 1) for _ in range(MAX_GOALS + 1)]
        total = 0.0
        for h in range(MAX_GOALS + 1):
            for a in range(MAX_GOALS + 1):
                m[h][a] = _poisson_pmf(h, lh) * _poisson_pmf(a, la) * _dc_adjust(h, a, self.rho)
                total += m[h][a]
        if total > 0:
            for h in range(MAX_GOALS + 1):
                for a in range(MAX_GOALS + 1):
                    m[h][a] /= total
        return m

    def predict_1x2(self, home: str, away: str) -> dict[str, float]:
        m = self._score_matrix(home, away)
        ph = sum(m[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h > a)
        pd = sum(m[h][h] for h in range(MAX_GOALS + 1))
        pa = sum(m[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h < a)
        return {"p_home": ph, "p_draw": pd, "p_away": pa}

    def predict_btts(self, home: str, away: str) -> dict[str, float]:
        m = self._score_matrix(home, away)
        py = sum(m[h][a] for h in range(1, MAX_GOALS + 1) for a in range(1, MAX_GOALS + 1))
        return {"p_yes": py, "p_no": 1.0 - py}

    def predict_totals(self, home: str, away: str, *, line: float = 2.5) -> dict[str, float]:
        m = self._score_matrix(home, away)
        po = sum(m[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h + a > line)
        return {"p_over": po, "p_under": 1.0 - po}