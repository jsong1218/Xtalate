"""``GET /v1/conversions/{id}`` and ``GET /v1/history`` — records + history (M24 slice 3).

One test drives the real path end to end (upload → convert → fetch the record, reports verbatim and
the bytes still downloadable); the rest seed conversion rows directly so the reports-outlive-bytes
promise, the history summaries, keyset pagination, and the live-upload ``file_id`` affordance can be
exercised in isolation. The records surface reads only persisted rows, so a seeded record is a
faithful stand-in for one a real convert wrote.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from backend.db import utcnow
from backend.db.models import Conversion, Job, Report, Upload

if TYPE_CHECKING:
    from backend.db import Repository

XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def _report_body(
    *,
    source_format: str = "xyz",
    target_format: str = "xyz",
    source_filename: str = "water.xyz",
    target_filename: str = "output.xyz",
    preserved: int = 2,
    removed: int = 1,
    assumptions: int = 0,
    warnings: int = 3,
) -> dict[str, object]:
    """A minimal ConversionReport-shaped body — only the fields the records surface reads."""
    return {
        "report_id": uuid.uuid4().hex,
        "stage": "final",
        "status": "completed",
        "mode": "permissive",
        "created_at": "2026-07-23T00:00:00+00:00",
        "source": {
            "format_id": source_format,
            "filename": source_filename,
            "sha256": "deadbeef",
            "schema_version": "1",
        },
        "target": {"format_id": target_format, "filename": target_filename},
        "preserved": [{"path": f"p{i}"} for i in range(preserved)],
        "removed": [{"path": f"r{i}", "reason": "unrepresentable"} for i in range(removed)],
        "assumptions": [
            {"id": f"A{i}", "scenario": "s", "choice": "c", "origin": "preset", "description": "d"}
            for i in range(assumptions)
        ],
        "warnings": [
            {"code": "W", "message": "m", "source": "capability"} for _ in range(warnings)
        ],
    }


def _seed_conversion(
    repository: Repository,
    *,
    created_at: datetime | None = None,
    validation_status: str | None = "passed",
    output_available: bool = True,
    expires_delta: timedelta | None = timedelta(hours=1),
    source_file_id: str | None = None,
    report_body: dict[str, object] | None = None,
) -> str:
    """Persist a job + conversion + conversion report with full control of the record's fields."""
    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(job_id=job_id, kind="convert", state="completed", request={}, finished_at=utcnow())
    )
    conversion_id = f"cnv-{uuid.uuid4().hex}"
    key = f"outputs/{conversion_id}" if output_available else None
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job_id,
            source_file_id=source_file_id,
            source_format="xyz",
            target_format="xyz",
            output_storage_key=key,
            output_available=output_available,
            output_expires_at=(utcnow() + expires_delta) if expires_delta is not None else None,
            conversion_status="completed",
            validation_status=validation_status,
            created_at=created_at or utcnow(),
        )
    )
    repository.add_report(
        Report(
            report_id=uuid.uuid4().hex,
            job_id=job_id,
            conversion_id=conversion_id,
            kind="conversion",
            body=report_body or _report_body(),
        )
    )
    return conversion_id


def _seed_upload(repository: Repository, *, expires_delta: timedelta) -> str:
    file_id = uuid.uuid4().hex
    repository.add_upload(
        Upload(
            file_id=file_id,
            filename="water.xyz",
            sha256="deadbeef",
            size_bytes=42,
            storage_key=f"uploads/{file_id}",
            expires_at=utcnow() + expires_delta,
        )
    )
    return file_id


# --- GET /v1/conversions/{id} -------------------------------------------------------------------


def test_conversion_record_round_trips_reports_and_download(
    client: TestClient, repository: Repository
) -> None:
    # The real path: convert XYZ → xyz, then read the record. Both reports come back verbatim and
    # the download block says the output is still fetchable, with its real size and expiry.
    file_id = _upload(client, XYZ_SAMPLE, "water.xyz")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}).json()
    assert env["state"] == "completed", env
    conversion_id = env["result"]["conversion_id"]

    resp = client.get(f"/v1/conversions/{conversion_id}")
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["conversion_id"] == conversion_id
    assert record["conversion_report"]["status"] == "completed"
    assert record["validation_report"] is not None
    assert record["source"]["format_id"] == "xyz"
    assert record["target"]["format_id"] == "xyz"
    assert record["download"]["available"] is True
    assert record["download"]["filename"] == "output.xyz"
    assert record["download"]["size_bytes"] is not None
    assert record["download"]["expires_at"] is not None


