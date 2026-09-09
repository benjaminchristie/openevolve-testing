# openevolve-testing

Uses [OpenEvolve](https://github.com/codelion/openevolve) to evolve functions inside real
C/C++/Python projects, instead of one hand-crafted file. A `bundler` tool extracts
`@evolve`-tagged functions from your actual source tree, hands them to OpenEvolve, and splices
the mutations back in.

## Running an example

```sh
git submodule update --init
export OPENAI_API_KEY=...
UID=$(id -u) GID=$(id -g) docker compose up
```

Runs `examples/matmul_cpp` by default. Switch with `EXAMPLE=matmul_py`. Results land in
`openevolve_output/<name>/`; the visualizer comes up on `localhost:8080` once a checkpoint
exists.

Set `UID`/`GID` like that or Docker writes into the repo as root and you'll need sudo to clean
up after.

## Adding your own project

```sh
python3 scripts/new_project.py my_project --language python --objective maximize_accuracy
```

(`--list-objectives` for the full list.) This writes `examples/my_project/` and
`config/my_project.yaml`. Open the generated source file, write your algorithm in `solve()`,
write a real correctness check in `main()`, then:

```sh
python3 eval/prepare.py examples/my_project
EXAMPLE=my_project UID=$(id -u) GID=$(id -g) docker compose up openevolve
```

## Things worth knowing

- Tag a function with `/** @evolve */` (C/C++) or `# @evolve` (Python) right above it.
- Your program has to print one line of JSON to stdout: `{"status": "ok", "metrics": {"duration_ms": 12.3}}`.
  Use the `openevolve_metrics` library instead of building that by hand (`Timer`, `report`,
  `guarded` — see `examples/matmul_cpp/src/main.cpp`).
- Keep the correctness check outside the `@evolve` block. If it's inside, the LLM will eventually
  "optimize" by weakening the check instead of the code.
- Lower `checkpoint_interval` along with `max_iterations` in `config/<name>.yaml` when doing a
  quick test, or the visualizer never sees a checkpoint (default is 100).
- `python3 scripts/test_pipeline.py` runs the whole pipeline locally, no Docker or API key
  needed. Run it after touching `bundler/` or `eval/`.

For the full schema (build/run commands, workspace pooling, extra correctness checks), see the
comments in `examples/matmul_cpp/project.yaml`.
