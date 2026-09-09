#!/usr/bin/env python3
"""Scaffolds a new examples/<name>/ project: a tagged source stub,
project.yaml, and config/<name>.yaml.

Usage:
  python3 scripts/new_project.py my_project --language python --objective maximize_accuracy
  python3 scripts/new_project.py my_project --language cpp     # objective defaults to minimize_time
  python3 scripts/new_project.py --list-objectives
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))

import objectives  # noqa: E402

LANGUAGES = {
    "cpp": {"ext": ".cpp", "openevolve_language": "cpp"},
    "c": {"ext": ".c", "openevolve_language": "c"},
    "python": {"ext": ".py", "openevolve_language": "python"},
}


def _extra_metric_line_cpp(preset: objectives.ObjectivePreset) -> str:
    """A metrics.add(...) statement for the objective's metric, or "" if it's
    duration_ms (already added unconditionally)."""
    if preset.metric_name == "duration_ms":
        return ""
    return f'        metrics.add("{preset.metric_name}", 0.0);  // TODO: compute your {preset.metric_name} here\n'


def _extra_metric_line_c(preset: objectives.ObjectivePreset) -> str:
    if preset.metric_name == "duration_ms":
        return ""
    return f'    oe_metrics_add(&metrics, "{preset.metric_name}", 0.0);  /* TODO: compute your {preset.metric_name} here */\n'


def _extra_metric_line_py(preset: objectives.ObjectivePreset) -> str:
    if preset.metric_name == "duration_ms":
        return ""
    return f'    metrics["{preset.metric_name}"] = 0.0  # TODO: compute your {preset.metric_name} here\n'


def render_cpp(name: str, preset: objectives.ObjectivePreset) -> str:
    extra = _extra_metric_line_cpp(preset)
    return f"""#include <openevolve_metrics.hpp>
using namespace openevolve;

/**
@evolve
*/
void solve() {{
    // TODO: your algorithm. Keep the signature stable.
}}

int main() {{
    return guarded([]() {{
        Timer t;
        solve();

        // TODO: a real correctness check -- see README.md on keeping this
        // out of reach of the evolved code.
        bool correct = true;

        Metrics metrics;
        metrics.add("duration_ms", t.elapsed_ms());
{extra}
        report(correct, metrics, correct ? "" : "TODO: describe the failure");
        return correct ? 0 : 1;
    }});
}}
"""


def render_c(name: str, preset: objectives.ObjectivePreset) -> str:
    extra = _extra_metric_line_c(preset)
    return f"""#include <openevolve_metrics.h>

/* @evolve */
void solve(void) {{
    /* TODO: your algorithm. Keep the signature stable. */
}}

int main(void) {{
    oe_timer_t t;
    oe_timer_start(&t);
    solve();

    /* TODO: a real correctness check -- see README.md on keeping this out
       of reach of the evolved code. */
    int correct = 1;

    oe_metrics_t metrics;
    oe_metrics_init(&metrics);
    oe_metrics_add(&metrics, "duration_ms", oe_timer_elapsed_ms(&t));
{extra}
    oe_report(correct, &metrics, correct ? "" : "TODO: describe the failure");
    return correct ? 0 : 1;
}}
"""


def render_python(name: str, preset: objectives.ObjectivePreset) -> str:
    extra = _extra_metric_line_py(preset)
    return f"""from openevolve_metrics import Timer, report, guarded


# @evolve
def solve():
    # TODO: your algorithm. Keep the signature stable.
    pass


def main():
    with Timer() as t:
        solve()

    # TODO: a real correctness check -- see README.md on keeping this out of
    # reach of the evolved code.
    correct = True

    metrics = {{"duration_ms": t.elapsed_ms}}
{extra}
    report(
        status="ok" if correct else "error",
        metrics=metrics,
        message=None if correct else "TODO: describe the failure",
    )


if __name__ == "__main__":
    guarded(main)
