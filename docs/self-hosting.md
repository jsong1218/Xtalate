# Self-hosting Xtalate

**Self-hosting is the primary supported deployment.** A "transparent" scientific tool that only runs
on someone else's infrastructure has an asterisk on the word — so every Xtalate feature runs
self-hosted, with **no external SaaS dependency**. This guide takes you from a clean machine to a
running instance, states the backup posture plainly, and lists what to watch in production.

The public hosted instance (if one is running) is a small, aggressively private demonstration
surface — 100 MB cap, short retention. Large-trajectory work is the CLI's and self-hosting's job, and
there is no size limit when you run it yourself. There is also a **hosted demo** on Render —
ephemeral, anonymous, 10 MB cap — a quick way to try the UI without running anything; see
[`docs/hosted-demo.md`](hosted-demo.md).

## What ships, and what you provide

Xtalate runs as **one image with two entrypoints** — the API and the worker — that never carry
different code. `docker-compose.prod.yml` runs that service plus the Redis that carries the job
queue. Two stateful dependencies are deliberately **external**, because they are where durability and
privacy actually live:

| Component | Where it runs | Why |
|---|---|---|
| API (`backend`) | this compose stack | Stateless; serves `/v1`, owns database migrations. |
| Worker (`worker`) | this compose stack | Stateless; executes queued convert/inspect/validate jobs. |
| Job queue (`queue`, Redis) | this compose stack | Ephemeral. Losing it loses only in-flight jobs (resubmittable). |
| **PostgreSQL** | **you provide** | The one component that must never lose data — reports and provenance. |
| **Object storage** (S3-compatible) | **you provide** | Private, lifecycle-expiring uploads and outputs. |
| Web UI + docs site | your reverse-proxy edge | Static/SSR build; served alongside the API under one origin. |

