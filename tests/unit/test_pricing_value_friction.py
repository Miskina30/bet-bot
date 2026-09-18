"""Value (model vs market) and friction tests, incl. the stale-never-alerts invariant."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from academic_edge_domain.enums import FreshnessLabel, OutcomeKind
from academic_edge_pricing import evaluate_model_value
from academic_edge_pricing.arb import LegInput
from academic_edge_pricing.friction import (
    FrictionConfig,
    apply_friction,
    assess_actionability,
    classify_freshness,
)
from hypothesis import given, settings
from hypothesis import strategies as st

UTC = dt.UTC


def _leg(kind: OutcomeKind, odds: str, source: str, *, age_s: int = 0) -> LegInput:
    observed = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=age_s)
    return LegInput(
        outcome_kind=kind,
        label=kind.value,
        decimal_odds=odds,
        source_id=source,
        observed_at_iso=observed.isoformat(),
    )


class TestValue:
    def test_ev_sign_flips_at_fair_price(self) -> None:
        positive = evaluate_model_value(Decimal("0.55"), Decimal("2.10"))
        negative = evaluate_model_value(Decimal("0.45"), Decimal("2.10"))
        assert positive.net_edge_bps > 0 > negative.net_edge_bps

    def test_large_disagreement_warns(self) -> None:
        result = evaluate_model_value(Decimal("0.90"), Decimal("2.00"), market_probability="0.50")
        assert any("disagrees" in w for w in result.warnings)

    def test_confidence_is_monotone_in_uncertainty(self) -> None:
        low = evaluate_model_value("0.55", "2.10", uncertainty=0.05).confidence
        high = evaluate_model_value("0.55", "2.10", uncertainty=0.45).confidence
        assert low > high

    def test_high_uncertainty_abstains(self) -> None:
        assert evaluate_model_value("0.55", "2.10", uncertainty=0.45).abstain

    def test_commission_reduces_net_edge(self) -> None:
        gross = evaluate_model_value("0.55", "2.10")
        net = evaluate_model_value("0.55", "2.10", commission_bps=200)
        assert net.net_edge_bps < gross.net_edge_bps


class TestFriction:
    CONFIG = FrictionConfig(max_quote_age_seconds=180)

    def test_freshness_labels(self) -> None:
        assert classify_freshness(10, 180) is FreshnessLabel.FRESH
        assert classify_freshness(100, 180) is FreshnessLabel.AGING
        assert classify_freshness(200, 180) is FreshnessLabel.STALE

    def test_stale_leg_blocks_actionability(self) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "2.10", "a", age_s=600),
            _leg(OutcomeKind.AWAY, "2.10", "b", age_s=600),
        ]
        breakdown = apply_friction(legs, self.CONFIG, dt.datetime.now(tz=UTC))
        decision = assess_actionability(breakdown, 0)
        assert not decision.is_actionable
        assert any("stale" in r for r in decision.reasons)

    def test_missing_timestamp_is_treated_as_stale(self) -> None:
        leg = LegInput(
            outcome_kind=OutcomeKind.HOME,
            label="home",
            decimal_odds="2.10",
            source_id="a",
            observed_at_iso=None,
        )
        breakdown = apply_friction([leg], self.CONFIG, dt.datetime.now(tz=UTC))
        assert breakdown.legs[0].is_stale

    def test_haircut_never_increases_odds(self) -> None:
        legs = [_leg(OutcomeKind.HOME, "2.50", "a", age_s=100)]
        breakdown = apply_friction(legs, self.CONFIG, dt.datetime.now(tz=UTC))
        leg = breakdown.legs[0]
        assert leg.effective_odds_after < leg.effective_odds_before

    def test_fresh_arb_stays_actionable(self) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "2.20", "a", age_s=10),
            _leg(OutcomeKind.AWAY, "2.20", "b", age_s=10),
        ]
        breakdown = apply_friction(legs, self.CONFIG, dt.datetime.now(tz=UTC))
        decision = assess_actionability(breakdown, 100)
        assert decision.is_actionable
        assert decision.net_edge_bps > 0

    def test_rule_or_size_mismatch_blocks(self) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "2.20", "a", age_s=10),
            _leg(OutcomeKind.AWAY, "2.20", "b", age_s=10),
        ]
        breakdown = apply_friction(legs, self.CONFIG, dt.datetime.now(tz=UTC))
        assert not assess_actionability(breakdown, 0, rules_match=False).is_actionable
        assert not assess_actionability(breakdown, 0, size_covers_stake=False).is_actionable

    @settings(max_examples=40, deadline=None)
    @given(st.integers(min_value=181, max_value=100000))
    def test_property_stale_never_actionable(self, age_seconds: int) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "50.00", "a", age_s=age_seconds),
            _leg(OutcomeKind.AWAY, "50.00", "b", age_s=age_seconds),
        ]
        breakdown = apply_friction(legs, self.CONFIG, dt.datetime.now(tz=UTC))
        assert assess_actionability(breakdown, 0).is_actionable is False