"""


RENDERERS = {"cpp": render_cpp, "c": render_c, "python": render_python}


def render_project_yaml(name: str, lang: str, preset: objectives.ObjectivePreset, ext: str) -> str:
    if lang in ("cpp", "c"):
        compiler = "g++ -O2 -std=c++17" if lang == "cpp" else "gcc -O2 -std=c11"
        build_cmd = f'["sh", "-c", "$(command -v ccache) {compiler} src/main{ext} -o {name}_bin"]'
        run_cmd = f'["./{name}_bin"]'
    else:
        build_cmd = f'["python3", "-m", "py_compile", "src/main{ext}"]'
        run_cmd = f'["python3", "src/main{ext}"]'

    return f"""# See examples/matmul_cpp/project.yaml for the full schema
name: {name}
language: {lang}
file_suffix: "{ext}"

bundler:
  src_dir: src
  group: all

build:
  cmd: {build_cmd}
  timeout_sec: 60

run:
  cmd: {run_cmd}
  timeout_sec: 30

workspace:
  mode: ephemeral  # "pool" once builds are slow enough to want incremental reuse

scoring:
  # preset: {preset.name} -- {preset.description}
  primary_metric: {preset.metric_name}
  mode: {preset.mode}
  scale: {preset.scale}
"""


def render_config_yaml(name: str, lang: str, preset: objectives.ObjectivePreset, ext: str) -> str:
    lang_label = {"cpp": "C++", "c": "C", "python": "Python"}[lang]
    return f"""log_level: "INFO"
file_suffix: "{ext}"
language: "{lang}"

# must be top-level, not nested under "evolution:" -- OpenEvolve silently
# ignores unrecognized keys instead of erroring
diff_based_evolution: true
max_iterations: 100
checkpoint_interval: 10  # keep <= max_iterations or the visualizer never sees a checkpoint (default 100)

llm:
  api_base: "https://generativelanguage.googleapis.com/v1beta/openai/"
  primary_model: "gemini-3.1-flash-lite"
  temperature: 0.2
  system_message: |
    You are an expert {lang_label} engineer.
    Optimize the function defined inside the EVOLVE-BLOCK markers to {preset.mode} the
    `{preset.metric_name}` metric this program reports ({preset.description}).
    Do not change the function signature or break program correctness.

database:
  num_islands: 2

evaluator:
  cascade_evaluation: false  # flip on once you add correctness.extra_checks to project.yaml
  parallel_evaluations: 2
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", nargs="?", help="Project name (becomes examples/<name>/ and config/<name>.yaml)")
    parser.add_argument("--language", choices=sorted(LANGUAGES), default="cpp")
    parser.add_argument("--objective", choices=sorted(objectives.PRESETS), default="minimize_time")
    parser.add_argument("--list-objectives", action="store_true", help="Print every objective preset and exit")
    args = parser.parse_args()

    if args.list_objectives:
        for preset in objectives.PRESETS.values():
            print(f"{preset.name:24s} {preset.description}")
        return 0

    if not args.name:
        parser.error("the following arguments are required: name")

    if not args.name.isidentifier():
        raise SystemExit(f"'{args.name}' isn't a valid project name (use letters/digits/underscore, like a Python identifier)")

    preset = objectives.get(args.objective)
    lang = args.language
    ext = LANGUAGES[lang]["ext"]

    project_dir = REPO_ROOT / "examples" / args.name
    config_path = REPO_ROOT / "config" / f"{args.name}.yaml"
    if project_dir.exists() or config_path.exists():
        raise SystemExit(f"{project_dir} or {config_path} already exists -- pick a different name")

    (project_dir / "src").mkdir(parents=True)
    (project_dir / "src" / f"main{ext}").write_text(RENDERERS[lang](args.name, preset))
    (project_dir / "project.yaml").write_text(render_project_yaml(args.name, lang, preset, ext))
    config_path.write_text(render_config_yaml(args.name, lang, preset, ext))

    print(f"Scaffolded examples/{args.name}/ ({lang}, objective: {preset.name}) and config/{args.name}.yaml")
    print(f"Next steps:")
    print(f"  1. Edit examples/{args.name}/src/main{ext} -- fill in solve() and the correctness check.")
    print(f"  2. python3 eval/prepare.py examples/{args.name}")
    print(f"  3. EXAMPLE={args.name} docker compose up openevolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