You can run PostgreSQL and object storage as managed services **or** as your own containers on the
same box — either satisfies the zero-SaaS criterion (see [below](#zero-saas-review)). Nothing forces
you onto a proprietary cloud.

## Prerequisites

- Docker with the Compose plugin.
- A reachable **PostgreSQL** database and its URL.
- A reachable **S3-compatible** object store (AWS S3, MinIO, Ceph, Backblaze B2, …), a private
  bucket, and its endpoint + credentials.
- A reverse proxy that terminates TLS and routes the browser's same-origin `/v1/*` to the API (any
  proxy works; Caddy and nginx are common choices).

## 1. Configure the environment

Configuration is **environment-only** — there is no config file format, so the same image behaves per
its environment with no rebuild. Copy the committed template and fill in your values in an
**untracked** `.env` (never commit secrets):

```bash
cp .env.example .env
# edit .env: set your PostgreSQL URL, object-storage endpoint + keys, and (for a public
# instance) at least one API key.
```

The production stack requires these — `docker compose` refuses to start until they are set:

| Variable | Purpose |
|---|---|
| `XTALATE_DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:5432/xtalate` |
| `XTALATE_OBJECT_STORE_ENDPOINT` | Your S3 endpoint URL |
| `XTALATE_OBJECT_STORE_ACCESS_KEY` / `..._SECRET_KEY` | Object-storage credentials |

Every knob and its default is documented in `.env.example`; the ones most operators set:

| Variable | Default | Notes |
|---|---|---|
| `XTALATE_API_KEYS` | *(empty = anonymous)* | **A public instance MUST set at least one** comma-separated key; requests then need `Authorization: Bearer <key>`. |
| `XTALATE_MAX_UPLOAD_BYTES` | `104857600` (100 MB) | Upload ceiling; over-limit uploads get `413 FILE_TOO_LARGE` (see the [error reference](./errors#file_too_large)). |
| `XTALATE_UPLOAD_RETENTION_HOURS` / `XTALATE_OUTPUT_RETENTION_HOURS` | `24` | How long uploaded and output **bytes** live before the storage lifecycle sweeps them. |
| `XTALATE_REPORT_RETENTION_DAYS` | `30` | How long conversion **records and reports** are kept (empty = indefinite). Reports outlive bytes by design. |
| `XTALATE_DOCS_BASE_URL` / `XTALATE_SELF_HOSTING_URL` | GitHub docs | Point these at **your** docs origin so the links the UI renders resolve on your running site. |

## 2. Start the service

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The API applies database migrations on start (`alembic upgrade head`, idempotent), then serves. The
worker waits until the API is healthy — so it never races the schema — then processes the queue.
Verify readiness (green only when PostgreSQL and object storage both answer):

```bash
curl "http://localhost:8000/v1/health?ready=true"
```

To pin a published image instead of building from a clone, set `XTALATE_IMAGE` to a release tag.

## 3. Put a reverse proxy in front

The browser always calls **same-origin `/v1`** (there is no hard-coded API host in the client). In
production your reverse proxy owns that prefix: route `/v1/*` to the API service and everything else
to the Web UI. Terminate TLS at the proxy. The API's versioned path prefix plus permanent redirects
keep clients insulated if the origin ever moves.

> **Two body-size limits sit in front of the API — set both above your upload ceiling.** Uploads
> pass *through* the Web UI's same-origin `/v1` proxy and then through your reverse proxy, and each
> has its own request-body cap that, if lower than `XTALATE_MAX_UPLOAD_BYTES`, fails the upload
> *before* it reaches the API — the reader sees an opaque transport error (a bare `500` or a `413`),
> never the app's own `413 FILE_TOO_LARGE`.
>
> 1. **The Web UI proxy (Next.js).** Next caps a proxied request body at **10 MB** by default
>    (`middlewareClientMaxBodySize`); over that it truncates the body and the upload 500s. `next.config.mjs`
>    already raises this ceiling *above* the backend's upload limit — but it reads that limit from
>    `XTALATE_MAX_UPLOAD_BYTES`, so the **frontend build/runtime must be given the same
>    `XTALATE_MAX_UPLOAD_BYTES` value the backend uses** (compose passes it automatically; a hand-rolled
>    frontend deploy must export it). This keeps the backend the sole gate — an oversize upload is
>    never silently truncated, it is refused with the honest `413`.
> 2. **Your reverse proxy.** nginx defaults to **1 MB** (`client_max_body_size`); several managed edges
>    cap around 10 MB. Set it to at least `XTALATE_MAX_UPLOAD_BYTES` (nginx: `client_max_body_size 100m;`;
>    Caddy has no default limit).

The Web UI and the static docs site are built and served at this edge — there is no production
frontend image as of v1.0 (the guide builds it at the edge). Build them from the `frontend/` project
(`npm ci && npm run build && npm run start`, or a static export) and serve behind the same proxy so
the whole surface shares one origin.

## Backups and restore — the honest posture

**PostgreSQL is the only component that must never lose data.** It holds the conversion and
validation reports and the provenance rows — the actual artifact. "Reports outlive bytes" is only
true if this database is durable.

- **Policy:** nightly logical dumps (`pg_dump`), retained ~30 days, plus WAL archiving where your
  platform offers it. Managed Postgres typically does; a lab-server self-host may accept the
  nightly-only posture.
- **What that means for you, stated plainly:** with nightly-only dumps your worst-case data loss
  (RPO) is **up to 24 hours** — a crash between dumps loses that day's new reports. On a managed
  platform with continuous WAL archiving it is near-zero. This is a real tradeoff, not a detail to
  gloss: choose WAL archiving if losing a day of records is unacceptable.
- **Restore is drilled, not assumed.** Before relying on a backup, restore the latest dump into a
  scratch database and confirm the service starts against it. An untested backup is a hope.

**Object storage is deliberately not backed up.** Uploads and outputs expire in days by design and
are reproducible from their sources by their owners; backing up ephemeral private science would
*increase* privacy exposure for zero recovery value.

**Disaster recovery is single-region and honest:** the plan is "restore the dump into a new
environment from this runbook," with recovery measured in hours. No user science is at risk in an
outage — input files are the user's own, and the records restore from the dump.

## Observability

**Structured logging ships today.** The worker emits one JSON line per lifecycle event to stdout —
the container-native sink — each carrying the correlation IDs the API also returns to users
(`request_id`, `job_id`), plus coarse operational facts (`kind`, `state`, `event`). **Scientific
content is never logged** — no coordinates, no file contents; logs are operational metadata and
uploaded science is private by policy. Aggregate your stdout however your platform prefers; grep a
user's `conversion_id` straight from a bug report.

**Metrics: a specified contract, not yet implemented.** MASTER_SPEC Part 9 §6.1 specifies a
Prometheus-format `/metrics` endpoint on the internal network exposing job counts by kind × terminal
state, `PARSE_ERROR` counts by format, validation pass/fail rates, queue depth, and storage bytes by
class. **That endpoint is not implemented (planned post-1.0)** — this guide will not pretend an
endpoint exists that does not. Until it lands, the structured logs above carry the same facts (state
transitions, error codes, durations) for you to aggregate.

**The five alerts worth having** (Part 9 §6.1) — documented here, not bundled, because every operator
has their own monitoring stack and shipping opinionated dashboards is maintenance surface you did not
ask for. Wire whichever your platform supports:

1. **Readiness failing** — `GET /v1/health?ready=true` returns 503 (a dependency is down).
2. **Failed-job rate > 5% over 15 minutes** — a spike in `failed`/`refused` jobs is the
   scientific-health signal (a parser or exporter regression in the wild).
3. **Queue depth growing monotonically for 30 minutes** — the worker pool is undersized or stuck.
4. **Storage > 80% of budget** — a cost and capacity tripwire.
5. **Retention-sweep lag > 5 minutes** — the byte-expiry privacy promise is application-enforced;
   this alert is its tripwire.

> **Note on the count.** There are **five**, per Part 9 §6.1 — retention-sweep lag (5) is easy to
> forget precisely because it guards the least-visible promise (byte expiry), so it is called out
> here explicitly.

## Zero-SaaS review

The hard criterion (Part 9 §5.4): **every feature works self-hosted with no external SaaS
dependency.** Walked against the shipped surface:

| Feature | Self-hosted with no SaaS? | How |
|---|---|---|
| Parse / inspect / convert / validate (7 formats) | ✅ | Pure Python in the API + worker; no network calls. |
| Recovery workflows (explicit, over HTTP) | ✅ | In-process; the worker resolves references from your own object store. |
| Conversion / validation reports + provenance | ✅ | Stored in **your** PostgreSQL. |
| Upload / download of file bytes | ✅ | Stored in **your** object store (S3-compatible; MinIO/Ceph are self-hostable). |
| Async job queue | ✅ | Redis in this compose stack — no managed queue. |
| Web UI (convert, history, formats, reports) | ✅ | Static/SSR build you serve at your edge; talks only to your `/v1`. |
| Docs site + per-code error reference | ✅ | Rendered from the committed `docs/` Markdown; no external service. |
| Auth (optional API keys) | ✅ | Static keys from your environment; no identity provider required. |

Every row is your own infrastructure. PostgreSQL and object storage are *external to the compose
file* but not external to you — run them as managed services or your own containers; the criterion is
that nothing **forces** a proprietary cloud, and nothing does.

## See also

- [Quickstart](./quickstart) — install the library, CLI, and the dev service.
- [Error reference](./errors) — every error-envelope code and what to do about it.
- [API](./api) — the `/v1` REST surface and its async-job model.
