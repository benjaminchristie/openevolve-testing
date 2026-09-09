# Self-contained image for running this repo's OpenEvolve + bundler pipeline.
#
# Building our own -- rather than patching the upstream
# ghcr.io/algorithmicsuperintelligence/openevolve image at container startup,
# which is what docker-compose.yml did before this -- means:
#   - cmake/git/ccache are installed once, at image build time, not on every
#     `docker compose up`.
#   - the bundler binary is compiled once, at image build time, into a path
#     outside the bind-mounted repo (see BUNDLER_BIN below), so a running
#     container never needs network access to fetch tree-sitter grammars or
#     run a C++ compile at startup.
#   - we track our own openevolve fork (third_party/openevolve) directly,
#     rather than whatever "latest" happens to resolve to upstream.
#
# examples/, eval/, and config/ are deliberately NOT copied in here -- they
# stay bind-mounted at runtime (docker-compose.yml's `./:/app2`), so editing
# a project.yaml or an example's source doesn't require an image rebuild.
# Only the two things that are genuinely build artifacts -- the openevolve
# package itself and the bundler binary -- are baked in.
#
# Requires the third_party/openevolve submodule to be checked out before
# `docker build` runs (git submodule update --init).

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    ccache \
    && rm -rf /var/lib/apt/lists/*

# --- OpenEvolve (our fork) ---
WORKDIR /app
COPY third_party/openevolve /app
RUN pip install --no-cache-dir --root-user-action=ignore -e . \
    && pip install --no-cache-dir --root-user-action=ignore pyyaml

# --- bundler (built once here, not at container startup) ---
COPY bundler /opt/bundler_src
RUN cmake -S /opt/bundler_src -B /opt/bundler_src/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/bundler_src/build -j"$(nproc)"

# Read by eval/harness.py's _default_bundler_bin(); overrides the
# repo-relative bundler/build/bundler default, which would otherwise resolve
# inside the bind mount and find nothing (the mount shadows anything COPY'd
# to that same path in the image).
ENV BUNDLER_BIN=/opt/bundler_src/build/bundler

WORKDIR /app
ENTRYPOINT ["python", "/app/openevolve-run.py"]
