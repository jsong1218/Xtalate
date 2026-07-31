# Quickstart

Xtalate is the trusted translation layer between computational-chemistry file formats — a converter
that tells you exactly what it kept, what it lost, and why. Every conversion produces a **Conversion
Report**: a line-by-line record of each field preserved, dropped because the target format cannot hold
it, or filled in by an explicit recovery choice. Nothing is changed silently.

There are three ways to use it, smallest first. The library and CLI have **no size limit and need no
services** — they are a first-class product, not a preview of the hosted one.

## 1. Install

The pure library and command-line tool:

```bash
pip install xtalate
```

The HTTP service (adds FastAPI and the job/queue/storage stack) is an optional extra:

```bash
pip install "xtalate[service]"
```

> Xtalate's plugin SDK is **not yet frozen** — parser/exporter interfaces may change before v1.0.
> Pin a version if you depend on them.

## 2. Convert a file (CLI)

Inspect what a file contains before touching it — the Information Discovery Engine reports every
canonical field as present (✓) or absent (✗), and never converts:

```bash
xtalate inspect relax.traj
```

Convert, and read the report:

```bash
xtalate convert relax.traj --to poscar -o POSCAR --report report.json
```

If the target format requires something the source lacks (POSCAR needs chemical symbols an XYZ may
not carry), the conversion **pauses and refuses rather than guessing**. Supply the missing data
explicitly with `--recover`, and the choice is recorded in the report as an Assumption:

```bash
xtalate convert min.xyz --to poscar -o POSCAR --recover "missing_species=periodic_table"
```

See the full [CLI reference](./cli) for every command and flag.

## 3. Run the HTTP service

Every operation is available over HTTP under `/v1`. Long-running operations (`inspect`, `convert`,
`validate`) are asynchronous jobs: submit, poll `/v1/jobs/{job_id}`, then retrieve the result.

The fastest way to a working instance is Docker Compose:

```bash
docker compose up --build
```

This brings up the API, a worker, PostgreSQL, object storage, and the Web UI. Open
`http://localhost:3000` for the UI, or drive the API directly:

```bash
# Upload a file, then start a conversion job against it.
curl -F file=@relax.traj http://localhost:8000/v1/files
```

A conversion the engine declines is **not** an HTTP error — it is a completed job whose report has
`status: "refused"` (HTTP 200). Genuine transport failures use the one error envelope documented in
the [error reference](./errors).

Self-hosting is the primary supported deployment. To run your own instance in production — the
hardened `docker-compose.prod.yml`, configuration, backups, and observability — see the
[self-hosting guide](./self-hosting).
