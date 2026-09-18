"""Odds conversion and de-vig tests, plus de-vig property invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest
from academic_edge_domain.enums import DeVigMethod
from academic_edge_pricing import (
    OddsError,
    american_to_decimal,
    consensus_de_vig,
    de_vig,
    de_vig_odds,
    decimal_from_probability,
    edge_bps,
    expected_value_per_unit,
    fractional_to_decimal,
    implied_probability,
    overround,
    quantize_odds,
)
from hypothesis import given, settings
from hypothesis import strategies as st


class TestConversions:
    def test_implied_probability_is_exact(self) -> None:
        assert implied_probability(Decimal("2.00")) == Decimal("0.5")

    def test_decimal_from_probability_round_trips(self) -> None:
        assert decimal_from_probability(Decimal("0.25")) == Decimal("4")

    def test_fractional_and_american(self) -> None:
        assert fractional_to_decimal(7, 4) == Decimal("2.750000")
        assert american_to_decimal(150) == Decimal("2.50")
        assert american_to_decimal(-200) == Decimal("1.50")

    def test_invalid_odds_are_rejected(self) -> None:
        with pytest.raises(OddsError):
            implied_probability(Decimal("1.0"))
        with pytest.raises(OddsError):
            decimal_from_probability(Decimal("1.5"))
        with pytest.raises(OddsError):
            american_to_decimal(0)

    def test_overround_positive_for_a_margin_book(self) -> None:
        probs = [implied_probability(o) for o in (Decimal("2.0"), Decimal("3.5"), Decimal("4.0"))]
        assert overround(probs) > 0

    def test_edge_bps_sign(self) -> None:
        assert edge_bps(Decimal("0.5"), Decimal("2.2")) > 0
        assert edge_bps(Decimal("0.5"), Decimal("1.9")) < 0

    def test_expected_value_zero_at_fair_price(self) -> None:
        assert expected_value_per_unit(Decimal("0.5"), Decimal("2.0")) == 0

    def test_quantize_keeps_six_dp(self) -> None:
        assert quantize_odds("1.9543217") == Decimal("1.954322")


class TestDevig:
    def test_multiplicative_sums_to_one(self) -> None:
        result = de_vig_odds(["2.0", "3.5", "4.0"])
        assert result.sum_fair == Decimal(1)
        assert result.method is DeVigMethod.MULTIPLICATIVE

    def test_power_sums_to_one_and_shrinks_longshots(self) -> None:
        multiplicative = de_vig_odds(["2.0", "3.5", "4.0"], DeVigMethod.MULTIPLICATIVE)
        power = de_vig_odds(["2.0", "3.5", "4.0"], DeVigMethod.POWER)
        assert power.sum_fair == Decimal(1)
        assert power.exponent is not None and power.exponent > 1
        # power de-vig gives the longshot less than multiplicative does
        assert power.fair_probabilities[-1] < multiplicative.fair_probabilities[-1]

    def test_power_is_order_preserving(self) -> None:
        result = de_vig_odds(["1.5", "4.0", "6.0"], DeVigMethod.POWER)
        assert result.fair_probabilities[0] > result.fair_probabilities[1]
        assert result.fair_probabilities[1] > result.fair_probabilities[2]

    def test_consensus_averages_devigged_probabilities(self) -> None:
        consensus = consensus_de_vig([["2.0", "3.5", "4.0"], ["2.1", "3.4", "3.9"]])
        assert consensus.sum_fair == Decimal(1)
        assert consensus.inputs["books"] == 2

    def test_rejects_degenerate_books(self) -> None:
        with pytest.raises(OddsError):
            de_vig([])
        with pytest.raises(OddsError):
            de_vig([Decimal("0"), Decimal("0")])

    @settings(max_examples=60, deadline=None)
    @given(st.lists(st.floats(min_value=1.05, max_value=50), min_size=2, max_size=6))
    def test_property_devig_sums_to_one_both_methods(self, odds: list[float]) -> None:
        prices = [quantize_odds(o) for o in odds]
        for method in (DeVigMethod.MULTIPLICATIVE, DeVigMethod.POWER):
            result = de_vig_odds(prices, method)
            assert abs(result.sum_fair - 1) < Decimal("1e-8")
            # extreme books can legitimately push an outcome to the 1e-9 floor
            assert all(Decimal(0) <= p < Decimal(1) for p in result.fair_probabilities)
            # Ordering invariant (tie-tolerant): the longest-odds outcome keeps
            # the smallest fair probability and the shortest-odds keeps the
            # largest, up to the 1e-9 storage resolution.
            implied = [implied_probability(p) for p in prices]
            favourite = implied.index(max(implied))  # shortest odds
            longshot = implied.index(min(implied))  # longest odds
            fair = result.fair_probabilities
            tol = Decimal("1e-8")
            assert fair[longshot] <= min(fair) + tol
            assert fair[favourite] >= max(fair) - tol
