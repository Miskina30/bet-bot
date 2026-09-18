"""Arbitrage and staking tests, plus payout-equalisation property invariants."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from academic_edge_domain.enums import OutcomeKind
from academic_edge_pricing import OddsError, arb, detect_arbitrage, kelly_stake, staking
from academic_edge_pricing.arb import effective_odds, select_best_legs
from hypothesis import given, settings
from hypothesis import strategies as st

UTC = dt.UTC


def _leg(
    kind: OutcomeKind,
    odds: str,
    source: str,
    *,
    commission: int = 0,
    age_s: int = 0,
) -> arb.LegInput:
    observed = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=age_s)
    return arb.LegInput(
        outcome_kind=kind,
        label=kind.value,
        decimal_odds=odds,
        source_id=source,
        commission_bps=commission,
        observed_at_iso=observed.isoformat(),
    )


class TestArbitrage:
    def test_two_way_arb_is_detected_and_equalised(self) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "2.10", "book_a"),
            _leg(OutcomeKind.AWAY, "2.10", "book_b"),
        ]
        result = detect_arbitrage(legs, Decimal("100"))
        assert result.is_arbitrage
        assert result.arbitrage_index > 0
        stakes = list(result.equalized_stakes.values())
        assert sum(stakes) == Decimal("100.00")
        assert all(s > 0 for s in stakes)
        payoffs = list(result.payoffs.values())
        assert max(payoffs) - min(payoffs) <= Decimal("0.01")
        assert result.guaranteed_profit > 0
        assert result.guaranteed_roi_bps == 500  # 2.10/2.10 pays +5% either way

    def test_no_arb_for_a_margin_book(self) -> None:
        legs = [
            _leg(OutcomeKind.HOME, "1.90", "book_a"),
            _leg(OutcomeKind.AWAY, "1.90", "book_b"),
        ]
        assert not detect_arbitrage(legs, Decimal("100")).is_arbitrage

    def test_commission_can_destroy_an_arb(self) -> None:
        # 2.10/2.10 survives a 5% commission but not a 15% one
        legs = [
            _leg(OutcomeKind.HOME, "2.10", "ex_a", commission=1500),
            _leg(OutcomeKind.AWAY, "2.10", "ex_b", commission=1500),
        ]
        assert not detect_arbitrage(legs, Decimal("100")).is_arbitrage

    def test_effective_odds_applies_commission_on_winnings(self) -> None:
        assert effective_odds(Decimal("3.00"), 0) == Decimal("3.000000")
        # 200 bps charged on winnings: 1 + 2 * 0.98 = 2.96
        assert effective_odds(Decimal("3.00"), 200) == Decimal("2.96")

    def test_duplicate_outcomes_are_rejected(self) -> None:
        legs = [_leg(OutcomeKind.HOME, "2.10", "a"), _leg(OutcomeKind.HOME, "2.20", "b")]
        with pytest.raises(OddsError):
            detect_arbitrage(legs, Decimal("100"))

    def test_venue_minimum_raises_total_and_warns(self) -> None:
        legs = [_leg(OutcomeKind.HOME, "1.05", "a"), _leg(OutcomeKind.AWAY, "100.00", "b")]
        result = detect_arbitrage(legs, Decimal("5"), min_stake=Decimal("10"))
        assert any("minimum" in w for w in result.warnings)
        assert result.total_stake >= Decimal("10")

    def test_select_best_legs_returns_none_when_incomplete(self) -> None:
        # a 1X2 market needs all three outcomes; only one is quoted here
        candidates = {OutcomeKind.HOME: [_leg(OutcomeKind.HOME, "2.0", "a")]}
        assert (
            select_best_legs(
                candidates, required=(OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY)
            )
            is None
        )
        # ...and it still picks the best price per side when the book is complete
        complete = {
            OutcomeKind.HOME: [
                _leg(OutcomeKind.HOME, "2.0", "a"),
                _leg(OutcomeKind.HOME, "2.3", "b"),
            ],
            OutcomeKind.AWAY: [_leg(OutcomeKind.AWAY, "2.0", "a")],
        }
        best = select_best_legs(complete)
        assert best is not None and best[0].source_id == "b"

    @settings(max_examples=50, deadline=None)
    @given(
        st.tuples(st.floats(1.5, 12), st.floats(1.5, 12), st.floats(1.5, 12)),
        st.floats(min_value=10, max_value=5000),
    )
    def test_property_payouts_equalise_and_stakes_sum(
        self, odds: tuple[float, float, float], total: float
    ) -> None:
        prices = [Decimal(str(round(o, 4))) for o in odds]
        legs = [
            _leg(OutcomeKind.HOME, str(prices[0]), "a"),
            _leg(OutcomeKind.DRAW, str(prices[1]), "b"),
            _leg(OutcomeKind.AWAY, str(prices[2]), "c"),
        ]
        result = detect_arbitrage(legs, Decimal(str(round(total, 2))))
        stakes = list(result.equalized_stakes.values())
        assert all(s >= 0 for s in stakes), "no negative stakes"
        assert sum(stakes) == result.total_stake
        # The allocator's real guarantee: every stake is within one cent of its
        # ideal equalised value (C / o_i). Payoff spread then follows from the
        # odds, so we bound it off that rather than assuming a fixed number.
        from academic_edge_pricing.arb import effective_odds

        inverse = [Decimal(1) / effective_odds(leg.decimal_odds) for leg in legs]
        sum_inverse = sum(inverse)
        ideal = {
            leg.label: result.total_stake * inv / sum_inverse
            for leg, inv in zip(legs, inverse, strict=True)
        }
        for label, stake in result.equalized_stakes.items():
            assert abs(stake - ideal[label]) <= Decimal("0.011"), (label, stake, ideal[label])
        if result.is_arbitrage:
            assert result.guaranteed_profit > 0


class TestStaking:
    def test_kelly_is_exact_for_a_known_edge(self) -> None:
        # f* = (0.55 * 2.5 - 1) / 1.5 = 0.25; quarter Kelly = 6.25% -> capped at 5%
        assert kelly_stake("0.55", "2.5", "1000") == Decimal("50.00")

    def test_kelly_never_negative(self) -> None:
        assert kelly_stake("0.30", "2.5", "1000") == 0

    def test_kelly_cap_is_honoured(self) -> None:
        stake = kelly_stake("0.9", "3.0", "1000", fraction=1, max_fraction="0.05")
        assert stake == Decimal("50.00")

    def test_kelly_rejects_invalid_input(self) -> None:
        with pytest.raises(OddsError):
            kelly_stake("1.5", "2.5", "1000")
        with pytest.raises(OddsError):
            kelly_stake("0.5", "2.5", "-1")

    def test_equalize_stakes_sums_exactly(self) -> None:
        legs = [_leg(OutcomeKind.HOME, "2.10", "a"), _leg(OutcomeKind.AWAY, "3.40", "b")]
        stakes = staking.equalize_stakes(legs, Decimal("250"))
        assert sum(stakes.values()) == Decimal("250.00")

    def test_level_stakes(self) -> None:
        legs = [_leg(OutcomeKind.HOME, "2.0", "a"), _leg(OutcomeKind.AWAY, "2.0", "b")]
        assert staking.level_stakes(legs, Decimal("10")) == {
            "home": Decimal("10.000000"),
            "away": Decimal("10.000000"),
        }
