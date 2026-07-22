# Xtalate Service image — one artifact for API and worker (MASTER_SPEC Part 9 §2).
#
# The same image runs the API (this file's default CMD) and, from M22, the worker — a second
# entrypoint on the *same* image, so there is no API/worker version skew. This is the "first shape"
# of the M21 compose stack; M25 hardens it (non-root already here; pinned base, healthcheck polish
# later). The library installs from the wheel; backend/ is copied alongside and made importable via
# PYTHONPATH, because it is the service layer, deliberately outside the distributed package.

FROM python:3.13-slim

# No .pyc writes, unbuffered stdout (logs stream), and backend/ + repo root on the import path.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install the library + service extra first, from just the packaging metadata and source, so this
# layer is cached across edits to backend/ and tests/.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[service]"

# The service layer and the migration config (not part of the wheel).
COPY backend ./backend
COPY alembic.ini ./

# Run as a non-root user — the container never needs root, and M25's hardening shouldn't have to
# retrofit it.
RUN useradd --create-home --uid 10001 xtalate \
    && chown -R xtalate:xtalate /app
USER xtalate

EXPOSE 8000

# Apply migrations to whatever database XTALATE_DATABASE_URL points at, then serve. `upgrade head`
# is idempotent, so a restart re-checks and moves on. Production process management (worker count,
# timeouts) is the orchestrator's job — this is the local/first-shape command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn backend.asgi:app --host 0.0.0.0 --port 8000"]
