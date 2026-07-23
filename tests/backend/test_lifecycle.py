"""Lifecycle — immediate file delete, report-retention sweep, reports-outlive-bytes (M24 slice 4).

The two retention windows meet here. ``DELETE /v1/files/{id}`` is the user-initiated byte removal
(the timed storage sweep's manual counterpart); :func:`~backend.jobs.retention.sweep_reports` is the
longer record window. Both must honour reports-outlive-bytes: deleting the *bytes* (by either path)
never touches the conversion record or its reports — only the record window does, and only after the
much longer horizon.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from backend.db import utcnow
from backend.db.models import Conversion, Job, Report
from backend.jobs.retention import sweep_reports

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository
    from backend.storage import ObjectStore

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


def _report_body(status: str = "completed") -> dict[str, object]:
    return {
        "report_id": uuid.uuid4().hex,
        "stage": "final",
        "status": status,
        "mode": "permissive",
        "created_at": "2026-07-23T00:00:00+00:00",
        "source": {
            "format_id": "xyz",
            "filename": "water.xyz",
            "sha256": "d",
            "schema_version": "1",
        },
        "target": {"format_id": "xyz", "filename": "output.xyz"},
        "preserved": [{"path": "atoms.positions"}],
        "removed": [],
        "assumptions": [],
        "warnings": [],
    }


def _seed_conversion(
    repository: Repository,
    object_store: ObjectStore,
    *,
    created_at: datetime | None = None,
    output_available: bool = True,
    put_bytes: bool = True,
    expires_delta: timedelta | None = timedelta(hours=1),
    with_validation: bool = True,
) -> str:
    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(job_id=job_id, kind="convert", state="completed", request={}, finished_at=utcnow())
    )
    conversion_id = f"cnv-{uuid.uuid4().hex}"
    key = f"outputs/{conversion_id}"
    if put_bytes:
        object_store.put(key, [b"OUTPUT\n"])
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job_id,
            source_format="xyz",
            target_format="xyz",
            output_storage_key=key if output_available else None,
            output_available=output_available,
            output_expires_at=(utcnow() + expires_delta) if expires_delta is not None else None,
            conversion_status="completed",
            validation_status="passed",
            created_at=created_at or utcnow(),
        )
    )
    repository.add_report(
        Report(
            report_id=uuid.uuid4().hex,
            job_id=job_id,
            conversion_id=conversion_id,
            kind="conversion",
            body=_report_body(),
        )
    )
    if with_validation:
        repository.add_report(
            Report(
                report_id=uuid.uuid4().hex,
                job_id=job_id,
                conversion_id=conversion_id,
                kind="validation",
                body={"status": "passed"},
            )
        )
    return conversion_id


# --- DELETE /v1/files/{file_id} -----------------------------------------------------------------


def test_delete_file_removes_bytes_but_keeps_conversion_record(
    client: TestClient, repository: Repository
) -> None:
    # Convert a real file (so a conversion references the upload), then delete the file. The upload
    # bytes are gone, but the conversion record and both reports survive (reports-outlive-bytes).
    file_id = _upload(client, XYZ_SAMPLE, "water.xyz")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}).json()
    conversion_id = env["result"]["conversion_id"]
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    assert object_store.exists(f"uploads/{file_id}")

    deleted = client.delete(f"/v1/files/{file_id}")
    assert deleted.status_code == 204, deleted.text
    assert deleted.content == b""
    assert not object_store.exists(f"uploads/{file_id}")  # bytes gone now
    assert repository.get_upload(file_id) is None  # row gone

    record = client.get(f"/v1/conversions/{conversion_id}")
    assert record.status_code == 200, record.text
    assert record.json()["conversion_report"]["status"] == "completed"
    assert record.json()["validation_report"] is not None


def test_delete_unknown_file_is_404(client: TestClient) -> None:
    resp = client.delete("/v1/files/nope")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "FILE_NOT_FOUND"


# --- report-retention sweep ---------------------------------------------------------------------


def test_report_retention_sweep_deletes_records_past_the_window(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # report_retention_days is 7 in the test settings. A record created 10 days ago is swept — its
    # reports cascade away with it — while a fresh record survives.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    old = _seed_conversion(repository, object_store, created_at=utcnow() - timedelta(days=10))
    recent = _seed_conversion(repository, object_store, created_at=utcnow())

    swept = sweep_reports(repository, settings)
    assert swept == [old]
    assert repository.get_conversion(old) is None
    assert list(repository.get_reports_for_conversion(old)) == []  # reports cascaded away
    assert repository.get_conversion(recent) is not None
    assert client.get(f"/v1/conversions/{old}").status_code == 404
    assert client.get(f"/v1/conversions/{recent}").status_code == 200


def test_report_retention_indefinite_is_a_noop(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # None = indefinite retention (the self-hosted default): the sweep deletes nothing, however old.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    old = _seed_conversion(repository, object_store, created_at=utcnow() - timedelta(days=9999))

    swept = sweep_reports(repository, settings.model_copy(update={"report_retention_days": None}))
    assert swept == []
    assert repository.get_conversion(old) is not None


# --- reports-outlive-bytes (the integration promise) --------------------------------------------


def test_expired_output_410s_while_the_record_still_serves_both_reports(
    client: TestClient, repository: Repository
) -> None:
    # The M24 done-means: a file past its (test-shortened) lifecycle 410s on download, while its
    # conversion record still serves both reports.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(repository, object_store, expires_delta=timedelta(hours=-1))

    download = client.get(f"/v1/download/{conversion_id}")
    assert download.status_code == 410, download.text
    assert download.json()["error"]["code"] == "OUTPUT_EXPIRED"

    record = client.get(f"/v1/conversions/{conversion_id}")
    assert record.status_code == 200, record.text
    body = record.json()
    assert body["conversion_report"]["status"] == "completed"
    assert body["validation_report"] is not None
    assert body["download"]["available"] is False
