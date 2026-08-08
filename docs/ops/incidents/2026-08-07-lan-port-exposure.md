# Incident — local dev services published to the LAN (2026-08-07)

**Severity:** medium · **Status:** resolved · **Data impact:** none identified

## Summary

The local development stack (`compose.yaml`) published every service port to `0.0.0.0`
(the host's LAN interface) rather than to loopback. While the stack was up on a wifi network
(LBNL), an automated network scan detected the PostgreSQL container listening on
`198.128.196.40:5432/tcp` and sent an exposure notice. The database was running the compose
default credentials (`xtalate:xtalate`), so any host on the same subnet could have connected
while the stack was running.

## Timeline

- **Trigger:** `docker compose up` on the LBNL wifi network with `compose.yaml`'s default
  `"5432:5432"`-style port mappings, which bind `0.0.0.0`.
- **Detection:** LBNL automated network scan flagged `5432/tcp open postgresql`
  (host `80-a9-97-b-5c-4c.dhcp.lbnl.us`, `198.128.196.40`).
- **Response (2026-08-07):** stack confirmed already down (no live exposure at time of
  investigation); root cause identified; all published ports rebound to loopback; the
  out-of-Docker `next dev` binding closed; this note written.

## Root cause

Docker short-form port mappings (`"HOST:CONTAINER"`, e.g. `"5432:5432"`) bind the host side to
`0.0.0.0` by default, publishing the service to every network interface — including wifi/LAN —
not just to the host. Every service in `compose.yaml` used this form: postgres (5432),
redis/`queue` (6379, **no auth**), minio (9000/9001), backend (8000), frontend (3000).

A second, independent path existed outside Docker: `frontend/package.json`'s `dev` script ran
`next dev`, and Next.js's dev server binds `0.0.0.0` by default. Running the frontend directly on
the host (rather than through compose) would have exposed port 3000 to the LAN regardless of any
compose change.

## Impact / blast radius

- **Exposed while up:** postgres (default creds), redis (no auth), minio (default creds),
  backend API, frontend dev server — all reachable from the local subnet.
- **Data:** the exposed database is a throwaway dev/e2e instance seeded with test fixtures; no
  production or personal data lives in it. No evidence of access; no data loss identified.
- **Not affected:** `docker-compose.prod.yml` — Postgres and object storage are external
  (managed) there and redis is network-internal; only the backend publishes `8000`, by design,
  to sit behind a reverse proxy.

## Remediation

1. **`compose.yaml`** — every published port rebound to loopback
   (`127.0.0.1:${PORT}:CONTAINER`): postgres, redis/`queue`, minio (both ports), backend,
   frontend. Services still reach each other over the compose network by name
   (`postgres:5432`, `queue:6379`); only the *host-side* publish is restricted to loopback, so
   host tooling (psql, the restore drill, Playwright e2e on `localhost`) is unaffected while the
   LAN can no longer reach any service.
2. **`frontend/package.json`** — `dev` script changed to
   `next dev -H ${XTALATE_DEV_HOST:-127.0.0.1}`: on a bare host (no `XTALATE_DEV_HOST` set) it binds
   loopback only, closing the out-of-Docker path. `compose.yaml` sets `XTALATE_DEV_HOST: "::"` for
   the frontend service so *inside the container* the dev server binds all interfaces (dual-stack) —
   required so Docker's port proxy can reach it and so the busybox healthcheck (`wget localhost`,
   which resolves to `::1`) still connects. The host side is still loopback-only via the `ports:`
   bind. To intentionally serve the bare-host dev server to the LAN, run `next dev -H 0.0.0.0`.

   *Note:* a first attempt used a literal `-H 127.0.0.1` in the script plus a `-- -H 0.0.0.0`
   compose override. That bound the container **IPv4-only**, and the healthcheck's `localhost`→`::1`
   lookup was then refused (container stuck `unhealthy`). The dual-stack `::` bind is the fix; the
   e2e run below is what caught the regression before it was committed.

The container-internal `uvicorn --host 0.0.0.0` in the `Dockerfile` is **correct and unchanged**:
that binds all interfaces *inside the container* so Docker's port proxy can reach it. Host
exposure is governed solely by the compose `ports:` host-IP, now loopback.

## Verification

- `docker compose config` reports `host_ip: 127.0.0.1` for all six published ports; with the stack
  up, `lsof` confirmed every published port bound `127.0.0.1` only (via Docker Desktop's proxy).
- From the host: `localhost:3000` and `localhost:8000` both answer `200`; from this machine's LAN
  address (`192.168.1.236:3000`) the connection is refused — the service is not on the wire.
- `lsof -nP -iTCP -sTCP:LISTEN` with the stack down showed no Xtalate service bound to `*` or a
  routable address (the only `*` listeners were unrelated system services: `rapportd`, `Spotify`).
- Full Playwright e2e suite (24 journeys) run through the loopback-bound compose stack: **24/24
  passed** — confirming the frontend↔backend↔proxy path works with every port on loopback.

## Residual risk / notes

- Re-adding a bare `"HOST:CONTAINER"` mapping (no `127.0.0.1:` prefix) to `compose.yaml` re-opens
  the vector. Keep the loopback prefix on every publish.
- Running `docker-compose.prod.yml` on a laptop would expose backend `8000` to the LAN by design;
  it is meant to run behind a reverse proxy, not directly on an untrusted network.
- The macOS application firewall does **not** reliably filter Docker Desktop's published ports —
  the loopback bind, not the firewall, is the control.
- Dev default credentials (`xtalate:xtalate`, minio `xtalate-local-dev`) are acceptable **only**
  because the services are now loopback-only; they must never be paired with a routable bind.

## Lessons

- Default to `127.0.0.1:` on every host port publish in dev compose files; only widen deliberately.
- Assume research/campus networks run active scanners — an exposed default-credential service will
  be found quickly.
