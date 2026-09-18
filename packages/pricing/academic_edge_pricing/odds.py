"""Odds and probability primitives.

All odds are **decimal** internally (brief: PRICING). Money and odds arithmetic
uses :class:`decimal.Decimal` with an explicit context so results are
reproducible run-to-run and property tests can assert exact invariants.

Conventions:
* ``decimal_odds`` > 1.0 always. ``1.0`` is not a valid price.
* probabilities are in ``(0, 1)`` and are the *raw* implied probability
  ``1 / decimal_odds`` until a de-vig method is applied.
* "edge in bps" is ``(true_probability * decimal_odds - 1) * 10_000``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, getcontext, localcontext

# 28 significant digits is plenty for 6-dp odds without hiding real rounding error.
getcontext().prec = 28

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
ODDS_QUANTUM = Decimal("0.000001")
PROB_QUANTUM = Decimal("0.000000001")


class OddsError(ValueError):
    """Raised for invalid prices/probabilities (e.g. odds <= 1.0)."""


def _to_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # str() first so 1.95 does not become 1.9499999999999999555910790149937383830547332763671875
        return Decimal(str(value))
    return Decimal(value)


def quantize_odds(value: Decimal | int | float | str) -> Decimal:
    """Round a price to the storage precision used by the ``quote`` table."""
    return _to_decimal(value).quantize(ODDS_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_probability(value: Decimal | int | float | str) -> Decimal:
    """Round a probability to the storage precision used by the canonical model."""
    return _to_decimal(value).quantize(PROB_QUANTUM, rounding=ROUND_HALF_UP)


def validate_decimal_odds(value: Decimal | int | float | str) -> Decimal:
    """Return a validated decimal price, raising :class:`OddsError` otherwise."""
    odds = _to_decimal(value)
    if odds <= ONE:
        raise OddsError(f"decimal odds must be > 1.0, got {odds}")
    return odds


def implied_probability(decimal_odds: Decimal | int | float | str) -> Decimal:
    """Raw implied probability ``1 / odds`` (still contains the bookmaker margin)."""
    odds = validate_decimal_odds(decimal_odds)
    with localcontext() as ctx:
        ctx.prec = 28
        return ONE / odds


def decimal_from_probability(probability: Decimal | int | float | str) -> Decimal:
    """Fair decimal odds for a probability: ``1 / p``."""
    prob = _to_decimal(probability)
    if prob <= ZERO or prob >= ONE:
        raise OddsError(f"probability must be strictly inside (0, 1), got {prob}")
    with localcontext() as ctx:
        ctx.prec = 28
        return ONE / prob


def fractional_to_decimal(numerator: float, denominator: float) -> Decimal:
    """UK fractional odds (e.g. 7/4) to decimal odds (2.75)."""
    if denominator == 0:
        raise OddsError("fractional denominator must be non-zero")
    if numerator < 0 or denominator < 0:
        raise OddsError("fractional odds must be non-negative")
    return quantize_odds(ONE + (Decimal(str(numerator)) / Decimal(str(denominator))))


def american_to_decimal(american: int | float) -> Decimal:
    """US moneyline to decimal odds. +150 -> 2.50, -200 -> 1.50."""
    value = Decimal(str(american))
    if value == 0:
        raise OddsError("american odds cannot be 0")
    if value > 0:
        return quantize_odds(ONE + value / Decimal(100))
    return quantize_odds(ONE + Decimal(100) / abs(value))


def overround(probabilities: Iterable[Decimal | int | float | str]) -> Decimal:
    """Bookmaker margin: ``sum(implied probabilities) - 1``.

    Positive means the book has a margin; negative means an arbitrage exists
    across the supplied prices (see :mod:`academic_edge_pricing.arb`).
    """
    total = sum((_to_decimal(p) for p in probabilities), ZERO)
    return total - ONE


def book_percentage(probabilities: Iterable[Decimal | int | float | str]) -> Decimal:
    """``sum(implied probabilities)`` expressed in percent (bookmaker's 100%)."""
    return sum((_to_decimal(p) for p in probabilities), ZERO) * Decimal(100)


def expected_value_per_unit(
    probability: Decimal | int | float | str, decimal_odds: Decimal | int | float | str
) -> Decimal:
    """EV of a 1-unit stake: ``p * (odds - 1) - (1 - p)``."""
    prob = _to_decimal(probability)
    odds = validate_decimal_odds(decimal_odds)
    return prob * (odds - ONE) - (ONE - prob)


def edge_bps(
    probability: Decimal | int | float | str, decimal_odds: Decimal | int | float | str
) -> int:
    """Edge in basis points: ``(p * odds - 1) * 10000``, truncated toward zero."""
    prob = _to_decimal(probability)
    odds = validate_decimal_odds(decimal_odds)
    return int(((prob * odds - ONE) * BPS).to_integral_value(rounding=ROUND_HALF_UP))


def payout(
    stake: Decimal | int | float | str, decimal_odds: Decimal | int | float | str
) -> Decimal:
    """Total return (stake + profit) for a winning bet."""
    return _to_decimal(stake) * validate_decimal_odds(decimal_odds)


def profit(
    stake: Decimal | int | float | str, decimal_odds: Decimal | int | float | str
) -> Decimal:
    """Net profit on a winning bet (excludes stake)."""
    stake_dec = _to_decimal(stake)
    return stake_dec * (validate_decimal_odds(decimal_odds) - ONE)


def proportional_normalize(probabilities: Sequence[Decimal]) -> list[Decimal]:
    """Multiplicative normalisation so the vector sums to exactly 1.

    Returns the input unchanged when it (or its sum) is degenerate, so callers
    never receive NaN: the pricing layer treats that as "undefined", not 0.
    """
    total = sum(probabilities, ZERO)
    if total <= ZERO:
        raise OddsError("cannot normalise probabilities summing to <= 0")
    return [p / total for p in probabilities]
