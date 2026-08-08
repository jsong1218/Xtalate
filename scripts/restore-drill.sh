#!/usr/bin/env bash
#
# restore-drill.sh — the PostgreSQL restore drill (MASTER_SPEC M37 S3; Part 8 §6 item 5).
#
# self-hosting.md promises "restore is drilled, not assumed": before relying on a backup, restore the
# latest dump into a scratch database, run the migration chain against it, and confirm the service
# reads it. This script IS that procedure — one command from done, so the next release's restore is a
# drill, not an adventure.
#
# What it does, against a running stack (dev compose by default):
#   1. Acquires a dump — either a real one you pass in (DUMP_FILE=...), or, for a dry run, a fresh
#      `pg_dump` of the live database.
#   2. Restores it into a throwaway scratch database on the same server.
#   3. Runs `alembic upgrade head` against the restored data and asserts it is green and at head —
#      the DB-schema migration chain (backend/db/migrations). A current dump yields a no-op upgrade
#      (the restored schema is already current, which is the correct result); an older dump runs the
#      real steps. The chain's execution from base is separately unit-proven in
#      tests/backend/db/test_migrations.py.
#   4. Confirms the service can read the restored data (row counts round-trip; the ORM opens against
#      the scratch DB).
#   5. Separately demonstrates the *canonical-object* schema migration (0.1.0 → 1.0.0, M35 / D114) —
#      a distinct, library-level guarantee (xtalate.schema.migrations), NOT triggered by the DB
#      restore (the backend stores report bodies verbatim and never migrates them on read). Included
#      here because a restored instance's library must still read any pre-1.0 persisted Canonical
#      Objects; unit-proven in tests/schema/test_migrations.py.
#   6. Drops the scratch database (unless KEEP_SCRATCH=1).
#
# Needs only `docker compose` and the running stack — no host Python, no psql on the host — so it is
# exactly the command a maintainer runs at release time. See docs/ops/restore-drill.md.
#
# IN-SESSION (dry run):   ./scripts/restore-drill.sh
# MAINTAINER (real dump): DUMP_FILE=/backups/xtalate-2026-08-07.sql ./scripts/restore-drill.sh
#
# Config (env, dev-compose defaults shown — production creds come from your environment, never here):
#   COMPOSE, PG_SERVICE, BACKEND_SERVICE, PG_USER, PG_PASSWORD, SRC_DB, SCRATCH_DB, DUMP_FILE,
#   KEEP_SCRATCH, OUT (write the run summary to this path in addition to stdout).
#
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
PG_SERVICE="${PG_SERVICE:-postgres}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
PG_USER="${PG_USER:-xtalate}"
PG_PASSWORD="${PG_PASSWORD:-xtalate}"
SRC_DB="${SRC_DB:-xtalate}"
SCRATCH_DB="${SCRATCH_DB:-xtalate_restore_drill}"
DUMP_FILE="${DUMP_FILE:-}"
KEEP_SCRATCH="${KEEP_SCRATCH:-}"
OUT="${OUT:-}"

# A scratch URL on the same server, different database — what alembic and the ORM point at.
SCRATCH_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@${PG_SERVICE}:5432/${SCRATCH_DB}"

WORKDIR="$(mktemp -d)"
DUMP="${WORKDIR}/dump.sql"
trap 'rm -rf "${WORKDIR}"' EXIT

log() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

