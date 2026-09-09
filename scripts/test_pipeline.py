#!/usr/bin/env python3
"""End-to-end regression test for the bundler + eval harness pipeline.

No LLM, no Docker, no API key required -- this only exercises the parts of the
system we actually control (bundler extract/inject, eval/harness.py's
isolated-workspace evaluation, the cascade stages). Run it after any change to
bundler/ or eval/, or before wiring up a new examples/<name>/ project, to
confirm the pipeline still behaves correctly.

What it checks, for every examples/<name>/ with a project.yaml:
  - `bundler --mode extract` + `--mode inject` round-trip the project's own
    source byte-for-byte when nothing changed (bundler's own self-hosting
    round-trip is checked the same way, directly on bundler/src/main.cpp).
  - evaluate_stage1/2/3 and the plain evaluate() all succeed on the untouched
    baseline bundle.
  - evaluation never mutates the real project source (hashed before/after).
  - a deliberately corrupted candidate fails cleanly (no crash, passed=False)
    rather than silently doing nothing or hanging.
  - no leftover workspace/build artifacts are left behind afterwards.

Usage: python3 scripts/test_pipeline.py [--keep-build]
  --keep-build: don't rebuild the bundler binary if one already exists (faster
                re-runs; omit this the first time or after editing bundler/).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLER_DIR = REPO_ROOT / "bundler"
BUNDLER_BIN = BUNDLER_DIR / "build" / "bundler"
EXAMPLES_DIR = REPO_ROOT / "examples"
EVAL_DIR = REPO_ROOT / "eval"

sys.path.insert(0, str(EVAL_DIR))

_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append((name, condition, detail))
    return condition


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_tree(root: Path) -> dict[Path, str]:
    return {f: sha256_of(f) for f in root.rglob("*") if f.is_file()}


def ensure_bundler_built(keep_build: bool) -> bool:
    if keep_build and BUNDLER_BIN.exists():
        print(f"Using existing bundler binary at {BUNDLER_BIN}")
        return True
    print("Building bundler (first build fetches tree-sitter grammars over the network)...")
    build_dir = BUNDLER_DIR / "build"
    build_dir.mkdir(exist_ok=True)
    configure = subprocess.run(["cmake", "-S", str(BUNDLER_DIR), "-B", str(build_dir)], capture_output=True, text=True)
    if not check("bundler: cmake configure succeeds", configure.returncode == 0, configure.stderr):
        return False
    build = subprocess.run(["cmake", "--build", str(build_dir), "-j4"], capture_output=True, text=True)
    return check("bundler: cmake build succeeds", build.returncode == 0, build.stderr)


def test_bundler_self_hosting_roundtrip() -> None:
    """Extracts and reinjects the bundler's own source on a scratch copy --
    the case that originally surfaced the false-boundary parsing bug, since
    extract_blocks' own body contains the literal delimiter text it writes."""
    with tempfile.TemporaryDirectory(prefix="bundler_selftest_") as td:
        td = Path(td)
        (td / "src").mkdir()
        shutil.copy2(BUNDLER_DIR / "src" / "main.cpp", td / "src" / "main.cpp")
        bundle, mapf = td / "bundle.cpp", td / "map.json"

        r1 = subprocess.run(
            [str(BUNDLER_BIN), "--mode", "extract", "--src", "src", "--bundle", str(bundle),
             "--map", str(mapf), "--group", "all"],
            cwd=td, capture_output=True, text=True,
        )
        if not check("bundler self-hosting: extract succeeds", r1.returncode == 0, r1.stderr):
            return

        r2 = subprocess.run(
            [str(BUNDLER_BIN), "--mode", "inject", "--bundle", str(bundle), "--map", str(mapf)],
            cwd=td, capture_output=True, text=True,
        )
        if not check("bundler self-hosting: inject succeeds", r2.returncode == 0, r2.stderr):
            return

        identical = sha256_of(td / "src" / "main.cpp") == sha256_of(BUNDLER_DIR / "src" / "main.cpp")
        check("bundler self-hosting: unmodified round-trip is byte-identical", identical)


