"""Generic, project-agnostic evaluation harness for OpenEvolve + the bundler tool.

Language-agnostic by design: every piece of project-specific knowledge (how to
build, how to run, what "correct" means, which grammar the bundler should use)
comes from that project's project.yaml. Nothing in this file assumes C++, or
any other single language -- see examples/matmul_cpp/project.yaml for a worked
C++ example; a Python or Rust project needs a different project.yaml, not a
different harness.

"Evaluate one candidate" is:
    1. get a workspace holding a pristine copy of the project (ephemeral or a
       reused pool slot -- see below), never touching the real project tree,
    2. splice the candidate bundle back into it with `bundler --mode inject`,
       using the *original* map.json produced when extraction happened,
    3. run the project's own build/run commands inside that workspace,
    4. parse a single JSON status line the run command prints to stdout,
    5. turn it into an OpenEvolve-compatible metrics dict.

Two workspace strategies (project.yaml: workspace.mode):
  - "ephemeral" (default): fresh tempdir per evaluation, deleted afterwards.
    Simplest and safest; fine for small/fast-building projects.
  - "pool": a fixed number of persistent slot directories, reused across
    evaluations instead of recreated. Each slot keeps its own build/ directory
    intact between evaluations so incremental builds (Ninja/Make/Cargo dep
    tracking) actually apply, not just from-scratch builds every time. Only
    the specific source files the bundler ever touches (from map.json) are
    reset to pristine before each inject -- see _restore_pristine. Slots are
    guarded by cross-process file locks because OpenEvolve evaluates in
    parallel via a real ProcessPoolExecutor (separate OS processes), not
    threads, so an in-memory lock would not coordinate between them.

Independently of workspace strategy, project.yaml's build.cache_env can wire
in a compiler object cache (ccache/sccache): set CCACHE_DIR to a location
that's shared across every workspace (never inside one that gets deleted).
This is what actually saves time across cascade stages (see below), since
stage1/stage2/stage3 are separate calls into this module with no workspace of
their own in common -- ccache is keyed by preprocessed-source content, not by
directory, so a rebuild of unchanged code across stages or across pool slots
is a cache hit regardless. The harness sets CCACHE_BASEDIR to the current
workspace automatically, since ccache's cache key can otherwise be sensitive
to the (per-workspace, non-reproducible) absolute path.

Cascade evaluation (OpenEvolve's evaluator.cascade_evaluation): the exported
evaluate_stage1/2/3 functions call evaluate_candidate(..., stage=...) so a
cheap correctness check runs before an expensive benchmark ever does. See
eval/evaluator.py.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import yaml

FAILURE_SCORE = -1000.0
TIMEOUT_SCORE = -500.0


@dataclass
class ExtraCheck:
    name: str
    cmd: List[str]
    timeout_sec: float


@dataclass
class ProjectSpec:
    project_dir: Path
    name: str
    language: str
    file_suffix: str
    bundler_src_dir: str
    bundler_group: str
    map_file: str
    build_cmd: List[str]
    build_timeout: float
    build_env: Dict[str, str]
    run_cmd: List[str]
    run_timeout: float
    benchmark_cmd: List[str]
    benchmark_timeout: float
    extra_checks: List[ExtraCheck]
    primary_metric: str
    mode: str
    scale: float
    workspace_mode: str
    workspace_pool_size: int
    workspace_root: Path

    @classmethod
    def load(cls, project_dir: Path) -> "ProjectSpec":
        spec_path = project_dir / "project.yaml"
        with open(spec_path) as f:
            data = yaml.safe_load(f)
        bundler_cfg = data.get("bundler", {})
        scoring_cfg = data.get("scoring", {})
        build_cfg = data.get("build", {})
        run_cfg = data["run"]
        benchmark_cfg = data.get("benchmark", run_cfg)
        correctness_cfg = data.get("correctness", {})
        workspace_cfg = data.get("workspace", {})

        build_env = dict(build_cfg.get("cache_env", {}))
        # Relative CCACHE_DIR is resolved against the project (stable, never
        # copied into a workspace) so a shared cache works out of the box
        # without a hardcoded absolute path in a checked-in project.yaml.
        if "CCACHE_DIR" in build_env and not os.path.isabs(build_env["CCACHE_DIR"]):
            cache_dir = (project_dir / build_env["CCACHE_DIR"]).resolve()
            cache_dir.mkdir(parents=True, exist_ok=True)
            build_env["CCACHE_DIR"] = str(cache_dir)

        extra_checks = [
            ExtraCheck(name=c["name"], cmd=c["cmd"], timeout_sec=float(c.get("timeout_sec", 60)))
            for c in correctness_cfg.get("extra_checks", [])
        ]

        workspace_root = project_dir / workspace_cfg.get("root", ".eval_workspaces")

        return cls(
            project_dir=project_dir,
            name=data["name"],
            language=data["language"],
            # Separate from `language` on purpose (mirrors OpenEvolve's own
            # config.yaml, which has both a `language` and a `file_suffix`
            # top-level field): "python" as a language name doesn't imply
            # ".python" as a file extension.
            file_suffix=data.get("file_suffix", "." + data["language"]),
            bundler_src_dir=bundler_cfg["src_dir"],
            bundler_group=bundler_cfg.get("group", "all"),
            map_file=bundler_cfg.get("map_file", "build/map.json"),
            build_cmd=build_cfg.get("cmd", []),
            build_timeout=float(build_cfg.get("timeout_sec", 60)),
            build_env=build_env,
            run_cmd=run_cfg["cmd"],
            run_timeout=float(run_cfg.get("timeout_sec", 15)),
            benchmark_cmd=benchmark_cfg["cmd"],
            benchmark_timeout=float(benchmark_cfg.get("timeout_sec", run_cfg.get("timeout_sec", 15))),
            extra_checks=extra_checks,
            primary_metric=scoring_cfg["primary_metric"],
            mode=scoring_cfg.get("mode", "minimize"),
            scale=float(scoring_cfg.get("scale", 1.0)),
            workspace_mode=workspace_cfg.get("mode", "ephemeral"),
            workspace_pool_size=int(workspace_cfg.get("pool_size", 4)),
            workspace_root=workspace_root,
        )


@dataclass
class EvalOutcome:
    combined_score: float
    passed: bool
    metrics: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    stderr_tail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        # Both keys are populated: "combined_score" is what OpenEvolve's cascade
        # threshold check (_passes_threshold) looks for; "score" is kept for the
        # simple non-cascade `evaluator=lambda path: {"score": ...}` convention.
        result: Dict[str, Any] = {
            "combined_score": self.combined_score,
            "score": self.combined_score,
            "passed": self.passed,
            **self.metrics,
        }
        if self.error:
            result["error"] = self.error
        return result


def _default_bundler_bin() -> Path:
    # Our Docker image builds the bundler once at image-build time into a path
    # outside the repo bind mount (see Dockerfile) -- the bind mount would
    # otherwise shadow anything COPY'd to the repo-relative path below, so the
    # image sets this env var rather than relying on the fallback.
    override = os.environ.get("BUNDLER_BIN")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "bundler" / "build" / "bundler"


def _tail(text: str, n_chars: int = 4000) -> str:
    return text[-n_chars:] if len(text) > n_chars else text


def _score_from_metrics(spec: ProjectSpec, metrics: Dict[str, float]) -> float:
    if spec.primary_metric not in metrics:
        raise ValueError(f"program did not report required metric '{spec.primary_metric}'")
    value = float(metrics[spec.primary_metric])
    if spec.mode == "minimize":
        return spec.scale / (value + 1e-6)
    elif spec.mode == "maximize":
        return value
    raise ValueError(f"unknown scoring mode '{spec.mode}' (expected 'minimize' or 'maximize')")


def _load_tagged_files(map_path: Path) -> List[str]:
    with open(map_path) as f:
        data = json.load(f)
    return sorted({block["file_path"] for block in data["blocks"]})


@contextlib.contextmanager
def _acquire_slot(pool_root: Path, pool_size: int) -> Iterator[int]:
    pool_root.mkdir(parents=True, exist_ok=True)
    fd = None
    chosen = None
    for i in range(pool_size):
        candidate_fd = os.open(str(pool_root / f"slot_{i}.lock"), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(candidate_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            chosen, fd = i, candidate_fd
            break
        except BlockingIOError:
            os.close(candidate_fd)
    if fd is None:
        # Every slot is busy right now: block on slot 0 rather than erroring
        # out, so a burst of concurrent evaluations still makes progress
        # (just serialized past the configured pool size).
        chosen = 0
        fd = os.open(str(pool_root / "slot_0.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield chosen # type: ignore
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _ensure_slot_initialized(slot_dir: Path, spec: ProjectSpec, map_path: Path, tagged_files: List[str]) -> None:
    if slot_dir.exists():
        return
    shutil.copytree(
        spec.project_dir, slot_dir,
        ignore=shutil.ignore_patterns("build", spec.workspace_root.name, "__pycache__"),
    )
    pristine_dir = slot_dir / ".pristine"
    for rel in tagged_files:
        dst = pristine_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(slot_dir / rel, dst)
    (slot_dir / spec.map_file).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(map_path, slot_dir / spec.map_file)


def _restore_pristine(slot_dir: Path, tagged_files: List[str]) -> None:
    for rel in tagged_files:
        shutil.copy2(slot_dir / ".pristine" / rel, slot_dir / rel)


@contextlib.contextmanager
def _workspace(spec: ProjectSpec, map_path: Path) -> Iterator[Path]:
    if spec.workspace_mode == "pool":
        tagged_files = _load_tagged_files(map_path)
        with _acquire_slot(spec.workspace_root, spec.workspace_pool_size) as slot_idx:
            slot_dir = spec.workspace_root / f"slot_{slot_idx}"
            _ensure_slot_initialized(slot_dir, spec, map_path, tagged_files)
            _restore_pristine(slot_dir, tagged_files)
            yield slot_dir
            # slot_dir (including its build/ dir) is deliberately left in
            # place for the next evaluation to reuse -- that reuse is the
            # entire point of pool mode.
    elif spec.workspace_mode == "ephemeral":
        workspace = Path(tempfile.mkdtemp(prefix=f"openevolve_eval_{spec.name}_"))
        try:
            shutil.copytree(
                spec.project_dir, workspace, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("build"),
            )
            (workspace / spec.map_file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(map_path, workspace / spec.map_file)
            yield workspace
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    else:
        raise ValueError(f"unknown workspace.mode '{spec.workspace_mode}' (expected 'ephemeral' or 'pool')")


def _build_env_for(spec: ProjectSpec, workspace: Path) -> Dict[str, str]:
    env = {**os.environ, **spec.build_env}
    if "CCACHE_DIR" in spec.build_env:
        env.setdefault("CCACHE_BASEDIR", str(workspace))
    return env


def _run_json_command(cmd: List[str], workspace: Path, env: Dict[str, str], timeout: float) -> "_CmdResult":
    try:
        res = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _CmdResult(ok=False, timed_out=True, status=None, metrics={}, error="run timed out", stderr_tail=None)

    stdout_lines = [ln for ln in res.stdout.strip().splitlines() if ln.strip()]
    if not stdout_lines:
        return _CmdResult(
            ok=False, timed_out=False, status=None, metrics={},
            error="run produced no stdout output", stderr_tail=_tail(res.stderr),
        )
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError as e:
        return _CmdResult(
            ok=False, timed_out=False, status=None, metrics={},
            error=f"last stdout line was not valid JSON: {e}",
            stderr_tail=_tail(res.stdout + res.stderr),
        )

    status = payload.get("status")
    metrics = {k: float(v) for k, v in payload.get("metrics", {}).items()}
    if status != "ok":
        return _CmdResult(
            ok=False, timed_out=False, status=status, metrics=metrics,
            error=payload.get("message", f"program reported status={status!r}"), stderr_tail=None,
        )
    return _CmdResult(ok=True, timed_out=False, status=status, metrics=metrics, error=None, stderr_tail=None)


@dataclass
class _CmdResult:
    ok: bool
    timed_out: bool
    status: Optional[str]
    metrics: Dict[str, float]
    error: Optional[str]
    stderr_tail: Optional[str]


def evaluate_candidate(
    bundle_path: str,
    project_dir: Path,
    bundler_bin: Optional[Path] = None,
    stage: str = "full",
) -> EvalOutcome:
    """Evaluate one OpenEvolve candidate bundle against the project described by
    project_dir's project.yaml. Never mutates project_dir.

    stage:
      "full"   -- build once, run once, score on the primary metric (what a
                  plain, non-cascade evaluate() call wants).
      "stage1" -- build + one correctness run only. combined_score is 1.0/0.0.
                  Cheap: meant to reject broken candidates before anything
                  expensive runs.
      "stage2" -- stage1, plus every project.yaml correctness.extra_checks
                  command (e.g. a sanitizer build+run, a type checker).
                  combined_score is the fraction of checks that passed.
      "stage3" -- build + the (possibly separate) benchmark command, scored
                  on the primary metric. Only reached for candidates that
                  already cleared stage1/stage2, via OpenEvolve's cascade.
    """
    spec = ProjectSpec.load(project_dir)
    bundler_bin = bundler_bin or _default_bundler_bin()
    if not bundler_bin.exists():
        return EvalOutcome(FAILURE_SCORE, False, error=f"bundler binary not found at {bundler_bin}")

    map_path = project_dir / spec.map_file
    if not map_path.exists():
        return EvalOutcome(
            FAILURE_SCORE, False,
            error=f"map file {map_path} not found -- run the project's prepare step first",
        )

    with _workspace(spec, map_path) as workspace:
        inject_res = subprocess.run(
            [str(bundler_bin), "--mode", "inject", "--bundle", str(Path(bundle_path).resolve()),
             "--map", str(workspace / spec.map_file)],
            cwd=workspace, capture_output=True, text=True, timeout=30,
        )
        if inject_res.returncode != 0:
            return EvalOutcome(FAILURE_SCORE, False, error=f"bundler inject failed: {inject_res.stderr.strip()}")

        env = _build_env_for(spec, workspace)
        if spec.build_cmd:
            try:
                build_res = subprocess.run(
                    spec.build_cmd, cwd=workspace, env=env, capture_output=True, text=True,
                    timeout=spec.build_timeout,
                )
            except subprocess.TimeoutExpired:
                return EvalOutcome(TIMEOUT_SCORE, False, error="build timed out")
            if build_res.returncode != 0:
                return EvalOutcome(
                    FAILURE_SCORE, False,
                    error=f"build failed: {_tail(build_res.stderr)}",
                    stderr_tail=_tail(build_res.stderr),
                )

        if stage in ("stage1", "stage2"):
            base = _run_json_command(spec.run_cmd, workspace, env, spec.run_timeout)
            if base.timed_out:
                return EvalOutcome(TIMEOUT_SCORE, False, error=base.error)
            if not base.ok:
                return EvalOutcome(0.0, False, metrics=base.metrics, error=base.error, stderr_tail=base.stderr_tail)
            if stage == "stage1":
                return EvalOutcome(1.0, True, metrics={**base.metrics, "stage1_passed": 1.0})

            total = 1 + len(spec.extra_checks)
            passed = 1
            failures: List[str] = []
            for check in spec.extra_checks:
                try:
                    check_res = subprocess.run(
                        check.cmd, cwd=workspace, env=env, capture_output=True, text=True,
                        timeout=check.timeout_sec,
                    )
                except subprocess.TimeoutExpired:
                    failures.append(f"{check.name}: timed out")
                    continue
                if check_res.returncode == 0:
                    passed += 1
                else:
                    failures.append(f"{check.name}: {_tail(check_res.stderr or check_res.stdout)}")
            combined = passed / total
            return EvalOutcome(
                combined, combined == 1.0,
                metrics={**base.metrics, "stage2_checks_passed": float(passed), "stage2_checks_total": float(total)},
                error="; ".join(failures) if failures else None,
            )

        # stage == "stage3" or "full": the real (possibly expensive) objective.
        bench = _run_json_command(spec.benchmark_cmd, workspace, env, spec.benchmark_timeout)
        if bench.timed_out:
            return EvalOutcome(TIMEOUT_SCORE, False, error=bench.error)
        if not bench.ok:
            return EvalOutcome(FAILURE_SCORE, False, metrics=bench.metrics, error=bench.error, stderr_tail=bench.stderr_tail)
        try:
            score = _score_from_metrics(spec, bench.metrics)
        except ValueError as e:
            return EvalOutcome(FAILURE_SCORE, False, metrics=bench.metrics, error=str(e))
        return EvalOutcome(score, True, metrics=bench.metrics)
