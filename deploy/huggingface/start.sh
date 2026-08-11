#!/usr/bin/env bash
# start.sh — the Hugging Face Spaces launcher (v1.1 M39-S1).
#
# One container, two processes: the FastAPI service on :8000 (Tier-0 defaults, no external
# dependencies) and the Next.js standalone server on :3000, which the Space exposes as app_port and
# which proxies same-origin /v1/* to the backend via API_PROXY_TARGET. Minimal and explicit:
# migrations first, backend in the background, wait for real readiness, then the frontend in the
# foreground. If either process exits, the script exits (non-zero on failure) so the platform
# restarts the container — a demo that half-died must not keep serving a broken page.
#
# tini is PID 1 (Dockerfile ENTRYPOINT), so signals reach the processes and zombies are reaped.
set -euo pipefail

echo "[start.sh] applying migrations"
alembic upgrade head

echo "[start.sh] starting backend (uvicorn on :8000)"
uvicorn backend.asgi:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Readiness, not liveness: /v1/health?ready=true only turns green once the database and object
# store are wired. Polled with the stdlib (no curl in the slim image); the frontend must never
# start against a backend that is up but not ready.
echo "[start.sh] waiting for backend readiness"
python3 - <<'PY'
import sys
import time
import urllib.request

url = "http://localhost:8000/v1/health?ready=true"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                print("[start.sh] backend ready")
                sys.exit(0)
    except Exception:
        pass
    time.sleep(1)
print("[start.sh] backend failed to become ready within 60s", file=sys.stderr)
sys.exit(1)
PY

echo "[start.sh] starting frontend (Next standalone on :3000)"
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
FRONTEND_PID=$!

# Wait for whichever exits first. `wait -n` returns that child's exit status; `set -e` turns a
# non-zero into the script's exit, so a backend crash restarts the whole container. The survivor is
# reaped as the shell exits.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
