# Runbook — the byte-expiry + retention drill

Xtalate keeps **two** retention windows, and self-hosting depends on both behaving as advertised
(MASTER_SPEC Part 6 §5, Part 9 §5.2; the recurring release-checklist drill, Part 8 §6 item 5):

- **The byte window** (`upload_retention_hours` / `output_retention_hours`, default 24 h) is a
  **bucket lifecycle rule** — the storage platform sweeps the objects on its own schedule, *never* an
  application cron. The service only **observes** the expiry lazily: a download past the horizon, or
  of an object the bucket has already removed, is a clean **`410 OUTPUT_EXPIRED`** — never a `404`,
  because the record outlives the bytes.
- **The record window** (`report_retention_days`, default 30, `None` = indefinite) is the in-app
  `sweep_reports` callable (`backend.jobs.retention`). It ages out the conversion record and cascades
  to its reports, while the originating upload/job rows survive.

"Reports outlive bytes" is the whole point: a client can still read *what happened* — the Conversion
and Validation reports — after the file itself is gone. The FK directions encode it
(Conversion→Upload `ON DELETE SET NULL`; Report→Job/Conversion `ON DELETE CASCADE`).

## What it verifies

1. **The byte window is a bucket rule.** The drill reads the bucket's lifecycle configuration back
   through boto3 — exactly as the app's S3 adapter would see it — and asserts an enabled expiry rule
   exists for both the `uploads/` and `outputs/` prefixes. This is application-independent: expiry is
   the platform's job.
2. **Reports outlive bytes.** It runs a real conversion to `completed`, confirms the download and
   record both read `200`, then removes the output object **the way the lifecycle rule removes it on
   schedule** and confirms the download becomes a clean `410 OUTPUT_EXPIRED` while the conversion
   record + its Conversion Report still read `200`.
3. **The record window cascades cleanly.** It calls `sweep_reports` past the horizon and confirms the
   conversion record is deleted (record now `404`) while the upload and job rows survive.

## What it does *not* do in-session

It does **not** wait for the bucket's own lifecycle scanner to delete an object on its real schedule.
MinIO's ilm granularity is whole days and a cloud bucket's scan cadence is its own. Step 2 removes the
object *explicitly* to exercise the half that lives in **our** code — the application's response to an
expired byte. Confirming **deletion-on-schedule against an actual deployment bucket** is the
⏳ maintainer step below; the v1.0 plan is explicit it must be run against "an actual deployment
target, not MinIO-in-compose."

## The command

The drill runs entirely inside the backend container (its boto3 talks to the bucket; urllib talks to
the live API on `localhost:8000`; the `Repository` + `sweep_reports` run in-process), so it needs only
`docker compose` and the running stack.

**In-session** (against the compose MinIO/Postgres — proves the application side fully):

```bash
./scripts/lifecycle-check.sh
```

Capture the transcript with `OUT=`:

```bash
OUT=docs/ops/drills/lifecycle-check-$(date -u +%F).txt ./scripts/lifecycle-check.sh
```

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSE` | `docker compose` | The compose invocation. |
| `BACKEND_SERVICE` | `backend` | The service whose image carries boto3 + `xtalate` + the API. |
| `OUT` | *(unset)* | Also tee the transcript to this path. |

Object-store and retention values are read from the backend's own settings
(`XTALATE_OBJECT_STORE_*`, `*_retention_*`), so the drill always checks the window the running
instance actually enforces.

## ⏳ Maintainer step — the real bucket

Point a stack at the **actual deployment target** (`XTALATE_OBJECT_STORE_ENDPOINT` / `_BUCKET` /
`_ACCESS_KEY` / `_SECRET_KEY` for AWS S3 / Cloudflare R2 / Backblaze B2 — supplied from your
environment, never committed) and:

1. Run `./scripts/lifecycle-check.sh` against it — steps 1–3 confirm the bucket carries the expiry
   rules and the application side behaves.
2. Confirm **deletion-on-schedule**: upload an object under `uploads/` (or `outputs/`), then verify
   the platform deletes it after the configured window — e.g. set a short expiry rule, upload, wait
   past the horizon, and confirm the object is gone and its download `410`s. On AWS S3 the lifecycle
   scan runs roughly daily; plan the wait accordingly, or use the platform's console to confirm the
   rule is attached and enabled.
3. Commit the transcript beside the in-session one as the release evidence.

## Expected result

A green run ends with `PASS — lifecycle drilled: bucket rule read, reports outlive bytes, record
window swept`, followed by the ⏳ maintainer-step reminder. Any failed check aborts with a `BAD:` /
`FAIL:` line (the script is `set -euo pipefail`).

A captured in-session run lives at
[`drills/lifecycle-check-2026-08-08.txt`](drills/lifecycle-check-2026-08-08.txt) as the committed
proof of the application side.
