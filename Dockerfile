# Self-contained image for this repo's OpenEvolve + bundler pipeline: builds
# our openevolve fork and the bundler binary once, at image build time.
# examples/, eval/, config/ stay bind-mounted at runtime (docker-compose.yml)
# so editing a project doesn't require a rebuild.
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
COPY bundler /opt/bundler_src
RUN cmake -S /opt/bundler_src -B /opt/bundler_src/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/bundler_src/build -j"$(nproc)"

# read by eval/harness.py -- outside the bind mount, which would otherwise shadow it
ENV BUNDLER_BIN=/opt/bundler_src/build/bundler

WORKDIR /app
ENTRYPOINT ["python", "/app/openevolve-run.py"]
