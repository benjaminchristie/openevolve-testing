# openevolve-testing

Uses [OpenEvolve](https://github.com/codelion/openevolve) to evolve functions inside C/C++/Python projects. A `bundler` tool extracts `@evolve`-tagged functions from your actual source tree, hands them to OpenEvolve, and splices the mutations back in.

## Setup

```sh
git submodule update --init
ln -s "$(pwd)/bin/evolve" ~/.local/bin/evolve   # once, assuming ~/.local/bin is on PATH
evolve build                                    # once, and again after pulling changes here
```

## Running an example

```sh
export OPENAI_API_KEY=...
cd examples/matmul_cpp
evolve run
```

Results land in `openevolve_output/`. When a run finishes, it writes a reviewable patch to
`openevolve_output/best/best.patch`:

```sh
patch -p1 < openevolve_output/best/best.patch
```

or re-review/apply it later with `evolve patch` / `evolve patch --apply`, or skip review entirely
with `AUTO_APPLY=1 evolve run`.

To restrict a run to one `@evolve(group)` instead of whatever `project.yaml`'s `bundler.group`
says: `evolve run <group>`.

### Using docker compose directly

`evolve` covers the common case; `docker-compose.yml` (repo root) is still there for the visualizer
and for Ollama. Point it at any project with `PROJECT_PATH`:

```sh
UID=$(id -u) GID=$(id -g) docker compose up          # + visualizer at localhost:8080
PROJECT_PATH=path/to/project UID=$(id -u) GID=$(id -g) docker compose up openevolve
```

`ollama` doesn't start by default, it only starts if `api_base` is set to an ollama endpoint. 
If that still doesn't work for some reason, use `COMPOSE_PROFILES=ollama docker compose up`.

## Adding your own project

```sh
mkdir ~/wherever/my_project && cd ~/wherever/my_project
evolve init --language python --objective maximize_accuracy
```

(`evolve init --list-objectives` for the full list.) This writes a source stub and one
`project.yaml`. Open the generated source file, write your algorithm in `solve()`, write a real correctness check in `main()`, then `evolve run`.

### Details

- Tag a function with `/** @evolve */` (C/C++) or `# @evolve` (Python) right above it.
- Your program has to print one line of JSON to stdout: `{"status": "ok", "metrics": {"duration_ms": 12.3}}`.
  Use the `openevolve_metrics` library instead of building that by hand (`Timer`, `report`,
  `guarded` — see `examples/matmul_cpp/src/main.cpp`).
- Keep the correctness check outside the `@evolve` block. If it's inside, the LLM will eventually
  "optimize" by weakening the check instead of the code.
- Lower `checkpoint_interval` along with `max_iterations` in `project.yaml` when doing a quick
  test, or you'll never see a checkpoint (default is 100).
- If you ever hand-edit files in a project after a run, re-run `python3 eval/prepare.py <project>`
  before the next one.

For the full schema (build/run commands, workspace pooling, extra correctness checks), see the
comments in `examples/matmul_cpp/project.yaml`.
