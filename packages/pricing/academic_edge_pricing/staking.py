"""Stake sizing: Kelly and the allocation helpers the paper ledger uses.

Kelly here is deliberately conservative and capped:

    f* = (p * odds - 1) / (odds - 1)

A negative edge returns a stake of exactly zero -- never a negative stake -- and
the fraction is capped at ``max_fraction`` of bankroll. Paper-trading a model
should not be able to go broke in one afternoon because a probability was wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from academic_edge_pricing.arb import LegInput, effective_odds
from academic_edge_pricing.odds import (
    ONE,
    ZERO,
    OddsError,
    _to_decimal,
    quantize_odds,
    validate_decimal_odds,
)

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class StakePlan:
    """A stake allocation with its risk profile."""

    stakes: dict[str, Decimal]
    total: Decimal
    expected_profit: Decimal
    max_loss: Decimal
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stakes": {k: str(v) for k, v in self.stakes.items()},
            "total": str(self.total),
            "expected_profit": str(self.expected_profit),
            "max_loss": str(self.max_loss),
            "notes": list(self.notes),
        }


def kelly_stake(
    probability: Decimal | int | float | str,
    decimal_odds: Decimal | int | float | str,
    bankroll: Decimal | int | float | str,
    *,
    fraction: Decimal | int | float | str = Decimal("0.25"),
    max_fraction: Decimal | int | float | str = Decimal("0.05"),
) -> Decimal:
    """Kelly stake, scaled by ``fraction`` and capped at ``max_fraction`` of bankroll.

    Returns ``0`` for a non-positive edge (never a negative stake) and raises
    :class:`OddsError` for invalid inputs rather than silently "fixing" them.
    """
    prob = _to_decimal(probability)
    odds = validate_decimal_odds(decimal_odds)
    bank = _to_decimal(bankroll)
    scale = _to_decimal(fraction)
    cap = _to_decimal(max_fraction)

    if prob <= ZERO or prob >= ONE:
        raise OddsError("probability must be strictly inside (0, 1)")
    if bank <= ZERO:
        raise OddsError("bankroll must be positive")
    if scale <= ZERO or scale > ONE:
        raise OddsError("fraction must be inside (0, 1]")
    if cap <= ZERO or cap > ONE:
        raise OddsError("max_fraction must be inside (0, 1]")

    edge_numerator = prob * odds - ONE
    denominator = odds - ONE
    if edge_numerator <= ZERO:
        return ZERO  # no edge: never bet, never go negative

    full_kelly = edge_numerator / denominator
    applied = min(full_kelly * scale, cap)
    stake = bank * applied
    if stake <= ZERO:
        return ZERO
    return stake.quantize(CENT, rounding=ROUND_HALF_UP)


def equalize_stakes(
    legs: Sequence[LegInput],
    total_stake: Decimal | int | float | str,
    *,
    min_stake: Decimal | int | float | str = Decimal("1"),
) -> dict[str, Decimal]:
    """Stakes per leg such that every leg returns the same payoff.

    This is the allocation behind :func:`academic_edge_pricing.arb.detect_arbitrage`;
    kept public so the paper ledger and the UI can show the same numbers.
    Raises :class:`OddsError` for empty input or duplicate outcome kinds, and
    never returns a negative or zero stake (the total is raised if required).
    """
    from academic_edge_pricing.arb import detect_arbitrage

    result = detect_arbitrage(legs, total_stake, min_stake=min_stake)
    return dict(result.equalized_stakes)


def level_stakes(legs: Sequence[LegInput], unit: Decimal | int | float | str) -> dict[str, Decimal]:
    """The same stake on every leg (what the backtests in ``evaluate`` assume)."""
    if not legs:
        raise OddsError("level_stakes needs at least one leg")
    stake = quantize_odds(_to_decimal(unit))
    if stake <= ZERO:
        raise OddsError("unit stake must be positive")
    return {leg.label: stake for leg in legs}


def plan_from_stakes(
    stakes: dict[str, Decimal],
    legs: Sequence[LegInput],
    *,
    win_probability: Decimal | int | float | str | None = None,
) -> StakePlan:
    """Summarise an allocation: total, expected profit and worst-case loss.

    ``win_probability`` is the probability of the single leg that wins (for a
    mutually exclusive market exactly one leg can win). When omitted, the worst
    case is reported and expected profit is computed at break-even odds.
    """
    if not stakes:
        raise OddsError("no stakes to plan")
    total = sum(stakes.values(), ZERO)
    if total <= ZERO:
        raise OddsError("stake total must be positive")

    by_label = {leg.label: leg for leg in legs}
    missing = set(stakes) - set(by_label)
    if missing:
        raise OddsError(f"stakes reference unknown legs: {sorted(missing)}")

    payoffs = {
        label: amount * effective_odds(by_label[label].decimal_odds, by_label[label].commission_bps)
        for label, amount in stakes.items()
    }
    worst = min(payoffs.values()) - total
    if win_probability is None:
        expected = worst  # conservative: assume the worst-paying leg wins
        notes = ["expected profit computed at the worst-paying leg (conservative)"]
    else:
        prob = _to_decimal(win_probability)
        if prob <= ZERO or prob >= ONE:
            raise OddsError("win_probability must be strictly inside (0, 1)")
        expected = prob * (total * ONE) + (ONE - prob) * worst - total
        notes = ["expected profit computed from the supplied win probability"]

    return StakePlan(
        stakes=dict(stakes),
        total=total,
        expected_profit=expected,
        max_loss=min(ZERO, worst),
        notes=notes,
    )
