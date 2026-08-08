#!/usr/bin/env bash
#
# lifecycle-check.sh — the byte-expiry + retention drill (MASTER_SPEC M37 S3; Part 8 §6 item 5).
#
# Xtalate keeps TWO retention windows, and this drill exercises both (Part 6 §5, Part 9 §5.2):
#
#   * the BYTE window (upload_retention_hours / output_retention_hours) — a bucket lifecycle rule
#     sweeps the objects; expiry is the storage platform's job, never an app cron. The service only
#     OBSERVES it lazily: a download past the horizon (or of an object the bucket already removed) is
#     a clean 410, never a 404 — the record outlives the bytes.
#   * the RECORD window (report_retention_days) — the in-app `sweep_reports` callable ages out the
#     conversion record and cascades to its reports, while the originating upload/job rows survive.
#
# What it proves, against a running stack (dev compose + MinIO by default):
#   1. The bucket carries the byte-expiry lifecycle rules (per-prefix uploads/ + outputs/), read back
#      through boto3 exactly as the app's own S3 adapter would see them — the byte window IS a
#      platform rule, not application code.
#   2. "Reports outlive bytes": a real completed conversion, then its output object is removed the way
#      the lifecycle rule removes it on schedule; the download becomes a clean 410 GONE while the
#      conversion record + its reports still read 200.
#   3. The record window: `sweep_reports` past the horizon deletes the conversion + its reports and
#      leaves the upload/job rows standing (the FK directions that encode "reports outlive bytes").
#
# What it does NOT do in-session: wait for the bucket's own lifecycle scanner to delete an object on
# its real schedule. MinIO's ilm granularity is whole days and a cloud bucket's scan cadence is its
# own; proving deletion-on-schedule against an ACTUAL deployment target (AWS S3 / R2 / B2) is the
# ⏳ maintainer step — see docs/ops/lifecycle-expiry.md. Step 2 here removes the object explicitly to
# prove the *application's* response to an expired byte, which is the half that lives in our code.
#
# Needs only `docker compose` and the running stack — the whole proof runs inside the backend
# container (its boto3 talks to the bucket; urllib talks to the live API on localhost:8000; the
# Repository + sweep run in-process). No host Python, curl, or jq. See docs/ops/lifecycle-expiry.md.
#
# IN-SESSION:  ./scripts/lifecycle-check.sh
# MAINTAINER (real bucket): point the stack's XTALATE_OBJECT_STORE_* at the target bucket and run the
#   same command; then follow docs/ops/lifecycle-expiry.md for the deletion-on-schedule confirmation.
#
# Config (env, dev-compose defaults; production creds come from your environment, never here):
#   COMPOSE, BACKEND_SERVICE, OUT (write the run summary to this path in addition to stdout).
#
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
OUT="${OUT:-}"

log() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

