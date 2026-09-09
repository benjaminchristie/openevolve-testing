"""Named objective presets shared by scripts/new_project.py and (eventually)
the per-language metrics-reporting helpers.

Writing a project.yaml `scoring:` block by hand means deriving the right
primary_metric/mode/scale combination yourself every time. These presets are
just that derivation done once, for the shapes of objective that actually
come up in practice -- wall-clock time, an ML-style loss, an accuracy or
success-rate fraction, throughput. Pick the closest one; you're never locked
in, since a project.yaml can always override primary_metric/mode/scale
directly instead of (or after) using a preset.

See harness.py's _score_from_metrics for how mode/scale turn a raw metric
value into the scalar score OpenEvolve optimizes:
  - "minimize": score = scale / (value + eps)  -- for costs like time or loss,
    where smaller is better and there's no natural upper bound.
  - "maximize": score = value  -- for fractions/rates that are already
    naturally bounded (e.g. accuracy in [0, 1]), where scale isn't needed.
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
    # Name of the eval.metrics reporter method this preset expects to have
    # supplied `metric_name` (see phase 2: the metrics-reporting helper).
    # Purely documentation until that helper exists; not read by anything yet.
    reporter_hint: str


PRESETS = {
    "minimize_time": ObjectivePreset(
        name="minimize_time",
        description="Wall-clock execution time -- smaller is better. The usual choice for performance/HPC-style optimization.",
        metric_name="duration_ms",
        mode="minimize",
        scale=10000.0,
        reporter_hint="timer() / elapsed_ms()",
    ),
    "minimize_loss": ObjectivePreset(
        name="minimize_loss",
        description="An ML-style loss/error value (MSE, cross-entropy, ...) -- smaller is better, no fixed upper bound.",
        metric_name="loss",
        mode="minimize",
        scale=100.0,
        reporter_hint="report(metrics={\"loss\": ...})",
    ),
    "maximize_accuracy": ObjectivePreset(
        name="maximize_accuracy",
        description="A fraction in [0, 1] (classification accuracy, R^2, ...) -- larger is better.",
        metric_name="accuracy",
        mode="maximize",
        scale=1.0,
        reporter_hint="report(metrics={\"accuracy\": ...})",
    ),
    "maximize_success_rate": ObjectivePreset(
        name="maximize_success_rate",
        description="Fraction of test cases/trials that passed -- larger is better. Distinct from accuracy only in naming; use whichever reads better for your project.",
        metric_name="success_rate",
        mode="maximize",
        scale=1.0,
        reporter_hint="report(metrics={\"success_rate\": ...})",
    ),
    "maximize_throughput": ObjectivePreset(
        name="maximize_throughput",
        description="Items/requests/iterations processed per second -- larger is better.",
        metric_name="throughput",
        mode="maximize",
        scale=1.0,
        reporter_hint="report(metrics={\"throughput\": ...})",
    ),
}


def get(name: str) -> ObjectivePreset:
    try:
        return PRESETS[name]
    except KeyError:
        available = ", ".join(sorted(PRESETS))
        raise SystemExit(f"Unknown objective preset '{name}'. Available: {available}")
