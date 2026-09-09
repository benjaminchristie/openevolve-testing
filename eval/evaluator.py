"""OpenEvolve-facing evaluator shim.

OpenEvolve imports this file once per candidate and calls either the plain
`evaluate(program_path)` function, or -- when evaluator.cascade_evaluation is
set in config.yaml -- `evaluate_stage1`, then `evaluate_stage2`, then
`evaluate_stage3`, stopping early if a stage's combined_score misses
evaluator.cascade_thresholds. `program_path` is the mutated EVOLVE-BLOCK
bundle OpenEvolve just produced. All the real work (workspace management,
bundler inject, build, run, scoring) lives in harness.py, which is
project-agnostic; this file's only job is picking which project.yaml to
evaluate against and exposing the stage entry points OpenEvolve looks for.

Which project to evaluate against is selected by the OPENEVOLVE_PROJECT_DIR
environment variable (an absolute path to a directory containing project.yaml),
defaulting to the matmul_cpp reference example so this file works out of the box.
"""
import os
import sys
from pathlib import Path

# OpenEvolve loads this file directly by path (not as a package import), so this
# directory isn't guaranteed to be on sys.path already -- add it explicitly so
# the sibling `harness` module can be found regardless of how/where this runs.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import evaluate_candidate

_DEFAULT_PROJECT_DIR = Path(__file__).resolve().parent.parent / "examples" / "matmul_cpp"
_PROJECT_DIR = Path(os.environ.get("OPENEVOLVE_PROJECT_DIR", _DEFAULT_PROJECT_DIR))

try:
    from openevolve.evaluation_result import EvaluationResult # type: ignore
    _HAVE_EVALUATION_RESULT = True
except ImportError:
    _HAVE_EVALUATION_RESULT = False


def _to_result(outcome):
    result = outcome.as_dict()
    if _HAVE_EVALUATION_RESULT and outcome.stderr_tail:
        # Feed compiler/runtime errors back to the LLM as artifacts so the next
        # generation sees *why* a candidate failed, not just a bare negative score.
        return EvaluationResult(metrics=result, artifacts={"stderr": outcome.stderr_tail}) # type: ignore
    return result


def evaluate(program_path: str):
    """Non-cascade entry point: one build, one run, scored on the primary metric."""
    return _to_result(evaluate_candidate(program_path, _PROJECT_DIR, stage="full"))


def evaluate_stage1(program_path: str):
    """Cheap gate: build + one correctness run. No benchmark yet."""
    return _to_result(evaluate_candidate(program_path, _PROJECT_DIR, stage="stage1"))


def evaluate_stage2(program_path: str):
    """Fuller correctness gate: stage1 plus every project.yaml
    correctness.extra_checks command (sanitizer builds, type checkers, ...)."""
    return _to_result(evaluate_candidate(program_path, _PROJECT_DIR, stage="stage2"))


def evaluate_stage3(program_path: str):
    """The real (possibly expensive) objective -- only reached for candidates
    that already cleared stage1/stage2 via OpenEvolve's cascade thresholds."""
    return _to_result(evaluate_candidate(program_path, _PROJECT_DIR, stage="stage3"))
