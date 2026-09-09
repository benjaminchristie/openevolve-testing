# openevolve-testing

Evolve arbitrary functions in an arbitrary project toward an arbitrary objective, using
[OpenEvolve](https://github.com/codelion/openevolve) (an open implementation of Google
DeepMind's AlphaEvolve) plus a `bundler` tool that extends it to real, multi-file C/C++/Python
projects instead of a single hand-crafted file.

OpenEvolve on its own evolves exactly one file: you wrap the code you want mutated in
`EVOLVE-BLOCK-START`/`EVOLVE-BLOCK-END` markers, point it at that file and an evaluator, and it
repeatedly asks an LLM to edit the marked region and scores the result. `bundler` is what makes
that work against a real project: it scans your actual source tree for `@evolve`-tagged
functions, extracts them into the single flattened file OpenEvolve expects, and splices
OpenEvolve's mutations back into your real files afterward. `eval/harness.py` is the piece that
turns "a mutated bundle" into an actual score: it injects the candidate into an isolated copy of
your project, builds and runs it there, and reports back.

## Quick start

```sh
git submodule update --init          # populates third_party/openevolve
export OPENAI_API_KEY=...            # or whatever your config's llm.api_base expects
UID=$(id -u) GID=$(id -g) docker compose up openevolve
```

That runs the default example (`examples/matmul_cpp`) for `max_iterations` (see
`config/matmul_cpp.yaml`) and writes results to `openevolve_output/matmul_cpp/`. To run a
different example: `EXAMPLE=matmul_py UID=$(id -u) GID=$(id -g) docker compose up openevolve`.

Bring up `docker compose up` (no service name) to also start a visualizer at
`http://localhost:8080` once a checkpoint exists (see the checkpoint_interval gotcha below).

The `UID`/`GID` bit matters: without it the container writes into your bind-mounted repo as
root, which leaves files you can't delete without sudo afterward. See "Known gotchas" if you've
already hit this.

## Creating a new project

```sh
python3 scripts/new_project.py my_project --language python --objective maximize_accuracy
# --list-objectives to see every preset
```

This scaffolds `examples/my_project/` (a tagged source stub + `project.yaml`) and
`config/my_project.yaml`. Fill in the TODOs in the generated source file — your algorithm in the
`@evolve`-tagged function, and a real correctness check in `main()` — then:

```sh
python3 eval/prepare.py examples/my_project     # one-time extraction
EXAMPLE=my_project UID=$(id -u) GID=$(id -g) docker compose up openevolve
```

## Core concepts

**Tagging code.** Put `/** @evolve */` (C/C++) or `# @evolve` (Python) directly above a function
to mark it as evolvable. `@evolve(group_name)` scopes it to a named group; `bundler`'s `--group`
selects which group(s) a given run bundles together — functions bundled together are evolved
*jointly*, as one unit, so keep a group to a small, related set of blocks rather than tagging an
entire codebase at once.

**The correctness contract.** Whatever your `run` command executes must print exactly one line
of JSON to stdout as its last line:
```json
{"status": "ok", "metrics": {"duration_ms": 12.3}}
```
`status` other than `"ok"` is scored as a failure regardless of `metrics`. This is what lets one
generic harness (`eval/harness.py`) score projects in any language without a bespoke parser per
project — see `examples/matmul_cpp/src/main.cpp` for a full worked example.

**Keep the correctness check out of reach of the evolved code.** The check that decides
`status: "ok"` vs `"error"` must live outside the `@evolve`-tagged region (in `main()`, or a
separate driver file bundler never scans). If it's inside the region being mutated, a
sufficiently pressured LLM will eventually "optimize" by weakening the check instead of the
actual algorithm — this is a real, well-known failure mode for LLM-driven code optimization, not
a hypothetical one.

**`project.yaml`** is the declarative spec for one project: where `bundler` looks for
`@evolve` tags, how to build and run it, and how to score it. See
`examples/matmul_cpp/project.yaml` for the fully-annotated schema, including the more advanced
options a starter project doesn't scaffold by default:
- `workspace.mode: pool` — reuse persistent build directories across evaluations instead of a
  fresh copy each time, so incremental builds and a shared `ccache` (`build.cache_env`) actually
  help. Worth it once builds are slow enough for it to matter; `ephemeral` (the default) is
  simpler and fine for small projects.
- `correctness.extra_checks` — arbitrary extra commands that must all exit 0 as part of the
  stage2 cascade gate (a sanitizer build, a type checker, `cargo clippy`, ...).

**Cascade evaluation.** `eval/evaluator.py` exposes `evaluate_stage1/2/3` (cheap correctness →
fuller correctness/`extra_checks` → the real, possibly-expensive objective), which OpenEvolve
runs in order via `evaluator.cascade_evaluation` in `config/<name>.yaml`, stopping early if a
stage's `combined_score` misses `evaluator.cascade_thresholds`. This means a broken candidate
gets rejected cheaply, before the expensive stage ever runs.

**Objective presets** (`eval/objectives.py`) are named shorthands for the `scoring:` block in
`project.yaml` — `minimize_time`, `minimize_loss`, `maximize_accuracy`,
`maximize_success_rate`, `maximize_throughput` — so you don't have to derive the
`primary_metric`/`mode`/`scale` combination yourself for the common cases. `--list-objectives` on
the scaffolding script prints all of them with descriptions.

## Directory structure

```
bundler/            The extraction/injection tool (C++, tree-sitter-based). Supports C, C++,
                     Python; see bundler/src/main.cpp's language_registry() to add another.
eval/                harness.py (the evaluator core), evaluator.py (the OpenEvolve-facing shim),
                     prepare.py (one-time extraction), objectives.py (presets).
examples/<name>/     One project per directory: src/, project.yaml, and (after prepare.py)
                     build/bundle.<ext> + build/map.json.
config/<name>.yaml   OpenEvolve's own run config for that example (LLM, cascade, islands, ...).
scripts/             test_pipeline.py (local regression test), new_project.py (scaffolding).
third_party/openevolve  Our OpenEvolve fork (git submodule) -- edit here only if something
                     genuinely needs a core change; almost everything is reachable from
                     project.yaml/eval/ alone.
```

## Testing locally

```sh
python3 scripts/test_pipeline.py
```

No LLM, no Docker, no API key needed — builds the bundler if needed, round-trips its own
self-hosting extract/inject, then for every `examples/<name>/` runs all three cascade stages
against the baseline, confirms your real project source is never mutated by evaluation, and
confirms a deliberately corrupted candidate fails cleanly instead of crashing. Run this after any
change to `bundler/` or `eval/`, or after scaffolding a new project.

## Known gotchas

- **A config typo fails silently, not loudly.** OpenEvolve's config loader (`dacite`) drops
  unrecognized YAML keys instead of erroring — a field nested one level wrong (e.g. under a
  stray `evolution:` key) just quietly does nothing. Cross-check against
  `third_party/openevolve/openevolve/config.py`'s actual dataclass fields if a setting doesn't
  seem to be taking effect.
- **`checkpoint_interval` (default 100) vs `max_iterations`.** The visualizer waits for an
  `openevolve_output/<name>/checkpoints/` directory that's only written every
  `checkpoint_interval` iterations. If you lower `max_iterations` for a quick test, lower
  `checkpoint_interval` to match (both scaffolded and existing configs already set it to 10) or
  the visualizer will wait forever even though the run itself completes normally.
- **Docker permission trap.** If you ever ran `docker compose up` *before* the `user:` directive
  was added to `docker-compose.yml`, or without `UID`/`GID` set, check for root-owned files under
  `examples/<name>/{build,.ccache,.eval_workspaces}` (`find examples -not -user "$(whoami)"`) --
  clean them up with `sudo rm -rf` once; going forward `UID=$(id -u) GID=$(id -g) docker compose
  up` prevents it from recurring.
- **`ccache` is optional, not required.** Project build commands use it opportunistically
  (`$(command -v ccache) g++ ...`) and fall back to a plain build if it isn't on `PATH`.
