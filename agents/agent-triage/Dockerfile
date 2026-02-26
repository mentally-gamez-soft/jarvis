# =============================================================================
# agent-triage — Docker image
#
# Build:  GH_TOKEN=$(gh auth token) docker build --secret id=gh_token,env=GH_TOKEN -t agent-triage .
# Run:    docker run --env-file .env agent-triage
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — builder: install Python dependencies into a venv
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# git is required by uv to clone the github-copilot-sdk Git dependency
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency locking / installation
RUN pip install --no-cache-dir uv

# Copy only dependency files first (layer-cache friendly)
COPY requirements.in requirements.txt ./

# Create a virtual environment and install runtime dependencies
RUN uv venv /venv && \
    uv pip install --python /venv/bin/python --no-cache -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Install cron, tini (PID-1 init / signal reaper), curl, and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
        tini \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Install the GitHub CLI + Copilot extension
# (Required by the GitHub Copilot Python SDK)
#
# GH_TOKEN is passed as a Docker build secret so it is never baked into
# any image layer. Mount it at build time:
#   docker build --secret id=gh_token,env=GH_TOKEN ...
# ---------------------------------------------------------------------------
ARG GH_CLI_VERSION=2.67.0
RUN --mount=type=secret,id=gh_token \
    curl -fsSL \
        "https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}/gh_${GH_CLI_VERSION}_linux_amd64.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local && \
    GH_TOKEN=$(cat /run/secrets/gh_token) gh extension install github/gh-copilot --force

# ---------------------------------------------------------------------------
# Copy the virtual environment from the builder stage
# ---------------------------------------------------------------------------
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ---------------------------------------------------------------------------
# Copy application source
# ---------------------------------------------------------------------------
WORKDIR /app

# Copy rules so epic_generator can load challenge-requirements.md at runtime
COPY rules/ /rules/

# Copy the agent source package into the image root so it is importable
# by `python -m agent_triage.main` (package becomes /app/agent_triage).
COPY src/ ./

# ---------------------------------------------------------------------------
# Cron setup
# ---------------------------------------------------------------------------
# The crontab is generated at container start by the entrypoint so that
# POLL_INTERVAL_MINUTES from the .env is respected.
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/crontab.template /crontab.template
RUN chmod +x /entrypoint.sh

# Create the data directory (mounted as a named volume in docker-compose).
# The cron log lives here so it survives container recreations.
RUN mkdir -p /app/data && touch /app/data/agent-triage.log

# tini is PID 1: reaps zombies and forwards signals to the entrypoint.
# This ensures SIGTERM from `docker stop` reaches cron and triggers graceful shutdown.
ENTRYPOINT ["tini", "--"]
CMD ["/entrypoint.sh"]
