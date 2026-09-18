import datetime as dt
import sys

sys.path.insert(0, "packages/forecasting")
sys.path.insert(0, "packages/domain")

from academic_edge_forecasting import (
    EloModel,
    MatchResult,
    PoissonModel,
    walk_forward_splits,
    multiclass_log_loss,
    brier_score,
    ranked_probability_score,
    expected_calibration_error,
)

# --- Elo ---
results = [
    MatchResult("A", "B", 2, 1, dt.date(2025, 1, 1)),
    MatchResult("B", "A", 0, 2, dt.date(2025, 2, 1)),
    MatchResult("A", "C", 1, 1, dt.date(2025, 3, 1)),
    MatchResult("C", "B", 3, 0, dt.date(2025, 4, 1)),
]
model = EloModel().fit(results)
p = model.predict("A", "C")
print("elo predict:", p)
assert abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1.0) < 1e-9, "Elo probs must sum to 1"
print("elo probs sum to 1: OK")

# --- Poisson ---
model_p = PoissonModel().fit(results)
p2 = model_p.predict_1x2("A", "B")
print("poisson 1x2:", p2)
assert abs(sum(p2.values()) - 1.0) < 1e-6, "Poisson 1x2 must sum to 1"
b = model_p.predict_btts("A", "B")
print("poisson btts:", b)
assert abs(b["p_yes"] + b["p_no"] - 1.0) < 1e-6, "BTTS must sum to 1"
t = model_p.predict_totals("A", "B")
print("poisson totals:", t)
assert abs(t["p_over"] + t["p_under"] - 1.0) < 1e-6, "Totals must sum to 1"
print("poisson all markets sum to 1: OK")

# --- Walk-forward ---
splits = list(walk_forward_splits(results, min_train=2, test_size=1, step=1))
print(f"walk_forward_splits produced {len(splits)} splits")
for i, (train_set, test_set) in enumerate(splits):
    print(f"  split {i}: train={len(train_set)} test={len(test_set)}")
    max_train_date = max(m.played_on for m in train_set)
    for m in test_set:
        assert m.played_on > max_train_date, (
            f"leakage! test match {m.played_on} <= max train date {max_train_date}"
        )
print("walk-forward no leakage: OK")

# --- Metrics ---
probs = [{"p_home": 0.5, "p_draw": 0.3, "p_away": 0.2}]
outcomes = ["home"]
labels = ["home", "draw", "away"]
ll = multiclass_log_loss(probs, outcomes, labels)
print(f"log_loss: {ll}")
bs = brier_score(probs, outcomes, labels)
print(f"brier: {bs}")
rps = ranked_probability_score(probs, outcomes, labels)
print(f"rps: {rps}")
ece = expected_calibration_error(probs, outcomes, "home")
print(f"ece: {ece}")
print("ALL FORECASTING SMOKE TESTS PASSED")