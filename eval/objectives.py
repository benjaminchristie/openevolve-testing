"""Named objective presets for project.yaml's scoring: block, so common cases
don't need primary_metric/mode/scale derived by hand. A project.yaml can
still override any of them directly.

See harness.py's _score_from_metrics: "minimize" -> scale / (value + eps),
"maximize" -> value (no scale needed for an already-bounded metric like
accuracy in [0, 1]).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectivePreset:
    name: str
    description: str
    metric_name: str
    mode: str  # "minimize" | "maximize"
    scale: float


PRESETS = {
    "minimize_time": ObjectivePreset(
        name="minimize_time",
        description="Wall-clock execution time -- smaller is better. The usual choice for performance/HPC-style optimization.",
        metric_name="duration_ms",
        mode="minimize",
        scale=10000.0,
    ),
    "minimize_loss": ObjectivePreset(
        name="minimize_loss",
        description="An ML-style loss/error value (MSE, cross-entropy, ...) -- smaller is better, no fixed upper bound.",
        metric_name="loss",
        mode="minimize",
        scale=100.0,
    ),
    "maximize_accuracy": ObjectivePreset(
        name="maximize_accuracy",
        description="A fraction in [0, 1] (classification accuracy, R^2, ...) -- larger is better.",
        metric_name="accuracy",
        mode="maximize",
        scale=1.0,
    ),
    "maximize_success_rate": ObjectivePreset(
        name="maximize_success_rate",
        description="Fraction of test cases/trials that passed -- larger is better. Distinct from accuracy only in naming; use whichever reads better for your project.",
        metric_name="success_rate",
        mode="maximize",
        scale=1.0,
    ),
    "maximize_throughput": ObjectivePreset(
        name="maximize_throughput",
        description="Items/requests/iterations processed per second -- larger is better.",
        metric_name="throughput",
        mode="maximize",
        scale=1.0,
    ),
}


def get(name: str) -> ObjectivePreset:
    try:
        return PRESETS[name]
    except KeyError:
        available = ", ".join(sorted(PRESETS))
        raise SystemExit(f"Unknown objective preset '{name}'. Available: {available}")
