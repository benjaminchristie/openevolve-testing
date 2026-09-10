# Self-contained image for this repo's OpenEvolve + bundler pipeline: builds
# our openevolve fork, the bundler binary, and the eval harness once, at image
# build time. Only the project being evolved is bind-mounted at runtime
# (docker-compose.yml) -- it can be any directory on the host with a
# project.yaml, not just something living inside this repo.
#
# Build context is the repo root (see docker-compose.yml's build.context),
# not this docker/ directory -- every path below is relative to that root.
#
# Requires third_party/openevolve to be checked out first:
#   git submodule update --init

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
COPY bundler /opt/bundler
RUN cmake -S /opt/bundler -B /opt/bundler/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/bundler/build -j"$(nproc)"

# read by eval/harness.py -- outside the bind mount, which would otherwise shadow it
ENV BUNDLER_BIN=/opt/bundler/build/bundler

# --- the eval harness itself (not the user's project) ---
COPY eval /opt/openevolve_eval

# --- what docker-compose.yml actually runs ---
COPY docker/entrypoint-evolve.sh docker/entrypoint-visualizer.sh /opt/
RUN chmod +x /opt/entrypoint-evolve.sh /opt/entrypoint-visualizer.sh

WORKDIR /app
ENTRYPOINT ["/opt/entrypoint-evolve.sh"]