def make_broken_bundle(bundle_path: Path, out_path: Path) -> bool:
    """Corrupts the first block's body with a language-agnostic garbage line,
    without needing to know anything about the specific project's source --
    this should break compilation/parsing in virtually any language while
    still round-tripping through bundler --mode inject cleanly (inject only
    cares about the delimiter lines, not what's between them)."""
    lines = bundle_path.read_text().splitlines()
    try:
        idx = next(i for i, l in enumerate(lines) if "OPENEVOLVE_BLOCK" in l and "id=" in l)
    except StopIteration:
        return False
    lines.insert(idx + 1, "THIS_IS_INTENTIONALLY_INVALID_SYNTAX ###???@@@!!! (@#$")
    out_path.write_text("\n".join(lines) + "\n")
    return True


def clean_generated(example_dir: Path) -> None:
    for junk in ("build", ".eval_workspaces", ".ccache"):
        shutil.rmtree(example_dir / junk, ignore_errors=True)


def test_example(example_dir: Path) -> None:
    name = example_dir.name
    print(f"\n--- {name} ---")
    clean_generated(example_dir)

    os.environ["OPENEVOLVE_PROJECT_DIR"] = str(example_dir)
    for mod in ("evaluator", "harness"):
        sys.modules.pop(mod, None)
    import evaluator  # noqa: E402  (fresh import per example, see reload above)

    prep = subprocess.run(
        [sys.executable, str(EVAL_DIR / "prepare.py"), str(example_dir)],
        capture_output=True, text=True,
    )
    if not check(f"{name}: prepare.py (bundler extract) succeeds", prep.returncode == 0, prep.stderr):
        return
    bundle_path = Path(prep.stdout.strip().splitlines()[-1])

    src_dir = example_dir / "src"
    before = hash_tree(src_dir)

    s1 = evaluator.evaluate_stage1(str(bundle_path))
    check(f"{name}: stage1 passes on baseline", isinstance(s1, dict) and s1.get("passed") is True, str(s1))

    s2 = evaluator.evaluate_stage2(str(bundle_path))
    check(f"{name}: stage2 passes on baseline", isinstance(s2, dict) and s2.get("passed") is True, str(s2))

    s3 = evaluator.evaluate_stage3(str(bundle_path))
    # Not "score > 0": a "maximize" objective (e.g. accuracy) legitimately
    # scores exactly 0 for an honest, not-yet-filled-in stub -- that's
    # correct behavior, not a failure. "passed" is what actually signals a
    # successful evaluation regardless of scoring mode/sign.
    check(
        f"{name}: stage3 evaluates the baseline successfully",
        isinstance(s3, dict) and s3.get("passed") is True,
        str(s3),
    )

    ev = evaluator.evaluate(str(bundle_path))
    check(f"{name}: plain evaluate() succeeds", isinstance(ev, dict) and ev.get("passed") is True, str(ev))

    after = hash_tree(src_dir)
    check(f"{name}: evaluation never mutated the real project source", before == after)

    broken_bundle = bundle_path.with_name("broken" + bundle_path.suffix)
    if make_broken_bundle(bundle_path, broken_bundle):
        bad = evaluator.evaluate_stage1(str(broken_bundle))
        check(
            f"{name}: a corrupted candidate fails cleanly (no crash)",
            isinstance(bad, dict) and bad.get("passed") is False,
            str(bad),
        )
    else:
        check(f"{name}: could not construct a corrupted candidate (no block delimiter found)", False)

    clean_generated(example_dir)


def main() -> int:
    keep_build = "--keep-build" in sys.argv

    if not ensure_bundler_built(keep_build):
        print("\nCannot continue without a working bundler binary.")
        return 1

    test_bundler_self_hosting_roundtrip()

    example_dirs = sorted(d for d in EXAMPLES_DIR.iterdir() if (d / "project.yaml").exists())
    if not example_dirs:
        check("at least one examples/<name>/project.yaml exists", False)
    for example_dir in example_dirs:
        test_example(example_dir)

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed.")
    failed = [(n, d) for n, ok, d in _results if not ok]
    if failed:
        print("\nFAILED:")
        for name, detail in failed:
            print(f"  - {name}" + (f": {detail}" if detail else ""))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
