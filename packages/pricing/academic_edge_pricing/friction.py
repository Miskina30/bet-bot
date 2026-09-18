"""Friction: everything between a quoted price and a real outcome.

The MVP is deliberately conservative: a quoted price is not a fillable price.

* **slippage** -- the best quote may be gone by the time you act;
* **commission** -- exchanges charge on net winnings;
* **FX spread** -- converting currencies costs something;
* **age haircut** -- an old quote is worth less, modelled in bps per minute and
  capped. A quote older than ``max_quote_age_seconds`` is *stale*: it can never
  make an opportunity actionable (asserted by property tests).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol, runtime_checkable

from academic_edge_domain.enums import FreshnessLabel, OutcomeKind
from academic_edge_domain.time import seconds_between

from academic_edge_pricing.arb import BPS, LegInput, effective_odds
from academic_edge_pricing.odds import ONE, ZERO, OddsError, validate_decimal_odds


@runtime_checkable
class FrictionLeg(Protocol):
    """Structural type so friction works with LegInput or any DB-backed quote."""

    outcome_kind: OutcomeKind
    label: str
    decimal_odds: Decimal | int | float | str
    source_id: str
    commission_bps: int
    observed_at_iso: str | None


@dataclass(frozen=True, slots=True)
class FrictionConfig:
    """All frictions in bps, plus the freshness window."""

    max_quote_age_seconds: int = 180
    slippage_bps: int = 15
    exchange_fee_bps: int = 200
    fx_spread_bps: int = 25
    quote_age_haircut_bps_per_min: int = 20
    max_quote_age_haircut_bps: int = 200

    @classmethod
    def from_settings(cls, settings: Any) -> FrictionConfig:
        """Build from the 12-factor settings object (the PRICING_* variables)."""
        return cls(
            max_quote_age_seconds=settings.pricing_max_quote_age_seconds,
            slippage_bps=settings.pricing_slippage_bps,
            exchange_fee_bps=settings.pricing_exchange_fee_bps,
            fx_spread_bps=settings.pricing_fx_spread_bps,
            quote_age_haircut_bps_per_min=settings.pricing_quote_age_haircut_bps_per_min,
            max_quote_age_haircut_bps=settings.pricing_max_quote_age_haircut_bps,
        )

    def validate(self) -> None:
        for name in (
            "slippage_bps",
            "exchange_fee_bps",
            "fx_spread_bps",
            "quote_age_haircut_bps_per_min",
            "max_quote_age_haircut_bps",
        ):
            if getattr(self, name) < 0:
                raise OddsError(f"{name} cannot be negative")
        if self.max_quote_age_seconds <= 0:
            raise OddsError("max_quote_age_seconds must be positive")


@dataclass(frozen=True, slots=True)
class LegFriction:
    """Per-leg friction breakdown."""

    label: str
    outcome_kind: OutcomeKind
    source_id: str
    quoted_odds: Decimal
    effective_odds_before: Decimal
    effective_odds_after: Decimal
    slippage_bps: int
    commission_bps: int
    fx_bps: int
    age_haircut_bps: int
    age_seconds: float
    freshness: FreshnessLabel
    is_stale: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "outcome_kind": str(self.outcome_kind),
            "source_id": self.source_id,
            "quoted_odds": str(self.quoted_odds),
            "effective_odds_before": str(self.effective_odds_before),
            "effective_odds_after": str(self.effective_odds_after),
            "slippage_bps": self.slippage_bps,
            "commission_bps": self.commission_bps,
            "fx_bps": self.fx_bps,
            "age_haircut_bps": self.age_haircut_bps,
            "age_seconds": round(self.age_seconds, 3),
            "freshness": str(self.freshness),
            "is_stale": self.is_stale,
        }


@dataclass(frozen=True, slots=True)
class FrictionBreakdown:
    """Everything the UI needs to explain a price after friction."""

    legs: tuple[LegFriction, ...]
    config: FrictionConfig
    min_net_edge_bps: int = 0

    @property
    def has_stale_leg(self) -> bool:
        return any(leg.is_stale for leg in self.legs)

    @property
    def worst_age_seconds(self) -> float:
        return max((leg.age_seconds for leg in self.legs), default=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "legs": [leg.as_dict() for leg in self.legs],
            "config": {
                "max_quote_age_seconds": self.config.max_quote_age_seconds,
                "slippage_bps": self.config.slippage_bps,
                "exchange_fee_bps": self.config.exchange_fee_bps,
                "fx_spread_bps": self.config.fx_spread_bps,
                "quote_age_haircut_bps_per_min": self.config.quote_age_haircut_bps_per_min,
                "max_quote_age_haircut_bps": self.config.max_quote_age_haircut_bps,
            },
            "min_net_edge_bps": self.min_net_edge_bps,
            "has_stale_leg": self.has_stale_leg,
            "worst_age_seconds": round(self.worst_age_seconds, 3),
        }


@dataclass(frozen=True, slots=True)
class ActionabilityDecision:
    """Whether an opportunity may be surfaced as actionable, and why/why not."""

    is_actionable: bool
    net_edge_bps: int
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_actionable": self.is_actionable,
            "net_edge_bps": self.net_edge_bps,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def classify_freshness(age_seconds: float, max_age_seconds: int) -> FreshnessLabel:
    """fresh (< 1/3 of the window), aging (< window), stale (>= window)."""
    if age_seconds < 0:
        raise OddsError("quote age cannot be negative")
    third = max_age_seconds / 3.0
    if age_seconds < third:
        return FreshnessLabel.FRESH
    if age_seconds < max_age_seconds:
        return FreshnessLabel.AGING
    return FreshnessLabel.STALE


def _haircut_bps(age_seconds: float, config: FrictionConfig) -> int:
    """Quote-age haircut in bps: linear in age, capped."""
    minutes = age_seconds / 60.0
    raw = config.quote_age_haircut_bps_per_min * minutes
    return int(min(raw, config.max_quote_age_haircut_bps))


def apply_friction(
    legs: Sequence[LegInput],
    config: FrictionConfig,
    now: dt.datetime,
    *,
    fx_bps: int | None = None,
) -> FrictionBreakdown:
    """Post-friction effective odds for every leg.

    ``observed_at_iso`` on each leg is compared with ``now`` (both UTC). A leg
    without a timestamp is treated as stale: an unknown age must never be
    presented as fresh.
    """
    config.validate()
    rows: list[LegFriction] = []
    for leg in legs:
        quoted = validate_decimal_odds(leg.decimal_odds)
        before = effective_odds(quoted, leg.commission_bps)

        if leg.observed_at_iso is None:
            age_seconds = float("inf")
            freshness = FreshnessLabel.STALE
            haircut = config.max_quote_age_haircut_bps
        else:
            observed = dt.datetime.fromisoformat(leg.observed_at_iso)
            age_seconds = max(0.0, seconds_between(now, observed))
            freshness = classify_freshness(age_seconds, config.max_quote_age_seconds)
            haircut = _haircut_bps(age_seconds, config)

        fx = config.fx_spread_bps if fx_bps is None else int(fx_bps)
        total_bps = config.slippage_bps + fx + haircut
        after = before * (ONE - Decimal(total_bps) / BPS)

        rows.append(
            LegFriction(
                label=leg.label,
                outcome_kind=leg.outcome_kind,
                source_id=leg.source_id,
                quoted_odds=quoted,
                effective_odds_before=before,
                effective_odds_after=after.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                slippage_bps=config.slippage_bps,
                commission_bps=leg.commission_bps,
                fx_bps=fx,
                age_haircut_bps=haircut,
                age_seconds=age_seconds,
                freshness=freshness,
                is_stale=freshness is FreshnessLabel.STALE,
            )
        )
    return FrictionBreakdown(legs=tuple(rows), config=config)


def assess_actionability(
    breakdown: FrictionBreakdown,
    min_net_edge_bps: int,
    *,
    rules_match: bool = True,
    size_covers_stake: bool = True,
    require_fresh: bool = True,
) -> ActionabilityDecision:
    """Decide whether an opportunity is actionable, with explicit reasons.

    ``is_actionable`` is true only when every gate passes: freshness, settlement
    rule agreement, size coverage and the net-edge threshold.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    if require_fresh and breakdown.has_stale_leg:
        stale = [leg.label for leg in breakdown.legs if leg.is_stale]
        reasons.append(
            "not actionable: stale quote(s) beyond "
            f"{breakdown.config.max_quote_age_seconds}s: {', '.join(stale)}"
        )
    if not rules_match:
        reasons.append("not actionable: settlement rules do not match across venues")
    if not size_covers_stake:
        reasons.append("not actionable: available size does not cover the stake")

    if not breakdown.legs:
        reasons.append("not actionable: no legs")
        return ActionabilityDecision(False, 0, reasons=reasons, warnings=warnings)

    total_inverse = sum((ONE / leg.effective_odds_after for leg in breakdown.legs), ZERO)
    net_index = ONE - total_inverse
    net_edge_bps = int((net_index * BPS).to_integral_value(rounding=ROUND_HALF_UP))

    if net_edge_bps >= min_net_edge_bps:
        reasons.append(f"net edge {net_edge_bps} bps >= required {min_net_edge_bps} bps")
    else:
        reasons.append(f"net edge {net_edge_bps} bps below the required {min_net_edge_bps} bps")
        warnings.append("near miss: the edge disappears after friction")

    gates_pass = (
        (not require_fresh or not breakdown.has_stale_leg)
        and rules_match
        and size_covers_stake
        and net_edge_bps >= min_net_edge_bps
    )
    return ActionabilityDecision(gates_pass, net_edge_bps, reasons=reasons, warnings=warnings)
