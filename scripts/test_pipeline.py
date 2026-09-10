#!/usr/bin/env python3
"""End-to-end regression test for the bundler + eval harness pipeline.
No LLM, no Docker, no API key required. Run after changing bundler/ or eval/,
or after scaffolding a new examples/<name>/ project.

For every examples/<name>/: round-trips extract/inject (and bundler's own
self-hosting round-trip on bundler/src/main.cpp), runs all cascade stages on
the baseline, confirms evaluation never mutates the real source, and confirms
a corrupted candidate fails cleanly instead of crashing or hanging.

Usage: python3 scripts/test_pipeline.py [--keep-build]
  --keep-build: skip rebuilding the bundler binary if one already exists.
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
    """Extracts and reinjects the bundler's own source on a scratch copy."""
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
    """Inserts a garbage line into the first block's body -- breaks
    compilation in any language without needing to know the source."""
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


def test_finalize(name: str, example_dir: Path, bundle_path: Path) -> None:
    """Generic (language-agnostic) finalize.py check: feeding it the
    unmodified bundle as "the best result" must report no changes, in both
    patch and --apply mode, on a scratch copy so the real example is
    untouched. This is the identity case; the interesting "a real change
    round-trips as a working patch" case was verified by hand on numerics_cpp
    rather than automated here, since it needs a per-language mutation."""
    with tempfile.TemporaryDirectory(prefix=f"finalize_test_{name}_") as td:
        scratch = Path(td) / "proj"
        shutil.copytree(example_dir, scratch)
        best_dir = scratch / "openevolve_output" / "best"
        # exist_ok: the scratch copy may already have a real openevolve_output/
        # from an actual run against this example -- fine to overwrite in the
        # disposable copy, just don't let that collide with a bare mkdir
        best_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle_path, best_dir / f"best_program{bundle_path.suffix}")
        (best_dir / "best_program_info.json").write_text('{"iteration": 0, "metrics": {}}')

        for mode_args, label in ([], "patch"), (["--apply"], "--apply"):
            res = subprocess.run(
                [sys.executable, str(EVAL_DIR / "finalize.py"), str(scratch), *mode_args],
                capture_output=True, text=True,
            )
            check(
                f"{name}: finalize.py {label} reports no changes for an unmodified best result",
                res.returncode == 0 and "no changes" in res.stdout.lower(),
                res.stdout + res.stderr,
            )


def test_example(example_dir: Path) -> None:
    name = example_dir.name
    print(f"\n--- {name} ---")
    clean_generated(example_dir)

    os.environ["OPENEVOLVE_PROJECT_DIR"] = str(example_dir)
    for mod in ("evaluator", "harness"):
        sys.modules.pop(mod, None)
    import evaluator  # noqa: E402 -- fresh import per example

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
    # not "score > 0": an unfilled "maximize" stub (e.g. accuracy) legitimately scores 0
    check(
        f"{name}: stage3 evaluates the baseline successfully",
        isinstance(s3, dict) and s3.get("passed") is True,
        str(s3),
    )

    ev = evaluator.evaluate(str(bundle_path))
    check(f"{name}: plain evaluate() succeeds", isinstance(ev, dict) and ev.get("passed") is True, str(ev))

    after = hash_tree(src_dir)
    check(f"{name}: evaluation never mutated the real project source", before == after)

    test_finalize(name, example_dir, bundle_path)

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
