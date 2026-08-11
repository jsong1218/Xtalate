# Hugging Face Spaces hosted demo

Xtalate runs as a **public, ephemeral, anonymous try-it demo** on Hugging Face Spaces — a
single container that serves the whole stack: the Next.js Web UI and the FastAPI service co-located
behind one exposed port. This guide is the maintainer's manual deploy recipe: the push to the Space
is a deliberate human step (no CI, no token in the repo — `docs/private/DECISIONS.md` D52
discipline).

## What it is

- **One container, both processes.** Next serves the Space's exposed `app_port` (**3000**); FastAPI
  serves `localhost:8000`; Next's existing `/v1` rewrite proxies to it via
  `API_PROXY_TARGET=http://localhost:8000`. The client contract — call same-origin `/v1` — is
  identical to dev and self-host, so there is no CORS surface and no hard-coded API origin.
- **Tier-0, no external dependencies.** The backend runs in its default mode — `inline` job queue
  (no Redis, no separate worker), `filesystem` object store, SQLite — so the container needs
  nothing but itself.
- **A demo policy, baked in** (all overridable via `ENV` in the image): anonymous mode (no API
  keys), a **25 MB upload cap**, short retention (uploads/outputs deleted after 6 hours), and docs
  URLs pointed at the GitHub docs so the error envelope and the `FILE_TOO_LARGE` funnel resolve.
- **The demo banner** (`NEXT_PUBLIC_DEMO_BANNER=1`) states the ephemeral posture on every page and
  funnels larger/private work to the CLI and self-hosting. It is off by default — a self-host never
  renders it.

The repo-root `Dockerfile` (backend-only, used by compose) is **untouched**: the Space has its own
combined shape at [`deploy/huggingface/Dockerfile`](../deploy/huggingface/Dockerfile) with its
launcher [`deploy/huggingface/start.sh`](../deploy/huggingface/start.sh) (tini as PID 1; migrations
→ backend → readiness wait → frontend; the container exits if either process dies, so the platform
restarts it).

## Deploying (manual push)

**1. Create the Space.** On huggingface.co: *New Space* → name it (e.g. `xtalate-demo`) → **Docker**
SDK. The Space's front page (`README.md` in the Space repo) is
[`deploy/huggingface/README.md`](../deploy/huggingface/README.md) — it carries the `sdk: docker` /
`app_port: 3000` metadata and the demo's front-page copy.

**2. Assemble the Space tree** — the Space repo must contain the **full build context** the combined
`Dockerfile` expects (it builds `frontend/` against `../docs/openapi.json` and the `docs/*.md`
corpus, and `pip install ".[service]"` from `pyproject.toml` + `src/`):

```
<space repo root>/
├── Dockerfile              = deploy/huggingface/Dockerfile
├── README.md               = deploy/huggingface/README.md   (the Space's front page)
├── deploy/huggingface/     = the Dockerfile + start.sh, verbatim
├── pyproject.toml, README.md-of-repo  →  pyproject.toml     (README.md is the front page above;
│                                                            the demo image's package metadata is
│                                                            cosmetic — nothing is published from it)
├── src/                    (the library, for pip install)
├── backend/, alembic.ini   (the service layer + migrations)
├── frontend/               (the Web UI, minus node_modules/.next — see below)
└── docs/                   (openapi.json + the docs corpus, for the frontend build)
```

[`scripts/sync-hf-space.sh`](../scripts/sync-hf-space.sh) does exactly this assembly from the
current checkout and pushes it — it copies the tracked files, writes a `.dockerignore` for the
build (excluding `node_modules/`, `.next/`, `docs/private/`, tests, and other non-image inputs), and
commits. The manual steps below are the same recipe spelled out, for when you want to do it by hand:

```bash
git clone https://huggingface.co/spaces/<your-org>/xtalate-demo /tmp/xtalate-demo
cd /tmp/xtalate-demo
cp "$REPO/deploy/huggingface/Dockerfile" .
cp "$REPO/deploy/huggingface/README.md" .
cp -r "$REPO/deploy" .
cp "$REPO/pyproject.toml" "$REPO/src" .
cp -r "$REPO/backend" "$REPO/alembic.ini" .
cp -r "$REPO/frontend" .
cp -r "$REPO/docs" .
# frontend/node_modules, frontend/.next, docs/private must NOT be copied — a .dockerignore
# (git-ignored or committed) with node_modules/, **/.next/, docs/private/, tests/, benchmarks/
# keeps the build context small.
git add -A && git commit -m "Update Xtalate demo"
git push
```

**3. Push.** HF builds the Docker image from the pushed tree and serves it at
`https://huggingface.co/spaces/<org>/xtalate-demo`. The build takes several minutes (npm ci, next
build, pip install). Every update is a re-push of the assembled tree — the Space's Dockerfile is
just the committed file.

## The ephemeral-data caveat (say it plainly)

The demo is **not** a data store: SQLite and the filesystem object store live under the container's
writable home (`/home/user/app`), so the container's lifetime *is* the data lifetime, and retention
is short by policy on top of that. Reports and provenance are the tool's purpose, but on the demo
they are a same-session convenience, not a promise — anyone who needs a durable record downloads
their Conversion Report JSON and runs the offline CLI (which needs no server at all). The banner
and the Space front page both say this; keep them in sync if the policy ever changes.

## Smoke-testing the image locally

```bash
docker build -f deploy/huggingface/Dockerfile -t xtalate-space .
docker run --rm -p 3000:3000 xtalate-space
# then: open http://localhost:3000 — landing + convert show a 25 MB cap (the dynamic /v1/limits
# value), and a real conversion completes end-to-end through the co-located FastAPI via the /v1
# proxy, producing a Conversion Report and a downloadable output.
```

The same code, different caps, proves the numbers are per-environment dynamic: the compose e2e stack
runs `XTALATE_MAX_UPLOAD_BYTES=1048576` (UI shows 1 MB), the demo image bakes 25 MB, and the
self-host default is 100 MB — all from one `next.config.mjs`/`backend/config.py`, nothing hard-coded
in the UI.
