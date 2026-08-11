# Hosted demo (Render)

Xtalate runs as a **public, ephemeral, anonymous try-it demo** on a generic Docker host — a
single container that serves the whole stack: the Next.js Web UI and the FastAPI service co-located
behind one public port. **Render is the primary host** (free tier, no card); **Fly.io is the
documented alternative** (no free tier — see below). This guide is the maintainer's manual deploy
recipe: connecting the repo / deploying is a deliberate human step (no CI, no token in the repo —
`docs/private/DECISIONS.md` D52 discipline).

## What it is

- **One container, both processes.** Next serves the public port (**3000** by default, or the
  platform-injected `$PORT` — Render sets it, e.g. 10000); FastAPI serves `localhost:8000`; Next's
  existing `/v1` rewrite proxies to it via `API_PROXY_TARGET=http://localhost:8000`. The client
  contract — call same-origin `/v1` — is identical to dev and self-host, so there is no CORS
  surface and no hard-coded API origin.
- **Tier-0, no external dependencies.** The backend runs in its default mode — `inline` job queue
  (no Redis, no separate worker), `filesystem` object store, SQLite — so the container needs
  nothing but itself.
- **A demo policy, baked in** (all overridable via `ENV` in the image): anonymous mode (no API
  keys), a **25 MB upload cap**, short retention (uploads/outputs deleted after 6 hours), and docs
  URLs pointed at the GitHub docs so the error envelope and the `FILE_TOO_LARGE` funnel resolve.
- **The demo banner** (`NEXT_PUBLIC_DEMO_BANNER=1`) states the ephemeral posture on every page and
  funnels larger/private work to the CLI and self-hosting. It is off by default — a self-host never
  renders it.

The repo-root `Dockerfile` (backend-only, used by compose) is **untouched**: the demo has its own
combined shape at [`deploy/demo/Dockerfile`](../deploy/demo/Dockerfile) with its launcher
[`deploy/demo/start.sh`](../deploy/demo/start.sh) (tini as PID 1; migrations → backend → readiness
wait → frontend; the container exits if either process dies, so the platform restarts it).

## Deploying on Render (primary)

**1. Connect the repo.** On render.com: **New → Blueprint** → pick the Xtalate repo. Render reads
the [`render.yaml`](../render.yaml) at the repo root (a Blueprint): one `web` service, `runtime:
docker`, `dockerfilePath: ./deploy/demo/Dockerfile`, `dockerContext: .` (the repo root — the build
needs `src/`, `backend/`, `frontend/`, `docs/`, `alembic.ini`, `pyproject.toml`), `plan: free`, and
`healthCheckPath: /v1/health` (hits the public port; the Next `/v1` rewrite forwards it to the
backend). No env vars need setting — the demo policy is baked into the image and Render injects
`$PORT`. Pick the default branch (or the milestone branch while the PR is open). The connect is the
maintainer's manual step — no token or credential ever enters the repo.

**2. Deploy.** The first build takes several minutes (npm ci, next build, pip install); deploys
afterward are fast (the Dockerfile caches dependencies first). Every push to the linked branch
auto-deploys.

**3. Free-tier expectations (say them plainly).** The Render free plan gives **512 MB RAM / 0.1
CPU**, spins the service **down after ~15 minutes idle**, and **cold-starts in ~30–60 s** on the
next request; bandwidth is ~5 GB/month. Fine for a small demo — the 25 MB upload cap and the
`max_frames` frame cap keep any single job bounded on a small box. The demo banner's "ephemeral"
posture already implies a demo that may sleep; if the cold start ever bothers users, the fix is the
paid starter plan (no spin-down), not a code change.

## Deploying on Fly.io (alternative, documented only)

> **No free tier.** Fly.io discontinued its free allowance — this path needs a Fly account with a
> payment method (pay-as-you-go) and the `flyctl` CLI. It is kept as the documented alternative to
> Render, not the default.

```bash
flyctl launch --dockerfile deploy/demo/Dockerfile   # applies deploy/demo/fly.toml
flyctl deploy
```

[`deploy/demo/fly.toml`](../deploy/demo/fly.toml) routes external traffic to `internal_port 3000`
(Fly does not inject a port; the container binds its default), enables `auto_stop_machines` (the
machine stops when idle; the next request wakes it) and checks `/v1/health`.

## The ephemeral-data caveat (say it plainly)

The demo is **not** a data store: SQLite and the filesystem object store live under the container's
writable home (`/home/user/app`), so the container's lifetime *is* the data lifetime — and on the
free tier the container may be recycled when idle — and retention is short by policy on top of
that. Reports and provenance are the tool's purpose, but on the demo they are a same-session
convenience, not a promise — anyone who needs a durable record downloads their Conversion Report
JSON and runs the offline CLI (which needs no server at all). The banner and the demo's front page
both say this; keep them in sync if the policy ever changes.

## Smoke-testing the image locally

```bash
docker build -f deploy/demo/Dockerfile -t xtalate-demo .
# The platform-injected-port path (what Render does — prove the $PORT fix):
docker run --rm -e PORT=10000 -p 10000:10000 xtalate-demo
#   → open http://localhost:10000 — landing + convert show a 25 MB cap (the dynamic /v1/limits
#     value), and a real conversion completes end-to-end through the co-located FastAPI via the /v1
#     proxy, producing a Conversion Report and a downloadable output.
# The default-port path (what Fly/local do):
docker run --rm -p 3000:3000 xtalate-demo
```

The same code, different caps, proves the numbers are per-environment dynamic: the compose e2e stack
runs `XTALATE_MAX_UPLOAD_BYTES=1048576` (UI shows 1 MB), the demo image bakes 25 MB, and the
self-host default is 100 MB — all from one `next.config.mjs`/`backend/config.py`, nothing hard-coded
in the UI.
