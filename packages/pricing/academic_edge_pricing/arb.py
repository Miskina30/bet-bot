"""Arbitrage detection and stake allocation across venues.

An arbitrage exists when the sum of implied probabilities across the *best* price
for every outcome of a market is below 1: backing every outcome then returns more
than the total staked, whatever the result.

Everything works on *effective* decimal odds: exchange commission is applied as
``1 + (odds - 1) * (1 - c)`` because commission is charged on net winnings.

Conventions used throughout:

    arbitrage index = 1 - sum(1 / effective_odds)      (> 0 means an arb exists)
    equalised stake = total * (1/o_i) / sum(1/o_i)     (every leg pays the same C)

so ``C = total / sum(1/o_i)`` and the guaranteed gross profit is ``C - total``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from academic_edge_domain.enums import OutcomeKind

from academic_edge_pricing.odds import ONE, ZERO, OddsError, _to_decimal, validate_decimal_odds

BPS = Decimal("10000")
CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class LegInput:
    """One candidate leg of a multi-venue bet."""

    outcome_kind: OutcomeKind
    label: str
    decimal_odds: Decimal | int | float | str
    source_id: str
    venue_name: str = "unknown"
    commission_bps: int = 0
    available_size: Decimal | int | float | str | None = None
    currency: str = "EUR"
    observed_at_iso: str | None = None

    @property
    def odds(self) -> Decimal:
        return validate_decimal_odds(self.decimal_odds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome_kind": str(self.outcome_kind),
            "label": self.label,
            "decimal_odds": str(self.odds),
            "source_id": self.source_id,
            "venue_name": self.venue_name,
            "commission_bps": self.commission_bps,
            "available_size": (
                str(_to_decimal(self.available_size)) if self.available_size is not None else None
            ),
            "currency": self.currency,
            "observed_at": self.observed_at_iso,
        }


@dataclass(frozen=True, slots=True)
class ArbResult:
    """Outcome of an arbitrage evaluation, with the numbers behind it."""

    is_arbitrage: bool
    arbitrage_index: Decimal
    book_percentage: Decimal
    sum_inverse_odds: Decimal
    total_stake: Decimal
    equalized_stakes: dict[str, Decimal] = field(default_factory=dict)
    payoffs: dict[str, Decimal] = field(default_factory=dict)
    guaranteed_profit: Decimal = ZERO
    guaranteed_roi_bps: int = 0
    legs: tuple[LegInput, ...] = ()
    warnings: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    @property
    def guaranteed_roi_pct(self) -> Decimal:
        return Decimal(self.guaranteed_roi_bps) / Decimal(100)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_arbitrage": self.is_arbitrage,
            "arbitrage_index": str(self.arbitrage_index),
            "book_percentage": str(self.book_percentage),
            "total_stake": str(self.total_stake),
            "equalized_stakes": {k: str(v) for k, v in self.equalized_stakes.items()},
            "payoffs": {k: str(v) for k, v in self.payoffs.items()},
            "guaranteed_profit": str(self.guaranteed_profit),
            "guaranteed_roi_bps": self.guaranteed_roi_bps,
            "warnings": list(self.warnings),
            "constraints": dict(self.constraints),
            "legs": [leg.as_dict() for leg in self.legs],
        }


def effective_odds(decimal_odds: Decimal | int | float | str, commission_bps: int = 0) -> Decimal:
    """Decimal odds net of commission charged on winnings (exchanges)."""
    odds = validate_decimal_odds(decimal_odds)
    if commission_bps < 0:
        raise OddsError("commission_bps must be non-negative")
    if commission_bps > 10000:
        raise OddsError("commission_bps cannot exceed 100%")
    if commission_bps == 0:
        return odds
    rate = Decimal(commission_bps) / BPS
    return ONE + (odds - ONE) * (ONE - rate)


def arbitrage_index(legs: Sequence[LegInput]) -> Decimal:
    """``1 - sum(1/effective_odds)``; strictly positive means an arbitrage."""
    total = sum((ONE / effective_odds(leg.decimal_odds, leg.commission_bps) for leg in legs), ZERO)
    return ONE - total


def select_best_legs(
    candidates: Mapping[OutcomeKind, Sequence[LegInput]],
    *,
    required: Sequence[OutcomeKind] | None = None,
) -> list[LegInput] | None:
    """Best (highest effective) price per required outcome across venues.

    ``required`` defaults to every key present in ``candidates``. Pass the full
    outcome set of the market (e.g. home/draw/away) to detect an incomplete book:
    the return is then ``None``, because a market missing a side cannot be
    arbitraged and must never be reported as one.
    """
    outcomes = tuple(required) if required is not None else tuple(candidates)
    best: list[LegInput] = []
    for outcome in outcomes:
        options = candidates.get(outcome)
        if not options:
            return None
        best.append(
            max(options, key=lambda leg: effective_odds(leg.decimal_odds, leg.commission_bps))
        )
    return best


def _round_stakes(
    stakes: dict[str, Decimal], total_stake: Decimal
) -> tuple[dict[str, Decimal], Decimal]:
    """Round to cents while preserving the total exactly.

    Naive rounding can leak or invent cents, which would make a reported
    guaranteed profit wrong by a rounding error. The residual is applied to the
    largest stake so the sum stays exact.
    """
    rounded = {key: value.quantize(CENT, rounding=ROUND_HALF_UP) for key, value in stakes.items()}
    if not rounded:
        return rounded, ZERO
    residual = total_stake - sum(rounded.values(), ZERO)
    if residual != ZERO:
        largest = max(rounded, key=lambda key: rounded[key])
        rounded[largest] = rounded[largest] + residual
    return rounded, sum(rounded.values(), ZERO)


def detect_arbitrage(
    legs: Sequence[LegInput],
    total_stake: Decimal | int | float | str,
    *,
    min_stake: Decimal | int | float | str = Decimal("1"),
    round_to_cents: bool = True,
) -> ArbResult:
    """Evaluate a leg set and (when viable) allocate stakes that equalise payouts.

    The returned ``equalized_stakes`` always sum to the applied total: if the
    requested stake would push a leg below ``min_stake``, the total is raised to
    the smallest amount that satisfies every venue minimum and that adjustment is
    reported in ``constraints`` and ``warnings`` rather than applied silently.
    """
    leg_list = list(legs)
    if not leg_list:
        raise OddsError("detect_arbitrage needs at least one leg")
    if len({leg.outcome_kind for leg in leg_list}) != len(leg_list):
        # Two legs on the same side is a correlated position, not an arbitrage.
        raise OddsError("an arbitrage needs exactly one leg per outcome")

    requested_total = _to_decimal(total_stake)
    if requested_total <= ZERO:
        raise OddsError("total_stake must be positive")
    min_stake_dec = _to_decimal(min_stake)
    if min_stake_dec < ZERO:
        raise OddsError("min_stake cannot be negative")

    inverse_odds = [ONE / effective_odds(leg.decimal_odds, leg.commission_bps) for leg in leg_list]
    sum_inverse = sum(inverse_odds, ZERO)
    index = ONE - sum_inverse
    book_pct = sum_inverse * Decimal(100)
    warnings: list[str] = []

    applied_total = requested_total
    if min_stake_dec > ZERO:
        max_odds = max(effective_odds(leg.decimal_odds, leg.commission_bps) for leg in leg_list)
        # the smallest equalised stake is C / max_odds, so C >= min_stake * max_odds
        required_total = min_stake_dec * max_odds * sum_inverse
        if required_total > applied_total:
            warnings.append(
                "total stake raised to satisfy the venue minimum stake "
                f"({requested_total} -> {required_total.quantize(CENT)})"
            )
            applied_total = required_total

    raw_stakes = {
        leg.label: applied_total * inv / sum_inverse
        for leg, inv in zip(leg_list, inverse_odds, strict=True)
    }

    if round_to_cents:
        stakes, stake_total = _round_stakes(raw_stakes, applied_total.quantize(CENT))
    else:
        stakes = {key: value.quantize(Decimal("0.000001")) for key, value in raw_stakes.items()}
        stake_total = sum(stakes.values(), ZERO)

    payoffs = {
        leg.label: stakes[leg.label] * effective_odds(leg.decimal_odds, leg.commission_bps)
        for leg in leg_list
    }
    profit = min(payoffs.values()) - stake_total
    roi_bps = int((profit / stake_total * BPS).to_integral_value(rounding=ROUND_HALF_UP))

    below_min = sorted(label for label, amount in stakes.items() if amount < min_stake_dec)
    if below_min:
        warnings.append("legs below the venue minimum after rounding: " + ", ".join(below_min))
    if index > ZERO and profit <= ZERO:
        warnings.append(
            "positive arbitrage index but non-positive profit after rounding and commission"
        )

    return ArbResult(
        is_arbitrage=index > ZERO and profit > ZERO,
        arbitrage_index=index,
        book_percentage=book_pct,
        sum_inverse_odds=sum_inverse,
        total_stake=stake_total,
        equalized_stakes=stakes,
        payoffs=payoffs,
        guaranteed_profit=profit,
        guaranteed_roi_bps=roi_bps,
        legs=tuple(leg_list),
        warnings=warnings,
        constraints={
            "requested_total_stake": str(requested_total),
            "applied_total_stake": str(stake_total),
            "min_stake": str(min_stake_dec),
            "commission_applied": True,
            "rounding": "cents" if round_to_cents else "micro",
        },
    )
