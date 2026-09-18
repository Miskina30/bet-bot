"""Overround removal ("de-vigging").

Given raw decimal odds for a complete market (1X2, totals, BTTS) the implied
probabilities sum to more than 1. De-vigging recovers the bookmaker's fair
probabilities so they can be compared with a model and with other venues.

Two methods, as specified in the brief:

* ``multiplicative`` -- ``p_i / sum(p)``: the margin is spread proportionally.
  Simple, and known to over-favour longshots (favourite-longshot bias).
* ``power`` -- find ``k`` such that ``sum(p_i ** k) == 1`` (power / odds-ratio
  method). Shrinks longshots more than favourites, usually closer to a sharp book.

Neither method is "correct"; both are estimators. Every result records the method,
the input book and the achieved residual so downstream comparison is auditable
(brief: label the de-vig method on every alert).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from academic_edge_domain.enums import DeVigMethod

from academic_edge_pricing.odds import (
    ONE,
    ZERO,
    OddsError,
    _to_decimal,
    implied_probability,
    overround,
    proportional_normalize,
    quantize_probability,
)

DEFAULT_POWER_TOLERANCE = 1e-12
DEFAULT_POWER_MAX_ITERATIONS = 200
POWER_UPPER_BOUND = 100.0


@dataclass(frozen=True, slots=True)
class DeVigResult:
    """Fair probabilities plus everything needed to audit how they were derived."""

    method: DeVigMethod
    fair_probabilities: tuple[Decimal, ...]
    raw_probabilities: tuple[Decimal, ...]
    overround: Decimal
    book_percentage: Decimal
    residual: Decimal
    exponent: Decimal | None = None
    iterations: int = 0
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def sum_fair(self) -> Decimal:
        return sum(self.fair_probabilities, ZERO)

    @property
    def fair_odds(self) -> tuple[Decimal, ...]:
        return tuple(
            (ONE / p).quantize(Decimal("0.000001")) if p > ZERO else ZERO
            for p in self.fair_probabilities
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": str(self.method),
            "fair_probabilities": [str(p) for p in self.fair_probabilities],
            "book_percentage": str(self.book_percentage),
            "overround": str(self.overround),
            "residual": str(self.residual),
            "exponent": str(self.exponent) if self.exponent is not None else None,
            "iterations": self.iterations,
        }


def multiplicative_de_vig(
    probabilities: Sequence[Decimal | int | float | str],
) -> DeVigResult:
    """Proportional normalisation: the margin is spread evenly across outcomes."""
    raw = tuple(_to_decimal(p) for p in probabilities)
    if not raw:
        raise OddsError("de-vig needs at least one probability")
    if any(p <= ZERO for p in raw):
        raise OddsError("de-vig requires strictly positive raw probabilities")

    fair = proportional_normalize(list(raw))
    # Exact renormalisation: distribute the (tiny) division residual onto the
    # largest share so the vector sums to exactly 1 at full precision.
    residual = ONE - sum(fair, ZERO)
    if residual != ZERO:
        largest = max(range(len(fair)), key=lambda i: fair[i])
        fair[largest] += residual
    return DeVigResult(
        method=DeVigMethod.MULTIPLICATIVE,
        fair_probabilities=tuple(fair),
        raw_probabilities=raw,
        overround=overround(raw),
        book_percentage=(sum(raw, ZERO) * Decimal(100)),
        residual=sum(fair, ZERO) - ONE,
        iterations=1,
    )


def _power_sum(probabilities: Sequence[float], exponent: float) -> float:
    """``sum(p_i ** k)`` in floating point (used only for the bisection)."""
    total = 0.0
    for p in probabilities:
        total += math.exp(exponent * math.log(p))
    return total


def power_de_vig(
    probabilities: Sequence[Decimal | int | float | str],
    *,
    tolerance: float = DEFAULT_POWER_TOLERANCE,
    max_iterations: float = DEFAULT_POWER_MAX_ITERATIONS,
) -> DeVigResult:
    """Solve ``sum(p_i ** k) == 1`` by bisection, then refine in Decimal.

    For a valid book ``sum(p_i) > 1`` with every ``p_i < 1``, so
    ``f(k) = sum(p_i ** k) - 1`` is strictly decreasing, ``f(1) > 0`` and
    ``f(k) -> -1``: bisection is well posed. The final vector is renormalised
    multiplicatively so the returned probabilities sum to exactly 1 at full
    precision, and the achieved residual is *recorded* rather than assumed zero.
    """
    raw = tuple(_to_decimal(p) for p in probabilities)
    if not raw:
        raise OddsError("de-vig needs at least one probability")
    if any(p <= ZERO or p >= ONE for p in raw):
        raise OddsError("power de-vig requires raw probabilities inside (0, 1)")

    floats = [float(p) for p in raw]
    if abs(sum(floats) - 1.0) <= tolerance:
        # Already a fair book (or a single-outcome market): nothing to solve.
        return DeVigResult(
            method=DeVigMethod.POWER,
            fair_probabilities=raw,
            raw_probabilities=raw,
            overround=overround(raw),
            book_percentage=sum(raw, ZERO) * Decimal(100),
            residual=sum(raw, ZERO) - ONE,
            exponent=ONE,
            iterations=0,
        )

    iteration_limit = int(max_iterations)
    low, high = 1.0, POWER_UPPER_BOUND
    iterations = 0
    exponent = 1.0
    for iterations in range(1, iteration_limit + 1):  # noqa: B007  (counts attempts)
        exponent = (low + high) / 2.0
        value = _power_sum(floats, exponent) - 1.0
        if abs(value) <= tolerance:
            break
        if value > 0:
            low = exponent
        else:
            high = exponent

    powered = [Decimal(str(math.exp(exponent * math.log(p)))) for p in floats]
    fair = proportional_normalize(powered)
    quantized = [quantize_probability(p) for p in fair]
    # Storage resolution is 1e-9: an extreme book (heavy favourite, wide margin)
    # can drive a longshot below it. Keep the sum exact at full precision by
    # putting the residual on the largest share, and record it.
    residual = ONE - sum(quantized, ZERO)
    if residual != ZERO:
        largest = max(range(len(quantized)), key=lambda i: quantized[i])
        quantized[largest] += residual

    return DeVigResult(
        method=DeVigMethod.POWER,
        fair_probabilities=tuple(quantized),
        raw_probabilities=raw,
        overround=overround(raw),
        book_percentage=sum(raw, ZERO) * Decimal(100),
        residual=sum(quantized, ZERO) - ONE,
        exponent=Decimal(str(exponent)).quantize(Decimal("0.000000001")),
        iterations=iterations,
        inputs={
            "note": (
                "extreme books can push an outcome below the 1e-9 storage "
                "resolution; the residual is kept on the largest share"
            )
        },
    )


def de_vig(
    probabilities: Sequence[Decimal | int | float | str],
    method: DeVigMethod = DeVigMethod.MULTIPLICATIVE,
) -> DeVigResult:
    """Dispatch to the requested de-vig method."""
    if method is DeVigMethod.MULTIPLICATIVE:
        return multiplicative_de_vig(probabilities)
    if method is DeVigMethod.POWER:
        return power_de_vig(probabilities)
    raise ValueError(f"unsupported de-vig method: {method!r}")


def de_vig_odds(
    decimal_odds: Sequence[Decimal | int | float | str],
    method: DeVigMethod = DeVigMethod.MULTIPLICATIVE,
) -> DeVigResult:
    """Convenience wrapper: decimal odds in, fair probabilities out."""
    raw = [implied_probability(o) for o in decimal_odds]
    return de_vig(raw, method)


def consensus_de_vig(
    books: Iterable[Sequence[Decimal | int | float | str]],
    method: DeVigMethod = DeVigMethod.MULTIPLICATIVE,
    *,
    weights: Sequence[float] | None = None,
) -> DeVigResult:
    """Average de-vigged probabilities across venues (the "consensus").

    Averaging *de-vigged* probabilities rather than raw odds stops one
    high-margin book from distorting the consensus. Weights default to equal and
    are normalised; supplying weights of the wrong length is a programming error.
    """
    book_list = [list(b) for b in books]
    if not book_list:
        raise OddsError("consensus de-vig needs at least one book")
    widths = {len(b) for b in book_list}
    if len(widths) != 1:
        raise OddsError("all books must cover the same number of outcomes")
    width = widths.pop()

    if weights is None:
        weight_list = [1.0] * len(book_list)
    else:
        if len(weights) != len(book_list):
            raise OddsError("weights length must match the number of books")
        weight_list = [float(w) for w in weights]
        if any(w < 0 for w in weight_list) or sum(weight_list) <= 0:
            raise OddsError("weights must be non-negative and not all zero")

    weight_total = sum(weight_list)
    accumulated = [ZERO] * width
    raw_accumulated = [ZERO] * width
    for book, weight in zip(book_list, weight_list, strict=True):
        result = de_vig_odds(book, method)
        share = Decimal(str(weight / weight_total))
        for index, probability in enumerate(result.fair_probabilities):
            accumulated[index] += probability * share
        for index, probability in enumerate(result.raw_probabilities):
            raw_accumulated[index] += probability * share

    fair = proportional_normalize(accumulated)
    return DeVigResult(
        method=method,
        fair_probabilities=tuple(quantize_probability(p) for p in fair),
        raw_probabilities=tuple(raw_accumulated),
        overround=overround(raw_accumulated),
        book_percentage=sum(raw_accumulated, ZERO) * Decimal(100),
        residual=sum(fair, ZERO) - ONE,
        exponent=None,
        inputs={
            "books": len(book_list),
            "weights": weight_list,
            "note": "equal-or-weighted consensus of de-vigged probabilities",
        },
    )
