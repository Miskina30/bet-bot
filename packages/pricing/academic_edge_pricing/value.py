"""Model-vs-market value (expected value) assessment.

This is the "is the model's probability different enough from the market's to
matter, after costs?" question. It deliberately reports *near misses* with
reasons instead of only boolean yes/no, because an analyst needs to know whether
an opportunity failed on edge, on uncertainty or on a suspicious disagreement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from academic_edge_pricing.arb import BPS
from academic_edge_pricing.odds import (
    ONE,
    OddsError,
    _to_decimal,
    edge_bps,
    expected_value_per_unit,
    implied_probability,
    validate_decimal_odds,
)

# A model that disagrees with the market by more than this is more likely to be
# wrong (or looking at a stale quote) than to have found a genuine edge.
MAX_PLAUSIBLE_DISAGREEMENT = Decimal("0.15")


@dataclass(frozen=True, slots=True)
class ValueAssessment:
    """Result of comparing a model probability with an offered price."""

    net_edge_bps: int
    gross_edge_bps: int
    model_probability: Decimal
    market_probability: Decimal
    fair_odds: Decimal
    offered_odds: Decimal
    expected_value_per_unit: Decimal
    confidence: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    abstain: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "net_edge_bps": self.net_edge_bps,
            "gross_edge_bps": self.gross_edge_bps,
            "model_probability": str(self.model_probability),
            "market_probability": str(self.market_probability),
            "fair_odds": str(self.fair_odds),
            "offered_odds": str(self.offered_odds),
            "expected_value_per_unit": str(self.expected_value_per_unit),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "abstain": self.abstain,
        }


def _confidence_from_uncertainty(uncertainty: float | None) -> float:
    """Map model uncertainty to confidence in [0, 1].

    Monotone decreasing: uncertainty 0 -> 1.0, uncertainty >= 0.5 -> 0.0.
    Missing uncertainty is treated as maximum uncertainty (least confidence),
    because an unquantified model must not be presented as a confident one.
    """
    if uncertainty is None:
        return 0.0
    if uncertainty < 0:
        raise OddsError("uncertainty cannot be negative")
    return max(0.0, 1.0 - uncertainty / 0.5)


def evaluate_model_value(
    model_probability: Decimal | int | float | str,
    offered_decimal_odds: Decimal | int | float | str,
    *,
    market_probability: Decimal | int | float | str | None = None,
    uncertainty: float | None = None,
    min_edge_bps: int = 0,
    commission_bps: int = 0,
) -> ValueAssessment:
    """Assess whether an offered price beats the model after friction.

    ``market_probability`` defaults to the raw implied probability of the offered
    price. For a fairer benchmark pass a de-vigged consensus probability from
    :func:`academic_edge_pricing.devig.consensus_de_vig` instead.
    """
    model_prob = _to_decimal(model_probability)
    if model_prob <= 0 or model_prob >= 1:
        raise OddsError("model_probability must be strictly inside (0, 1)")
    odds = validate_decimal_odds(offered_decimal_odds)

    if market_probability is not None:
        market_prob = _to_decimal(market_probability)
    else:
        market_prob = implied_probability(odds)

    if market_prob <= 0 or market_prob >= 1:
        raise OddsError("market_probability must be strictly inside (0, 1)")

    reasons: list[str] = []
    warnings: list[str] = []
    confidence = _confidence_from_uncertainty(uncertainty)

    gross = edge_bps(model_prob, odds)
    # commission is charged on winnings, so it scales the profitable part only
    net_odds = ONE + (odds - ONE) * (ONE - Decimal(commission_bps) / BPS)
    net = edge_bps(model_prob, net_odds)
    ev_per_unit = expected_value_per_unit(model_prob, net_odds)
    fair = ONE / model_prob

    disagreement = abs(model_prob - market_prob)
    if disagreement > MAX_PLAUSIBLE_DISAGREEMENT:
        warnings.append(
            f"model disagrees with the market by {disagreement:.3f} "
            f"(>{MAX_PLAUSIBLE_DISAGREEMENT}); more likely a model error or a stale "
            "quote than a genuine edge"
        )
    if uncertainty is not None and uncertainty > 0.25:
        warnings.append(f"high model uncertainty ({uncertainty:.3f}); consider abstaining")
        if uncertainty > 0.4:
            reasons.append("abstaining: uncertainty above the 0.4 threshold")
    if commission_bps:
        reasons.append(f"commission of {commission_bps} bps applied to winnings")

    if net >= min_edge_bps:
        reasons.append(f"net edge {net} bps >= required {min_edge_bps} bps at offered odds {odds}")
    else:
        reasons.append(f"net edge {net} bps below the required {min_edge_bps} bps (near miss)")

    abstain = uncertainty is not None and uncertainty > 0.4
    return ValueAssessment(
        net_edge_bps=net,
        gross_edge_bps=gross,
        model_probability=model_prob,
        market_probability=market_prob,
        fair_odds=fair,
        offered_odds=odds,
        expected_value_per_unit=ev_per_unit,
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
        abstain=abstain,
    )
