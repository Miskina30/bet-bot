"""Pricing engine: odds, de-vig, arbitrage, staking, value and friction.

All functions are pure (no I/O, no clocks except where ``now`` is passed in) and
work on :class:`decimal.Decimal` so results are reproducible and property tests
can assert exact invariants.

Public surface::

    from academic_edge_pricing import (
        OddsError, implied_probability, decimal_from_probability, overround,
        edge_bps, expected_value_per_unit,
        de_vig, de_vig_odds, consensus_de_vig, DeVigResult,
        LegInput, ArbResult, effective_odds, arbitrage_index, select_best_legs,
        detect_arbitrage, kelly_stake, equalize_stakes, StakePlan,
        ValueAssessment, evaluate_model_value,
        FrictionConfig, FrictionBreakdown, apply_friction, assess_actionability,
        ActionabilityDecision, classify_freshness,
    )
"""

from __future__ import annotations

from academic_edge_pricing.arb import (
    ArbResult,
    LegInput,
    arbitrage_index,
    detect_arbitrage,
    effective_odds,
    select_best_legs,
)
from academic_edge_pricing.devig import (
    DeVigResult,
    consensus_de_vig,
    de_vig,
    de_vig_odds,
    multiplicative_de_vig,
    power_de_vig,
)
from academic_edge_pricing.friction import (
    ActionabilityDecision,
    FrictionBreakdown,
    FrictionConfig,
    LegFriction,
    apply_friction,
    assess_actionability,
    classify_freshness,
)
from academic_edge_pricing.odds import (
    OddsError,
    american_to_decimal,  # noqa: F401  (re-exported public API)
    decimal_from_probability,
    edge_bps,
    expected_value_per_unit,
    fractional_to_decimal,  # noqa: F401  (re-exported public API)
    implied_probability,
    overround,
    quantize_odds,
    validate_decimal_odds,
)
from academic_edge_pricing.staking import StakePlan, equalize_stakes, kelly_stake
from academic_edge_pricing.value import ValueAssessment, evaluate_model_value

__all__ = [
    "ActionabilityDecision",
    "ArbResult",
    "DeVigResult",
    "FrictionBreakdown",
    "FrictionConfig",
    "LegFriction",
    "LegInput",
    "OddsError",
    "StakePlan",
    "ValueAssessment",
    "apply_friction",
    "arbitrage_index",
    "assess_actionability",
    "classify_freshness",
    "consensus_de_vig",
    "de_vig",
    "de_vig_odds",
    "decimal_from_probability",
    "detect_arbitrage",
    "edge_bps",
    "effective_odds",
    "equalize_stakes",
    "evaluate_model_value",
    "expected_value_per_unit",
    "implied_probability",
    "kelly_stake",
    "multiplicative_de_vig",
    "overround",
    "power_de_vig",
    "quantize_odds",
    "select_best_legs",
    "validate_decimal_odds",
]
