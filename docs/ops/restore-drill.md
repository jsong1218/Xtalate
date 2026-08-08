# Runbook — the PostgreSQL restore drill

`docs/self-hosting.md` promises **"restore is drilled, not assumed": before relying on a backup,
restore the latest dump into a scratch database and confirm the service starts against it. An
untested backup is a hope.** This runbook is that drill turned into a procedure, so the next release's
restore is a rehearsal, not an adventure (MASTER_SPEC Part 8 §6 item 5, the recurring release-checklist
drill).

The database is the durable artifact — the conversion and validation reports, the provenance rows.
"Reports outlive bytes" is only true if this database restores. The drill exists to keep that true.

## What it verifies

1. **A dump restores** into a clean scratch database on the same server (no clobbering the live one).
2. **The DB-schema migration chain is green at head** against the restored data
   (`alembic upgrade head` → `alembic current` reports `(head)`). A *current* dump makes this a no-op
   upgrade — the correct result; an *older* dump runs the real migration steps. The chain's execution
   from base is separately unit-proven in `tests/backend/db/test_migrations.py`.
3. **The service reads the restored data** — row counts round-trip and the ORM opens against the
   scratch database (proving the app starts against a restored instance, not just that bytes loaded).
4. **The canonical-object schema migration works** (`0.1.0 → 1.0.0`, M35 / D114). This is a
   *distinct, library-level* guarantee (`xtalate.schema.migrations`) — the backend stores report
   bodies verbatim and never migrates them on read — but a restored instance's library must still
   read any pre-1.0 persisted Canonical Objects, so the drill demonstrates it end-to-end
   (unit-proven in `tests/schema/test_migrations.py`).

## The command

The drill runs entirely through `docker compose` against the running stack — no host `psql`, no host
Python. That is deliberate: it is exactly the command a maintainer runs at release time.

**Dry run** (proves the *procedure* against the compose Postgres by dumping the live dev database):

```bash
./scripts/restore-drill.sh
```

**Release-time run** (⏳ maintainer step — restore an *actual production dump*):

```bash
DUMP_FILE=/backups/xtalate-YYYY-MM-DD.sql ./scripts/restore-drill.sh
```

Write the run's transcript alongside the release evidence with `OUT=`:

```bash
OUT=docs/ops/drills/restore-drill-$(date -u +%F).txt ./scripts/restore-drill.sh
```

### Configuration

All via environment variables, dev-compose defaults shown. **Production credentials come from your
environment, never from this file or the script** (CLAUDE.md "Never commit secrets"):

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSE` | `docker compose` | The compose invocation. |
| `PG_SERVICE` | `postgres` | The Postgres service name in the stack. |
| `BACKEND_SERVICE` | `backend` | The service whose image carries `alembic` + `xtalate`. |
| `PG_USER` / `PG_PASSWORD` | `xtalate` / `xtalate` | The dev-compose throwaways; override for real. |
| `SRC_DB` | `xtalate` | The database a dry run dumps from. |
| `SCRATCH_DB` | `xtalate_restore_drill` | The throwaway restore target (created + dropped). |
| `DUMP_FILE` | *(unset)* | A real dump to restore; unset ⇒ dry-run `pg_dump` of the live DB. |
| `KEEP_SCRATCH` | *(unset)* | Set to leave the scratch DB in place for inspection. |
| `OUT` | *(unset)* | Also tee the transcript to this path. |

## Expected result

A green run ends with `PASS — restore drilled: dump restored, migration chain green at head, service
read it`. Any failed step aborts with a `FAIL:` line (the script is `set -euo pipefail`). The scratch
database is dropped on completion unless `KEEP_SCRATCH=1`.

A captured in-session dry run lives at
[`drills/restore-drill-2026-08-08.txt`](drills/restore-drill-2026-08-08.txt) as the committed proof
of the procedure. The production-dump run is the maintainer's release-time instance — commit its
transcript beside it.

## Release-checklist placement

Run this drill as part of the release checklist (§6 item 5) whenever the schema changes or a new
release is cut. A restore you have not rehearsed since the last migration is a restore you do not
have.