main() {
  log "lifecycle drill — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "compose        : ${COMPOSE}"

  log "0. preflight — the stack is up and ready"
  $COMPOSE ps "$BACKEND_SERVICE" | grep -q . || fail "backend service not found (is the stack up?)"

  # The entire proof runs inside the backend container: boto3 -> bucket, urllib -> live API,
  # Repository + sweep_reports in-process. -T keeps stdin a pipe (no TTY).
  $COMPOSE exec -T "$BACKEND_SERVICE" python - <<'PY' || fail "lifecycle drill failed"
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import timedelta

import boto3
from botocore.config import Config

from backend.config import get_settings
from backend.db import Repository, utcnow
from backend.db.engine import build_engine, build_sessionmaker
from backend.jobs.retention import sweep_reports
from backend.storage import create_object_store

BASE = "http://localhost:8000"
settings = get_settings()
repo = Repository(build_sessionmaker(build_engine(settings)))
store = create_object_store(settings)


def http(method, path, *, data=None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:  # noqa: PERF203 - readable over a tuple-return refactor
        return e.code, e.read()


def upload(filename, content):
    boundary = "----xtalate" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return http(
        "POST",
        "/v1/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def poll(job_id, terminal={"completed", "failed", "cancelled", "expired"}, timeout=60.0):
    deadline = time.monotonic() + timeout
    while True:
        code, raw = http("GET", f"/v1/jobs/{job_id}")
        env = json.loads(raw)
        if env["state"] in terminal:
            return env
        if time.monotonic() > deadline:
            raise SystemExit(f"job {job_id} stuck in {env['state']!r} after {timeout}s")
        time.sleep(0.5)


def check(cond, ok, bad):
    print(f"  {'ok ' if cond else 'BAD'}: {ok if cond else bad}")
    if not cond:
        raise SystemExit(1)


# A single-frame XYZ -> extXYZ conversion is lossless and needs no recovery, so it completes without
# pausing — the simplest real "completed" conversion with genuine output bytes.
SINGLE_XYZ = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""

print("\n--- 1. byte window is a bucket lifecycle rule (read via boto3, as the app's adapter sees it)")
print(f"  retention config: uploads={settings.upload_retention_hours}h "
      f"outputs={settings.output_retention_hours}h record={settings.report_retention_days}d")
if settings.object_store_backend != "s3":
    # Tier 0 (filesystem) has no bucket lifecycle at all — the byte window is then only the record
    # clock. This drill is meaningful against the S3/MinIO Tier 1 stack; say so and stop cleanly.
    raise SystemExit("object store is not 's3' — run this drill against the compose (MinIO) stack")
s3 = boto3.client(
    "s3",
    endpoint_url=settings.object_store_endpoint,
    region_name=settings.object_store_region,
    aws_access_key_id=settings.object_store_access_key,
    aws_secret_access_key=settings.object_store_secret_key,
    config=Config(signature_version="s3v4"),
)
rules = s3.get_bucket_lifecycle_configuration(Bucket=settings.object_store_bucket)["Rules"]
by_prefix = {
    r.get("Filter", {}).get("Prefix"): r for r in rules if r.get("Status") == "Enabled"
}
for prefix in ("uploads/", "outputs/"):
    rule = by_prefix.get(prefix)
    days = (rule or {}).get("Expiration", {}).get("Days")
    check(days is not None, f"{prefix} expires after {days} day(s) (bucket rule)",
          f"no enabled expiry rule for prefix {prefix!r}")

print("\n--- 2. reports outlive bytes: remove the output object, download 410s, record still reads")
code, raw = upload("water.xyz", SINGLE_XYZ)
check(code == 201, f"uploaded ({code})", f"upload returned {code}: {raw[:200]!r}")
file_id = json.loads(raw)["file_id"]
code, raw = http(
    "POST",
    "/v1/convert",
    data=json.dumps({"file_id": file_id, "target_format_id": "extxyz"}).encode(),
    headers={"Content-Type": "application/json"},
)
check(code in (200, 201, 202), f"convert submitted ({code})", f"convert returned {code}: {raw[:200]!r}")
job_id = json.loads(raw)["job_id"]
done = poll(job_id)
check(done["state"] == "completed", "conversion completed", f"job ended {done['state']!r}: {done}")
conversion_id = done["result"]["conversion_id"]

code, _ = http("GET", f"/v1/download/{conversion_id}")
check(code == 200, "download works while bytes exist (200)", f"download returned {code}")
code, _ = http("GET", f"/v1/conversions/{conversion_id}")
check(code == 200, "record reads while bytes exist (200)", f"record returned {code}")

output_key = f"outputs/{conversion_id}"
check(store.exists(output_key), f"output object present in bucket ({output_key})",
      f"expected output object {output_key} missing")

# Remove the object exactly as the bucket's lifecycle rule removes it on schedule.
store.delete(output_key)
check(not store.exists(output_key), "output object removed (simulating lifecycle expiry)",
      "output object still present after delete")

code, raw = http("GET", f"/v1/download/{conversion_id}")
check(code == 410, "download is a clean 410 GONE after byte expiry",
      f"expected 410, got {code}: {raw[:200]!r}")
check(json.loads(raw)["error"]["code"] == "OUTPUT_EXPIRED", "410 body is OUTPUT_EXPIRED",
      f"unexpected 410 body: {raw[:200]!r}")

code, raw = http("GET", f"/v1/conversions/{conversion_id}")
check(code == 200, "conversion record still reads 200 after bytes are gone", f"record returned {code}")
report = json.loads(raw).get("conversion_report") or {}
check(report.get("status") == "completed", "the Conversion Report survived the byte expiry",
      f"unexpected report: {json.dumps(report)[:200]}")

print("\n--- 3. record window: sweep_reports ages out the record; upload/job rows survive the cascade")
assert settings.report_retention_days is not None  # the compose default is 30d
future = utcnow() + timedelta(days=settings.report_retention_days + 1)
deleted = sweep_reports(repo, settings, now=future)
check(conversion_id in deleted, f"sweep deleted the record past the {settings.report_retention_days}d window",
      f"conversion {conversion_id} not in swept set {deleted}")
code, _ = http("GET", f"/v1/conversions/{conversion_id}")
check(code == 404, "conversion record is gone after the record window (404)", f"record returned {code}")
check(repo.get_upload(file_id) is not None, "upload row survives the report cascade",
      "upload row was deleted by the report sweep")
check(repo.get_job(job_id) is not None, "job row survives the report cascade",
      "job row was deleted by the report sweep")

print("\nPASS — byte window is a bucket rule; reports outlive bytes; record window cascades cleanly")
PY

  log "PASS — lifecycle drilled: bucket rule read, reports outlive bytes, record window swept"
  echo
  echo "⏳ maintainer step: deletion-on-schedule against an actual deployment bucket (AWS S3 / R2 / B2)"
  echo "   is not run here — see docs/ops/lifecycle-expiry.md."
}

if [ -n "$OUT" ]; then
  main 2>&1 | tee "$OUT"
else
  main
fi
