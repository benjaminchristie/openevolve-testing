#!/usr/bin/env python3
"""Scaffolds a new examples/<name>/ project: a tagged source stub, a
project.yaml, and a matching config/<name>.yaml -- so starting a new project
means filling in a working skeleton instead of writing the whole schema from
scratch by copying examples/matmul_cpp and hand-editing it.

Usage:
  python3 scripts/new_project.py my_project --language python --objective maximize_accuracy
  python3 scripts/new_project.py my_project --language cpp     # objective defaults to minimize_time

Run `python3 scripts/new_project.py --list-objectives` to see every preset.

After scaffolding, see the TODO comments in the generated source file (your
algorithm + how to compute the objective metric) and project.yaml (the
bundler group, build/run commands if the defaults don't fit).
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


def _extra_metric_cpp(preset: objectives.ObjectivePreset) -> tuple[str, str]:
    """Returns (decl_line, cout_fragment). Empty strings if the objective's
    metric already *is* duration_ms, which main() computes unconditionally.

    The TODO comment deliberately lives on its own declaration line rather
    than inline in the cout chain -- an earlier version tried to embed it
    directly in the JSON-building expression and it broke the enclosing
    string literal (unescaped quotes) in exactly the way this now avoids."""
    if preset.metric_name == "duration_ms":
        return "", ""
    var = f"{preset.metric_name}_value"
    decl = f"    double {var} = 0.0;  // TODO: compute your {preset.metric_name} here\n"
    frag = f' << ", \\"{preset.metric_name}\\": " << {var}'
    return decl, frag


def _extra_metric_c(preset: objectives.ObjectivePreset) -> tuple[str, str, str]:
    """Returns (decl_line, printf_format_fragment, printf_arg_fragment)."""
    if preset.metric_name == "duration_ms":
        return "", "", ""
    var = f"{preset.metric_name}_value"
    decl = f"    double {var} = 0.0;  /* TODO: compute your {preset.metric_name} here */\n"
    fmt = f', \\"{preset.metric_name}\\": %f'
    arg = f", {var}"
    return decl, fmt, arg


def _extra_metric_py(preset: objectives.ObjectivePreset) -> tuple[str, str]:
    """Returns (decl_line, dict_fragment). See _extra_metric_cpp docstring --
    same fix applies here even more sharply, since a Python "#" comment
    embedded inside a single-line dict literal eats the rest of the line,
    including the closing "}" that was supposed to end the literal."""
    if preset.metric_name == "duration_ms":
        return "", ""
    var = f"{preset.metric_name}_value"
    decl = f"    {var} = 0.0  # TODO: compute your {preset.metric_name} here\n"
    frag = f', "{preset.metric_name}": {var}'
    return decl, frag


def render_cpp(name: str, preset: objectives.ObjectivePreset) -> str:
    decl, frag = _extra_metric_cpp(preset)
    return f"""#include <chrono>
#include <iostream>

/**
@evolve
*/
void solve() {{
    // TODO: replace this with the code you want OpenEvolve to optimize.
    // Keep the function signature stable -- OpenEvolve edits the body, not
    // how it's called from main() below.
}}

