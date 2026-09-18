"""Point-in-time feature vectors for Academic Edge.

Features are computed from data available *up to* a given ``as_of`` timestamp, and
the builder refuses to accept any observation timestamped after ``as_of``. That is
the leakage guard: it makes the walk-forward tests meaningful and stops the model
pipeline from accidentally looking at the future.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from academic_edge_domain.time import ensure_utc
from academic_edge_features.form import FormTracker


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """One event's feature snapshot at a point in time.

    Every numeric feature is exposed through a plain dict so downstream code can
    read it without knowing the internal feature-set version. Missing features are
    listed, never hallucinated.
    """

    event_id: str
    as_of: dt.datetime
    feature_set_version: str
    features: dict[str, float] = field(default_factory=dict)
    missing_features: list[str] = field(default_factory=list)


def _ensure_not_future(observed_at: dt.datetime, *, as_of: dt.datetime, label: str) -> None:
    """Raise if an observation is timestamped after the feature-as-of time."""
    if observed_at > as_of:
        raise ValueError(
            f"feature builder received a {label} observed at {observed_at.isoformat()} "
            f"which is after the feature as_of {as_of.isoformat()}. Point-in-time safety: "
            f"features may only use data available up to as_of."
        )


class FeatureBuilder:
    """Compute a point-in-time feature vector for one event.

    Uses a :class:`FormTracker` for opponent-adjusted, time-decayed form. All other
    features are simple, deterministic, and derived only from data up to ``as_of``.
    """

    def __init__(self, *, half_life_days: float = 180.0) -> None:
        self._half_life_days = half_life_days

    def build(
        self,
        *,
        event_id: str,
        as_of: dt.datetime,
        home_team: str,
        away_team: str,
        kickoff: dt.datetime,
        results: list[dict[str, Any]] | None = None,
    ) -> FeatureVector:
        """Build a feature vector for one event at one point in time.

        ``results`` is an optional list of historical ``FormRecord``-compatible
        dicts with keys ``home_team``, ``away_team``, ``played_on``, ``home_goals``,
        ``away_goals``. Each ``played_on`` must be <= ``as_of``.
        """
        as_of_dt = ensure_utc(as_of)

        if results:
            for r in results:
                played_on = ensure_utc(dt.datetime.combine(r["played_on"], dt.time()))
                _ensure_not_future(played_on, as_of=as_of_dt, label="historical result")
            tracker = FormTracker(
                half_life_days=self._half_life_days, cutoff_date=as_of_dt.date()
            )
            for r in results:
                tracker.append(
                    FormRecord(
                        home_team=r["home_team"],
                        away_team=r["away_team"],
                        played_on=r["played_on"],
                        home_goals=int(r["home_goals"]),
                        away_goals=int(r["away_goals"]),
                    )
                )
            home_form_rolling = tracker.weighted_attack_rate(home_team)
            away_form_rolling = tracker.weighted_attack_rate(away_team)
            home_conceded_rolling = tracker.weighted_defence_rate(home_team)
            away_conceded_rolling = tracker.weighted_defence_rate(away_team)
        else:
            home_form_rolling = 0.0
            away_form_rolling = 0.0
            home_conceded_rolling = 0.0
            away_conceded_rolling = 0.0

        kickoff_dt = ensure_utc(kickoff)
        _ensure_not_future(kickoff_dt, as_of=as_of_dt, label="event kickoff")

        features: dict[str, float] = {
            "days_to_kickoff": float(max(0, (kickoff_dt.date() - as_of_dt.date()).days)),
            "home_form_rolling": float(home_form_rolling),
            "away_form_rolling": float(away_form_rolling),
            "home_conceded_rolling": float(home_conceded_rolling),
            "away_conceded_rolling": float(away_conceded_rolling),
            "form_diff": float((home_form_rolling or 0.0) - (away_form_rolling or 0.0)),
            "conceded_diff": float((home_conceded_rolling or 0.0) - (away_conceded_rolling or 0.0)),
            "home_advantage": 1.0,
        }

        missing: list[str] = []
        for key in ("home_form_rolling", "away_form_rolling", "home_conceded_rolling", "away_conceded_rolling"):
            if features[key] == 0.0 and (results is None or not tracker._results):
                missing.append(key)

        return FeatureVector(
            event_id=event_id,
            as_of=as_of_dt,
            feature_set_version="v1",
            features=features,
            missing_features=missing,
        )
