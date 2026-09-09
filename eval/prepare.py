"""Runs `bundler --mode extract` for a project, producing the paired
(initial bundle, map.json) that OpenEvolve starts evolving from and that every
later `evaluate()` call injects candidates back against for the rest of that
run. Run this once per project before starting OpenEvolve; re-run it (which
mints a fresh random block-delimiter token, see bundler/src/main.cpp) only when
the project's @evolve-tagged source has actually changed.

Usage: python3 prepare.py <project_dir>
Prints the path to the initial bundle file OpenEvolve should be pointed at.
"""
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

    result = subprocess.run(
        [str(bundler_bin), "--mode", "extract",
         "--src", spec.bundler_src_dir,
         "--bundle", str(bundle_path),
         "--map", str(map_path),
         "--group", spec.bundler_group],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"bundler extract failed: {result.stderr.strip()}")
    print(result.stdout.strip())
    return bundle_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <project_dir>")
    bundle_path = prepare(Path(sys.argv[1]).resolve())
    print(bundle_path)
