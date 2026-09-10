#!/usr/bin/env python3
"""Delivers an OpenEvolve run's winning result back into the real project --
either as a reviewable unified diff (default), or applied directly.

Reads <project_dir>/openevolve_output/best/best_program<ext> (OpenEvolve's own
output, see third_party/openevolve/openevolve/controller.py's
_save_best_program) and injects it with the same bundler --mode inject used
throughout the run.

Usage: python3 finalize.py <project_dir> [--apply]
"""
from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ProjectSpec, _default_bundler_bin, _load_tagged_files


def _format_metrics(metrics: dict) -> str:
    parts = []
    for k, v in metrics.items():
        parts.append(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}")
    return ", ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="write changes directly instead of producing a patch")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    spec = ProjectSpec.load(project_dir)

    best_dir = project_dir / "openevolve_output" / "best"
    best_code = best_dir / f"best_program{spec.file_suffix}"
    info_path = best_dir / "best_program_info.json"
    map_path = project_dir / spec.map_file

    if not best_code.exists():
        raise SystemExit(f"no best result at {best_code} -- did the run finish?")
    if not map_path.exists():
        raise SystemExit(f"map file {map_path} not found")

    if info_path.exists():
        info = json.loads(info_path.read_text())
        print(f"Best result (iteration {info.get('iteration', '?')}): {_format_metrics(info.get('metrics', {}))}")

    bundler_bin = _default_bundler_bin()
    tagged_files = _load_tagged_files(map_path)

    # map.json's byte offsets are only valid against the file content that existed
    # at extraction time -- inject against whatever's currently in project_dir
    # would corrupt the result the moment it's not pristine anymore (e.g. a
    # previous finalize --apply already changed a file's length). prepare.py
    # snapshots that exact content here for exactly this reason.
    pristine_dir = map_path.parent / "pristine"
    if not pristine_dir.exists():
        raise SystemExit(f"{pristine_dir} not found -- re-run eval/prepare.py for this project first")

    workspace = Path(tempfile.mkdtemp(prefix="openevolve_finalize_"))
    try:
        shutil.copytree(
            project_dir, workspace, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("build", "openevolve_output", ".eval_workspaces", ".ccache", "__pycache__"),
        )
        (workspace / spec.map_file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(map_path, workspace / spec.map_file)
        for rel in tagged_files:
            src = pristine_dir / rel
            if not src.exists():
                raise SystemExit(f"pristine snapshot missing {rel} -- re-run eval/prepare.py")
            shutil.copy2(src, workspace / rel)

        inject_res = subprocess.run(
            [str(bundler_bin), "--mode", "inject", "--bundle", str(best_code.resolve()),
             "--map", str(workspace / spec.map_file)],
            cwd=workspace, capture_output=True, text=True,
        )
        if inject_res.returncode != 0:
            raise SystemExit(f"bundler inject failed: {inject_res.stderr.strip()}")

        changed = [rel for rel in tagged_files if (project_dir / rel).read_bytes() != (workspace / rel).read_bytes()]

        if args.apply:
            if not changed:
                print("No changes -- the best candidate matches the current source already.")
                return 0
            for rel in changed:
                shutil.copy2(workspace / rel, project_dir / rel)
            print(f"Applied changes directly to {len(changed)} file(s): {', '.join(changed)}")
            return 0

        patch_lines = []
        for rel in changed:
            old = (project_dir / rel).read_text().splitlines(keepends=True)
            new = (workspace / rel).read_text().splitlines(keepends=True)
            patch_lines += list(difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}"))

        if not patch_lines:
            print("No changes -- the best candidate matches the current source already.")
            return 0

        patch_path = best_dir / "best.patch"
        patch_path.write_text("".join(patch_lines))
        print(f"Wrote {patch_path}")
        print(f"Review it, then apply with: patch -p1 -d {project_dir} < {patch_path}")
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
