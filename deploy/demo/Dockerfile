# Xtalate hosted-demo image (v1.1 M39-S1, re-targeted S1b) — the whole stack in one container.
#
# The hosted demo runs on a generic Docker host: Render is the primary (render.yaml, repo root) and
# Fly.io is the documented alternative (deploy/demo/fly.toml). The host exposes ONE public port to
# the Next.js UI (standalone build), which serves :3000 (or the platform-injected $PORT — Render
# sets $PORT, e.g. 10000; start.sh binds ${PORT:-3000}) and proxies same-origin `/v1/*` to the
# FastAPI service on localhost:8000 via API_PROXY_TARGET — the exact same-origin `/v1` client
# contract as dev and self-host (next.config.mjs's rewrite), so there is no CORS surface and no
# hard-coded API origin in client code. The backend runs in its already-default Tier-0 mode —
# inline job queue, filesystem object store, SQLite (`backend/config.py` defaults) — so the
# container has **no external dependencies** (no Redis, no Postgres, no MinIO, no separate worker).
#
# Build context = the repo root (the deploy guide documents the shape): `src/`, `backend/`,
# `frontend/`, `docs/` (the Next build reads `../docs/openapi.json` for the typed client and
# `../docs/*.md` for the in-app docs site), `alembic.ini`, `pyproject.toml`, and `deploy/`. The
# repo-root `Dockerfile` (backend-only, used by compose) is untouched — this is the demo's own
# shape.

# --- Stage A: build the frontend standalone bundle ----------------------------------------------
FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-build

WORKDIR /repo

# Dependencies first from the lockfile, then the source, so `npm ci` is cached across source edits.
# `--ignore-scripts` defers the postinstall `gen:api` (it reads ../docs/openapi.json, which is not
# in the context yet); the build's own `prebuild` regenerates the typed client later, below.
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci --ignore-scripts

# The full frontend plus the docs corpus it builds against (prebuild `gen:api` reads
# ../docs/openapi.json; the /docs pages render ../docs/*.md at build time).
COPY frontend frontend
COPY docs docs

# The frontend env the NEXT BUNDLE COMPILES IN at build time (next.config.mjs is evaluated during
# `next build`, and NEXT_PUBLIC_ values are inlined — a standalone server does not re-read them at
# runtime): the /v1 rewrite must target the co-located backend (never a compose service name),
# the proxy body-clone ceiling must sit above the backend's own 10 MiB gate (the D112 rule), and
# the demo banner must be on. The final stage's ENV block below repeats these for the backend's
# runtime and for documentation parity — this build-time block is the load-bearing one for Next.
ENV API_PROXY_TARGET=http://localhost:8000 \
    XTALATE_MAX_UPLOAD_BYTES=10485760 \
    NEXT_PUBLIC_DEMO_BANNER=1

# `prebuild` regenerates the typed client, then `next build` emits the self-contained
# `.next/standalone` bundle (`output: "standalone"`, frontend/next.config.mjs).
RUN cd frontend && npm run build

# --- Final stage: the co-located runtime --------------------------------------------------------
FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

# tini as PID 1 so the launcher and its two children get clean signals and no zombies; the Node
# runtime copied from the build stage (python:3.13-slim already carries node's shared libs —
# libstdc++, libgcc_s, libssl3, zlib — verified against the image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node

# backend/ + alembic.ini live outside the distributed package, so the app root joins the import
# path exactly as the repo-root image does (PYTHONPATH=/app there, /home/user/app here).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/user/app \
    HOME=/home/user

WORKDIR /home/user/app

# The library + `service` extra from the packaging metadata and source first (cached across edits
# to backend/ and the frontend bundle), then the service layer and migration config.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[service]"
COPY backend ./backend
COPY alembic.ini ./

# The standalone Next server: `.next/standalone` contents at the app root (server.js plus its
# traced node_modules) with `.next/static` alongside, exactly where the standalone server expects
# them. `output: "standalone"` does NOT copy `public/`, so the vendored samples under
# `frontend/public/samples/` (S4, D246) must be copied explicitly or `/samples/*` 404s on the
# hosted demo (S7 fix).
COPY --from=frontend-build /repo/frontend/.next/standalone/ ./
COPY --from=frontend-build /repo/frontend/.next/static ./.next/static
COPY --from=frontend-build /repo/frontend/public ./public

# The launcher: migrations → backend (background) → readiness wait → frontend (foreground).
COPY deploy/demo/start.sh ./start.sh
RUN chmod +x ./start.sh

# Generic Docker-host convention: run as a non-root user (UID 1000) with a writable $HOME under
# which the SQLite database and filesystem object store live — the demo keeps all state under this
# app dir, which is exactly the ephemeral posture the demo advertises.
RUN useradd --create-home --uid 1000 user \
    && chown -R user:user /home/user/app
USER user

# --- The demo environment (all overridable — these are the demo defaults) ----------------------
# Backend: Tier-0 mode + the demo policy — anonymous (no API keys), a 10 MiB upload cap, short
# retention (v1.2: uploads/outputs 1 h and the conversion record + reports 1 h too, via the sub-day
# `XTALATE_REPORT_RETENTION_HOURS` override — a shared, anonymous instance should not keep one
# visitor's record + report readable for a whole day. This is enforced lazily on every record read
# (a conversion past 1 h reads as 404 / drops out of the shared history), so the window is real even
# though the free box runs no cron to drive the sweep), and docs URLs pointed at the GitHub docs so the
# error envelope's documentation_url and the FILE_TOO_LARGE funnel resolve. XTALATE_ENVIRONMENT is a
# free-form label surfaced in logs and
# /v1/health (backend/config.py never branches scientific behaviour on it) — set to "demo"; the
# previous "huggingface" value is retired, do not monitor for it.
ENV XTALATE_ENVIRONMENT=demo \
    XTALATE_QUEUE_BACKEND=inline \
    XTALATE_OBJECT_STORE_BACKEND=filesystem \
    XTALATE_OBJECT_STORE_ROOT=/home/user/app/_objects \
    XTALATE_DATABASE_URL=sqlite+pysqlite:////home/user/app/_xtalate.db \
    XTALATE_MAX_UPLOAD_BYTES=10485760 \
    XTALATE_UPLOAD_RETENTION_HOURS=1 \
    XTALATE_OUTPUT_RETENTION_HOURS=1 \
    XTALATE_REPORT_RETENTION_HOURS=1 \
    XTALATE_API_KEYS= \
    XTALATE_DOCS_BASE_URL=https://github.com/jsong1218/Xtalate/blob/main/docs/errors.md \
    XTALATE_SELF_HOSTING_URL=https://github.com/jsong1218/Xtalate/blob/main/docs/self-hosting.md
# Frontend runtime: INTERNAL_API_URL is read at RUNTIME by the server-side API client (the
# banner's /v1/limits read) — localhost inside this single container. API_PROXY_TARGET /
# XTALATE_MAX_UPLOAD_BYTES / NEXT_PUBLIC_DEMO_BANNER are repeated here for documentation parity;
# the values that actually reach the standalone bundle are the stage-A build-time ones above.
ENV INTERNAL_API_URL=http://localhost:8000 \
    API_PROXY_TARGET=http://localhost:8000 \
    XTALATE_MAX_UPLOAD_BYTES=10485760 \
    NEXT_PUBLIC_DEMO_BANNER=1

EXPOSE 3000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/home/user/app/start.sh"]