int main() {{
    auto start = std::chrono::high_resolution_clock::now();
    solve();
    auto end = std::chrono::high_resolution_clock::now();
    double duration_ms = std::chrono::duration<double, std::milli>(end - start).count();
{decl}
    // TODO: replace with a real correctness check (e.g. compare a computed
    // result against a known-good expected value). A candidate that "passes"
    // here but isn't actually correct will happily get evolved for speed at
    // correctness's expense -- see README.md's note on keeping the check
    // trustworthy.
    bool correct = true;

    std::cout << "{{\\"status\\": \\"" << (correct ? "ok" : "error")
              << "\\", \\"metrics\\": {{\\"duration_ms\\": " << duration_ms{frag}
              << "}}"
              << (correct ? "" : ", \\"message\\": \\"TODO: describe the failure\\"")
              << "}}" << std::endl;
    return correct ? 0 : 1;
}}
"""


def render_c(name: str, preset: objectives.ObjectivePreset) -> str:
    decl, fmt, arg = _extra_metric_c(preset)
    return f"""#include <stdio.h>
#include <time.h>

/* @evolve */
void solve(void) {{
    /* TODO: replace this with the code you want OpenEvolve to optimize.
       Keep the function signature stable -- OpenEvolve edits the body, not
       how it's called from main() below. */
}}

int main(void) {{
    /* timespec_get is standard C11 (unlike clock_gettime/CLOCK_MONOTONIC,
       which are POSIX extensions hidden under strict -std=c11 without a
       feature-test macro). */
    struct timespec start, end;
    timespec_get(&start, TIME_UTC);
    solve();
    timespec_get(&end, TIME_UTC);
    double duration_ms = (end.tv_sec - start.tv_sec) * 1000.0
                        + (end.tv_nsec - start.tv_nsec) / 1e6;
{decl}
    /* TODO: replace with a real correctness check. A candidate that "passes"
       here but isn't actually correct will happily get evolved for speed at
       correctness's expense -- see README.md's note on keeping the check
       trustworthy. */
    int correct = 1;

    printf("{{\\"status\\": \\"%s\\", \\"metrics\\": {{\\"duration_ms\\": %f{fmt}}}%s}}\\n",
           correct ? "ok" : "error", duration_ms{arg},
           correct ? "" : ", \\"message\\": \\"TODO: describe the failure\\"");
    return correct ? 0 : 1;
}}
"""


def render_python(name: str, preset: objectives.ObjectivePreset) -> str:
    decl, frag = _extra_metric_py(preset)
    return f"""import json
import time


# @evolve
def solve():
    # TODO: replace this with the code you want OpenEvolve to optimize. Keep
    # the function signature stable -- OpenEvolve edits the body, not how
    # it's called from main() below.
    pass


def main():
    start = time.perf_counter()
    solve()
    duration_ms = (time.perf_counter() - start) * 1000
{decl}
    # TODO: replace with a real correctness check (e.g. compare a computed
    # result against a known-good expected value). A candidate that "passes"
    # here but isn't actually correct will happily get evolved for speed at
    # correctness's expense -- see README.md's note on keeping the check
    # trustworthy.
    correct = True

    result = {{"status": "ok" if correct else "error", "metrics": {{"duration_ms": duration_ms{frag}}}}}
    if not correct:
        result["message"] = "TODO: describe the failure"
    print(json.dumps(result))


if __name__ == "__main__":
    main()
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

    return f"""# Scaffolded by scripts/new_project.py. See examples/matmul_cpp/project.yaml
# for the full schema (workspace pooling, ccache, correctness.extra_checks) --
# this starter only sets what's needed to get a first run working.
name: {name}
language: {lang}
file_suffix: "{ext}"

bundler:
  src_dir: src
  # "all" pulls in every @evolve(<group>) tag plus untagged ("universal")
  # blocks. Narrow this once you're tagging more than one logical group.
  group: all

build:
  cmd: {build_cmd}
  timeout_sec: 60

run:
  cmd: {run_cmd}
  timeout_sec: 30

workspace:
  mode: ephemeral  # switch to "pool" once builds are slow enough to want incremental reuse -- see examples/matmul_cpp/project.yaml

scoring:
  # Objective preset: {preset.name} -- {preset.description}
  primary_metric: {preset.metric_name}
  mode: {preset.mode}
  scale: {preset.scale}
"""


def render_config_yaml(name: str, lang: str, preset: objectives.ObjectivePreset, ext: str) -> str:
    lang_label = {"cpp": "C++", "c": "C", "python": "Python"}[lang]
    return f"""log_level: "INFO"
file_suffix: "{ext}"
language: "{lang}"

# NOTE: diff_based_evolution and max_iterations must be top-level fields, not
# nested under an "evolution:" key -- OpenEvolve's config loader (dacite)
# silently drops unrecognized keys instead of erroring, so a stray "evolution:"
# section here would appear to work while quietly having no effect at all.
diff_based_evolution: true
max_iterations: 100
# Keep <= max_iterations, or the visualizer waits forever for a
# checkpoints/ directory that's never written (default is 100).
checkpoint_interval: 10

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
  cascade_evaluation: false  # flip to true once you add correctness.extra_checks to project.yaml (see examples/matmul_cpp)
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