# psql/pg_dump run *inside* the postgres container; -T keeps stdin a pipe (no TTY).
psql_src()     { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$SRC_DB" -tAc "$1"; }
psql_scratch() { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$SCRATCH_DB" -tAc "$1"; }
psql_admin()   { $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d postgres -c "$1"; }

counts() {
  # A stable, sorted "table=rows" block for the given db, so source and restored can be diffed.
  local db="$1"
  $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$db" -tAc \
    "select 'conversions='||count(*) from conversions
     union all select 'jobs='||count(*) from jobs
     union all select 'reports='||count(*) from reports
     union all select 'uploads='||count(*) from uploads
     order by 1"
}

drop_scratch() { psql_admin "DROP DATABASE IF EXISTS ${SCRATCH_DB} WITH (FORCE);" >/dev/null; }

main() {
  log "restore drill — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "compose        : ${COMPOSE}"
  echo "scratch db     : ${SCRATCH_DB}"

  log "0. preflight — the stack is up"
  $COMPOSE ps "$PG_SERVICE" | grep -q . || fail "postgres service not found (is the stack up?)"
  psql_admin "select 1" >/dev/null 2>&1 || fail "cannot reach postgres"

  if [ -n "$DUMP_FILE" ]; then
    log "1. dump — using the supplied real dump"
    [ -f "$DUMP_FILE" ] || fail "DUMP_FILE not found: ${DUMP_FILE}"
    cp "$DUMP_FILE" "$DUMP"
    echo "dump           : ${DUMP_FILE} ($(wc -c <"$DUMP") bytes)"
    SRC_COUNTS="(not compared — restoring an external dump, not the live db)"
  else
    log "1. dump — pg_dump the live database (dry run)"
    $COMPOSE exec -T "$PG_SERVICE" pg_dump -U "$PG_USER" -d "$SRC_DB" >"$DUMP"
    echo "dump           : $(wc -c <"$DUMP") bytes from live ${SRC_DB}"
    SRC_COUNTS="$(counts "$SRC_DB")"
    echo "source counts  :"; echo "$SRC_COUNTS" | sed 's/^/  /'
  fi

  log "2. scratch — (re)create ${SCRATCH_DB}"
  drop_scratch
  psql_admin "CREATE DATABASE ${SCRATCH_DB};" >/dev/null
  echo "created        : ${SCRATCH_DB}"

  log "3. restore — load the dump into the scratch database"
  $COMPOSE exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -q <"$DUMP"
  echo "restored       : ok"

  log "4. migration chain — alembic upgrade head against the restored data"
  $COMPOSE exec -T -e "XTALATE_DATABASE_URL=${SCRATCH_URL}" "$BACKEND_SERVICE" alembic upgrade head
  CURRENT="$($COMPOSE exec -T -e "XTALATE_DATABASE_URL=${SCRATCH_URL}" "$BACKEND_SERVICE" \
    alembic current 2>/dev/null | tr -d '\r')"
  echo "alembic current: ${CURRENT}"
  echo "$CURRENT" | grep -q '(head)' || fail "alembic is not at head after restore"

  log "5. service reads restored data — row counts"
  RESTORED_COUNTS="$(counts "$SCRATCH_DB")"
  echo "restored counts:"; echo "$RESTORED_COUNTS" | sed 's/^/  /'
  if [ -z "$DUMP_FILE" ]; then
    [ "$SRC_COUNTS" = "$RESTORED_COUNTS" ] || fail "row counts differ after restore"
    echo "round-trip     : source and restored counts match"
  fi
  # The ORM opens against the scratch DB and reads a row — proving the service starts against it.
  $COMPOSE exec -T -e "XTALATE_DATABASE_URL=${SCRATCH_URL}" "$BACKEND_SERVICE" python -c '
from backend.config import get_settings
from backend.db.engine import build_engine, build_sessionmaker
from backend.db.models import Conversion
sm = build_sessionmaker(build_engine(get_settings()))
with sm() as s:
    n = s.query(Conversion).count()
print(f"ORM opened scratch db and read conversions: {n}")
' || fail "the service ORM could not read the restored database"

  log "6. canonical schema migration — 0.1.0 -> 1.0.0 (library-level, separate from the DB restore)"
  # Pipe a real 0.1.0 Canonical Object (a golden fixture) through load_canonical and confirm it is
  # carried to the current schema and stamped. This is NOT part of the DB restore — the backend never
  # migrates stored report bodies — but a restored instance's library must read pre-1.0 objects.
  $COMPOSE exec -T "$BACKEND_SERVICE" python -c '
import sys, json
from xtalate.schema.migrations import load_canonical
raw = sys.stdin.read()
before = json.loads(raw)["schema_version"]
obj = load_canonical(raw)
recs = [r for r in obj.provenance.history if r.operation == "migrate"]
assert obj.schema_version == "1.0.0", obj.schema_version
assert len(recs) == 1, recs
print(f"canonical object migrated {before} -> {obj.schema_version}; recorded: {recs[-1].assumptions[0]}")
' < tests/golden/xyz/water-traj/expected.canonical.json || fail "canonical migration did not run"

  if [ -n "$KEEP_SCRATCH" ]; then
    log "7. cleanup — KEEP_SCRATCH set, leaving ${SCRATCH_DB} in place"
  else
    log "7. cleanup — drop ${SCRATCH_DB}"
    drop_scratch
    echo "dropped        : ${SCRATCH_DB}"
  fi

  log "PASS — restore drilled: dump restored, migration chain green at head, service read it"
}

if [ -n "$OUT" ]; then
  main 2>&1 | tee "$OUT"
else
  main
fi
