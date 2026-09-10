"""Runs `bundler --mode extract`, producing the (bundle, map.json) pair that
OpenEvolve evolves from and every evaluate() call injects candidates against.
Run once per project before starting OpenEvolve; re-run only if the
@evolve-tagged source changed.

Also snapshots the tagged files as-they-are-right-now into build/pristine/ --
map.json's byte offsets are only valid against that exact content, so
finalize.py restores from this snapshot before injecting rather than trusting
whatever's currently in the project (which might already have a previous
finalize --apply in it).

Set EVOLVE_GROUP to override project.yaml's bundler.group for this call
(e.g. to extract just one @evolve(group) without editing the file).

Usage: python3 prepare.py <project_dir>
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ProjectSpec, _default_bundler_bin


def prepare(project_dir: Path) -> Path:
    spec = ProjectSpec.load(project_dir)
    bundler_bin = _default_bundler_bin()
    if not bundler_bin.exists():
        raise SystemExit(f"bundler binary not found at {bundler_bin} -- build it first")

    map_path = project_dir / spec.map_file
    bundle_path = map_path.parent / f"bundle{spec.file_suffix}"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    group = os.environ.get("EVOLVE_GROUP") or spec.bundler_group

    result = subprocess.run(
        [str(bundler_bin), "--mode", "extract",
         "--src", spec.bundler_src_dir,
         "--bundle", str(bundle_path),
         "--map", str(map_path),
         "--group", group],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"bundler extract failed: {result.stderr.strip()}")
    print(result.stdout.strip())

    pristine_dir = map_path.parent / "pristine"
    if pristine_dir.exists():
        shutil.rmtree(pristine_dir)
    tagged_files = sorted({b["file_path"] for b in json.loads(map_path.read_text())["blocks"]})
    for rel in tagged_files:
        dst = pristine_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_dir / rel, dst)

    return bundle_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <project_dir>")
    bundle_path = prepare(Path(sys.argv[1]).resolve())
    print(bundle_path)
