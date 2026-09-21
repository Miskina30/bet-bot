"""Walk-forward splitting and evaluation metrics (pure stdlib).

Metrics: multiclass log loss, Brier score, RPS, ECE, CLV, net ROI, turnover
and max drawdown for a 1-unit level-stake backtest. Each function is
documented with its formula and returns ``None`` when undefined (not NaN).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from academic_edge_forecasting.elo import MatchResult


def walk_forward_splits(
    results: list[MatchResult],
    *,
    min_train: int = 200,
    test_size: int = 20,
    step: int = 10,
) -> Iterator[tuple[list[MatchResult], list[MatchResult]]]:
    """Yield strictly expanding-window (train, test) splits.

    Training is always ``results[:split_index]``; test is the next
    ``test_size`` matches. Advancing by ``step`` gives overlapping test
    windows but never leaks future data into training.
    """
    chronological = sorted(results, key=lambda r: r.played_on)
    n = len(chronological)
    if n < min_train + test_size:
        return
    split = min_train
    while split + test_size <= n:
        yield chronological[:split], chronological[split : split + test_size]
        split += step


def multiclass_log_loss(
    probabilities: list[dict[str, float]], outcomes: list[str], labels: list[str]
) -> float | None:
    """``-mean(log(p[label]))`` over all samples."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return None
    if not labels:
        return None
    total = 0.0
    for probs, outcome in zip(probabilities, outcomes, strict=True):
        p = probs.get(outcome, 0.0)
        total += math.log(max(p, 1e-15))
    return -total / len(probabilities)


def brier_score(
    probabilities: list[dict[str, float]], outcomes: list[str], labels: list[str]
) -> float | None:
    """Multiclass Brier: ``mean(sum((p_i - y_i)^2))``."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return None
    if not labels:
        return None
    total = 0.0
    for probs, outcome in zip(probabilities, outcomes, strict=True):
        score = 0.0
        for label in labels:
            actual = 1.0 if label == outcome else 0.0
            score += (probs.get(label, 0.0) - actual) ** 2
        total += score
    return total / len(probabilities)


def ranked_probability_score(
    probabilities: list[dict[str, float]], outcomes: list[str], labels: list[str]
) -> float | None:
    """RPS for ordered outcomes (e.g. home < draw < away)."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return None
    if len(labels) < 2:
        return None
    total = 0.0
    for probs, outcome in zip(probabilities, outcomes, strict=True):
        cumulative_p = 0.0
        cumulative_y = 0.0
        rps = 0.0
        for label in labels[:-1]:
            cumulative_p += probs.get(label, 0.0)
            cumulative_y += 1.0 if outcome == label else 0.0
            rps += (cumulative_p - cumulative_y) ** 2
        total += rps / (len(labels) - 1)
    return total / len(probabilities)


def expected_calibration_error(
    probabilities: list[dict[str, float]],
    outcomes: list[str],
    target_label: str,
    *,
    n_bins: int = 10,
) -> float | None:
    """ECE for a binary outcome."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return None
    bin_sums = [0.0] * n_bins
    bin_counts = [0] * n_bins
    for probs, outcome in zip(probabilities, outcomes, strict=True):
        p = probs.get(target_label, 0.0)
        actual = 1.0 if outcome == target_label else 0.0
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bin_sums[bin_idx] += actual
        bin_counts[bin_idx] += 1
    total = sum(bin_counts)
    if total == 0:
        return None
    ece = 0.0
    for i in range(n_bins):
        if bin_counts[i] == 0:
            continue
        confidence = (i + 0.5) / n_bins
        accuracy = bin_sums[i] / bin_counts[i]
        ece += abs(confidence - accuracy) * bin_counts[i] / total
    return ece


def closing_line_value(model_fair_odds: float, closing_odds: float) -> float | None:
    """``(closing_odds / model_fair_odds) - 1``. Positive means you beat the close."""
    if model_fair_odds <= 0 or closing_odds <= 0:
        return None
    return (closing_odds / model_fair_odds) - 1.0


def net_roi(pnl: list[float], stakes: list[float]) -> float | None:
    """``sum(pnl) / sum(stakes)``. ``None`` when stakes are zero."""
    total_stakes = sum(stakes)
    if total_stakes <= 0:
        return None
    return sum(pnl) / total_stakes


def max_drawdown(cumulative_pnl: list[float]) -> float | None:
    """Maximum drawdown from peak."""
    if not cumulative_pnl:
        return None
    peak = cumulative_pnl[0]
    max_dd = 0.0
    for value in cumulative_pnl:
        if value > peak:
            peak = value
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
    return max_dd


def turnover(stakes: list[float]) -> float:
    return sum(stakes)


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Aggregate evaluation over walk-forward splits."""

    log_loss: float | None = None
    brier: float | None = None
    rps: float | None = None
    ece: float | None = None
    clv_mean: float | None = None
    net_roi: float | None = None
    turnover: float = 0.0
    max_drawdown: float | None = None
    n_splits: int = 0
    n_test_matches: int = 0
    model_name: str = ""
    model_version: str = ""
    algorithm: str = ""
    train_window: tuple[str, str] | None = None
    calibration_window: tuple[str, str] | None = None
