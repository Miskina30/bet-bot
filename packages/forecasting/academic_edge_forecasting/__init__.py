"""Academic Edge forecasting: Elo, Poisson/Dixon-Coles, walk-forward evaluation.

Public surface::

    from academic_edge_forecasting import (
        EloModel, MatchResult, PoissonModel,
        walk_forward_splits, WalkForwardResult,
        multiclass_log_loss, brier_score, ranked_probability_score,
        expected_calibration_error, closing_line_value, net_roi,
        max_drawdown, turnover,
    )
"""

from __future__ import annotations

from academic_edge_forecasting.elo import EloModel, MatchResult
from academic_edge_forecasting.evaluate import (
    WalkForwardResult,
    brier_score,
    closing_line_value,
    expected_calibration_error,
    max_drawdown,
    multiclass_log_loss,
    net_roi,
    ranked_probability_score,
    turnover,
    walk_forward_splits,
)
from academic_edge_forecasting.poisson import PoissonModel

__all__ = [
    "EloModel",
    "MatchResult",
    "PoissonModel",
    "WalkForwardResult",
    "brier_score",
    "closing_line_value",
    "expected_calibration_error",
    "max_drawdown",
    "multiclass_log_loss",
    "net_roi",
    "ranked_probability_score",
    "turnover",
    "walk_forward_splits",
]
