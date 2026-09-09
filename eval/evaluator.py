"""OpenEvolve-facing evaluator shim.

OpenEvolve calls evaluate(program_path), or -- with cascade_evaluation on --
evaluate_stage1/2/3 in order, stopping early if a stage's combined_score
misses cascade_thresholds. The real work lives in harness.py; this file just
picks a project (via OPENEVOLVE_PROJECT_DIR) and exposes the entry points.
"""
import os
import sys
from pathlib import Path

# OpenEvolve loads this file by path, not as a package import, so put the
# sibling `harness` module on sys.path explicitly.
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
        # surfaces the error to the LLM instead of just a bare score
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
