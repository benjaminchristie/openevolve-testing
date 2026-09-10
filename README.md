# openevolve-testing

Uses [OpenEvolve](https://github.com/codelion/openevolve) to evolve functions inside C/C++/Python projects. A `bundler` tool extracts `@evolve`-tagged functions from your actual source tree, hands them to OpenEvolve, and splices the mutations back in.

## Running an example

```sh
git submodule update --init
export OPENAI_API_KEY=...
UID=$(id -u) GID=$(id -g) docker compose up
```

Runs `examples/matmul_cpp` by default. Point it at any other project with `PROJECT_PATH=path/to/project`.
Results land in `<project>/openevolve_output/`; the visualizer comes up on `localhost:8080` once a
checkpoint exists.

Set `UID`/`GID` like that or Docker writes into the project as root and you'll need `sudo` to clean
up after.

When a run finishes, it writes a reviewable patch to `openevolve_output/best/best.patch`:

```sh
patch -p1 -d path/to/project < path/to/project/openevolve_output/best/best.patch
```

Or skip the review and apply the winner automatically: `AUTO_APPLY=1 docker compose up openevolve`.

### Using a local Ollama model

`ollama` doesn't start by default -- there's no reason to if `project.yaml`'s `llm.api_base`
points at a remote provider like every current example does. Only bring it up if you actually
set `api_base` to Ollama's endpoint:

```sh
COMPOSE_PROFILES=ollama docker compose up
```

## Adding your own project

```sh
python3 scripts/new_project.py ~/wherever/my_project --language python --objective maximize_accuracy
```

(`--list-objectives` for the full list.) This writes a source stub and one `project.yaml` holding
both the OpenEvolve run config and the build/run spec -- any directory works, not just something
under `examples/`. Open the generated source file, write your algorithm in `solve()`, write a real
correctness check in `main()`, then:

```sh
PROJECT_PATH=~/wherever/my_project UID=$(id -u) GID=$(id -g) docker compose up openevolve
```

## Things worth knowing

- Tag a function with `/** @evolve */` (C/C++) or `# @evolve` (Python) right above it.
- Your program has to print one line of JSON to stdout: `{"status": "ok", "metrics": {"duration_ms": 12.3}}`.
  Use the `openevolve_metrics` library instead of building that by hand (`Timer`, `report`,
  `guarded` — see `examples/matmul_cpp/src/main.cpp`).
- Keep the correctness check outside the `@evolve` block. If it's inside, the LLM will eventually
  "optimize" by weakening the check instead of the code.
- Lower `checkpoint_interval` along with `max_iterations` in `project.yaml` when doing a quick
  test, or the visualizer never sees a checkpoint (default is 100).
- `python3 scripts/test_pipeline.py` runs the whole pipeline locally, no Docker or API key
  needed. Run it after touching `bundler/` or `eval/`.
- If you ever hand-edit files in a project after a run, re-run `python3 eval/prepare.py <project>`
  before the next one -- it snapshots the tagged files so `finalize.py` knows what "unchanged"
  means, and a stale snapshot there is the one way injection can go wrong.

For the full schema (build/run commands, workspace pooling, extra correctness checks), see the
comments in `examples/matmul_cpp/project.yaml`.