def test_conversion_record_unknown_is_404(client: TestClient) -> None:
    resp = client.get("/v1/conversions/cnv-nope")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "CONVERSION_NOT_FOUND"


def test_conversion_record_outlives_expired_bytes(
    client: TestClient, repository: Repository
) -> None:
    # Reports-outlive-bytes: once the output has expired the record still serves both its reports,
    # and the download block reports the bytes are gone (available=false, no size, no expiry).
    conversion_id = _seed_conversion(repository, output_available=False, expires_delta=None)

    resp = client.get(f"/v1/conversions/{conversion_id}")
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["conversion_report"]["status"] == "completed"
    assert record["download"]["available"] is False
    assert record["download"]["size_bytes"] is None
    assert record["download"]["expires_at"] is None
    # requires_ack still reflects the stored validation status even with the bytes gone.
    assert record["download"]["requires_ack"] is False


def test_conversion_record_past_horizon_is_unavailable(
    client: TestClient, repository: Repository
) -> None:
    # Bytes still flagged available but the record's horizon has passed: the lazy check reports the
    # download unavailable, matching the download endpoint's 410 — the two never disagree.
    conversion_id = _seed_conversion(repository, expires_delta=timedelta(hours=-1))

    record = client.get(f"/v1/conversions/{conversion_id}").json()
    assert record["download"]["available"] is False


# --- GET /v1/history ----------------------------------------------------------------------------


def test_history_summarizes_conversions_newest_first(
    client: TestClient, repository: Repository
) -> None:
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    oldest = _seed_conversion(repository, created_at=base)
    newest = _seed_conversion(
        repository,
        created_at=base + timedelta(minutes=5),
        report_body=_report_body(preserved=4, removed=2, assumptions=1, warnings=0),
    )

    body = client.get("/v1/history").json()
    ids = [item["conversion_id"] for item in body["items"]]
    assert ids == [newest, oldest], ids  # newest first
    top = body["items"][0]
    assert top["summary_counts"] == {
        "preserved": 4,
        "removed": 2,
        "assumptions": 1,
        "warnings": 0,
    }
    assert top["source"]["format_id"] == "xyz"
    assert "sha256" not in top["source"]  # source minus hashes
    assert top["conversion_status"] == "completed"
    assert top["validation_status"] == "passed"


def test_history_paginates_with_a_cursor(client: TestClient, repository: Repository) -> None:
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    ids = [_seed_conversion(repository, created_at=base + timedelta(minutes=i)) for i in range(3)]
    newest_first = list(reversed(ids))

    first = client.get("/v1/history", params={"limit": 2}).json()
    assert [i["conversion_id"] for i in first["items"]] == newest_first[:2]
    assert first["next_cursor"] is not None

    second = client.get("/v1/history", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["conversion_id"] for i in second["items"]] == newest_first[2:]
    assert second["next_cursor"] is None  # last page


def test_history_file_id_present_only_while_upload_lives(
    client: TestClient, repository: Repository
) -> None:
    live_upload = _seed_upload(repository, expires_delta=timedelta(hours=1))
    dead_upload = _seed_upload(repository, expires_delta=timedelta(hours=-1))
    with_live = _seed_conversion(repository, source_file_id=live_upload)
    with_dead = _seed_conversion(repository, source_file_id=dead_upload)
    without = _seed_conversion(repository, source_file_id=None)

    items = {i["conversion_id"]: i for i in client.get("/v1/history").json()["items"]}
    assert items[with_live]["file_id"] == live_upload
    assert items[with_dead]["file_id"] is None  # upload expired ⇒ no re-convert affordance
    assert items[without]["file_id"] is None


def test_history_rejects_a_malformed_cursor(client: TestClient) -> None:
    resp = client.get("/v1/history", params={"cursor": "not-a-real-cursor!!"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"
