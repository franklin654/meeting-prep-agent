# Meeting Prep Agent — backend (FastAPI) dev image.
#
# Single-stage, dev-oriented per AGENTS.md ("hackathon demo stack", not a
# hardened production build). docker-compose.yml bind-mounts ./backend:/app
# over this image at runtime, so WORKDIR is /app and the app must run cleanly
# from there; the virtualenv lives at /opt/venv (outside /app) so the mount
# doesn't shadow it — see below.

FROM python:3.11-slim

# uv: single static binary, no extra Python bootstrapping needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Put the virtualenv outside /app: docker-compose.yml bind-mounts
# ./backend:/app for live dev, which would otherwise shadow an in-project
# .venv and remove uvicorn from PATH the moment the mount is applied.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy dependency manifests first so dependency install is cached separately
# from application code changes.
COPY pyproject.toml uv.lock ./

# Install deps only (no source yet).
RUN uv sync --frozen --no-install-project

# Now copy the rest of the source (used for standalone `docker run`, without
# compose's bind mount; under compose this is shadowed by the mount, and
# `uv sync` below reruns via the bind-mounted source instead).
COPY . .

RUN uv sync --frozen

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
