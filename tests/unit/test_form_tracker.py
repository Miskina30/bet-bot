"""Verifier for the form/tracking helpers and leakage guard."""

from __future__ import annotations

import datetime as dt

from academic_edge_features.form import (
    FormRecord,
    FormTracker,
    decay_weight,
    days_between,
    rest_days,
)


def test_decay_weight_half_life() -> None:
    assert decay_weight(0.0, half_life_days=180.0) == 1.0
    assert abs(decay_weight(180.0, half_life_days=180.0) - 0.5) < 1e-12
    assert decay_weight(360.0, half_life_days=180.0) == 0.25
    assert decay_weight(540.0, half_life_days=180.0) == 0.125


def test_decay_weight_requires_positive_half_life() -> None:
    try:
        decay_weight(1.0, half_life_days=0)
    except ValueError as exc:
        assert "half_life_days must be positive" in str(exc)
    else:
        raise AssertionError("should have raised")


def test_decay_weight_does_not_accept_negative_age() -> None:
    try:
        decay_weight(-1.0, half_life_days=180.0)
    except ValueError as exc:
        assert "age_days must be non-negative" in str(exc)
    else:
        raise AssertionError("should have raised")


def test_form_tracker_weighted_rate() -> None:
    tracker = FormTracker(half_life_days=365.0, cutoff_date=dt.date(2026, 8, 1))
    records = [
        FormRecord("Home", "Away", dt.date(2025, 1, 1), 2, 0),
        FormRecord("Home", "Away", dt.date(2025, 3, 1), 3, 1),
        FormRecord("Away", "Home", dt.date(2025, 6, 1), 1, 4),
        FormRecord("Home", "Away", dt.date(2025, 9, 1), 1, 1),
    ]
    for r in records:
        tracker.append(r)

    home_gf = tracker.weighted_attack_rate("Home")
    away_gf = tracker.weighted_attack_rate("Away")
    assert home_gf > away_gf >= 0.0


def test_form_tracker_strength_is_monotonic_in_recent_good_form() -> None:
    base = FormTracker(half_life_days=365.0, cutoff_date=dt.date(2026, 8, 1))
    strong = FormTracker(half_life_days=365.0, cutoff_date=dt.date(2026, 8, 1))

    base_form = [FormRecord("Home", "Away", dt.date(2024, 1, 1), 1, 1)]
    strong_form = [FormRecord("Home", "Away", dt.date(2025, 7, 1), 3, 0)]

    for r in base_form:
        base.append(r)
    for r in strong_form:
        strong.append(r)

    assert strong.weighted_attack_rate("Home") > base.weighted_attack_rate("Home")


def test_home_and_away_conceded_are_opposite() -> None:
    r = FormRecord("Home", "Away", dt.date(2026, 1, 1), 3, 2)
    assert r.home_conceded == 2
    assert r.away_conceded == 3


def test_weight_multiplier_is_exact_at_half_life() -> None:
    w = decay_weight(180.0, half_life_days=180.0)
    assert w == 0.5
