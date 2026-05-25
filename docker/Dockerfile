# GYST containerized — single-container deploy of the full app, listening
# on :10443 with its own self-signed Caddy cert. SQLite DBs + photos live
# in the `gyst-docker-data` named volume.
#
# Build context is the REPO ROOT (one level up). The compose file in this
# directory sets that up automatically:
#     cd docker && docker compose up -d --build
FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_VERSION=22

# ---- System deps -----------------------------------------------------------
# - caddy: TLS-terminating front. `tls internal` mints its own CA so the
#   container's certs are independent from any host Caddy.
# - nodejs 22: Reflex 0.9 shells out to node during compile (rolldown).
# - sqlite3: useful for poking at the DBs inside the container.
# - libgl1 / libglib2.0-0: torch/torchvision wheels need these.
# - unzip / git: Reflex installs bun on first run via a downloaded zip.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https \
        sqlite3 libgl1 libglib2.0-0 procps unzip git \
    && curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sed "s|signed-by=/etc/apt/keyrings/caddy-stable-archive-keyring.gpg|signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg|" > /etc/apt/sources.list.d/caddy-stable.list \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends caddy nodejs \
    && rm -rf /var/lib/apt/lists/*

# ---- Python deps -----------------------------------------------------------
WORKDIR /app
COPY requirements.txt /app/requirements.txt
# CPU-only torch wheels save ~2 GB vs CUDA wheels. The OWL-ViT detector is
# defaulted off in recognize.py so torch is rarely exercised, but it's
# imported at module load and must be installable.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        torch torchvision \
    && pip install -r /app/requirements.txt

# ---- App code --------------------------------------------------------------
# Build context is the repo root; .dockerignore strips `docker/`, `.git`,
# venvs, build artifacts, and any committed user data. Everything else
# lands at /app verbatim. rxconfig binds Reflex to 127.0.0.1:3002 which
# matches the internal Caddy upstream.
COPY . /app/

# /app/data is anchored by config.py (DATA_DIR = _PROJECT_ROOT / "data"),
# so every SQLite DB + the photos store lands here. Declared as a volume
# so a `docker compose down` doesn't drop the data.
RUN mkdir -p /app/data/photos

# Reflex needs HOME + REFLEX_DIR for state cache. Put them on the volume
# so the compile cache survives container restarts.
ENV HOME=/app/data \
    REFLEX_DIR=/app/data/reflex \
    XDG_DATA_HOME=/app/data/caddy-data \
    XDG_CONFIG_HOME=/app/data/caddy-config \
    GYST_PUBLIC_ORIGIN=https://localhost:10443 \
    PYTHONPATH=/app:/app/house_demo

# ---- Caddy + entrypoint ----------------------------------------------------
COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 10443
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -ksf https://127.0.0.1:10443/ -o /dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
