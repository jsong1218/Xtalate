"""``GET /v1/download/{conversion_id}`` — streaming, the ack gate, and byte expiry (M24 slice 2).

One test drives the real path end to end (upload → convert → download round-trips the output bytes
through object storage); the rest seed a conversion record directly so the failed-validation ack
gate and the three expiry conditions can be exercised in isolation, without contriving a genuinely
failing validation. The download surface reads only the conversion record and the stored bytes, so a
seeded record is a faithful stand-in for one a real convert wrote.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from backend.db import utcnow
from backend.db.models import Conversion, Job

if TYPE_CHECKING:
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


def _seed_conversion(
    repository: Repository,
    object_store: ObjectStore,
    *,
    body: bytes = b"OUTPUT-BYTES\n",
    validation_status: str | None = "passed",
    output_available: bool = True,
    put_bytes: bool = True,
    expires_delta: timedelta | None = timedelta(hours=1),
    output_filename: str | None = None,
) -> str:
    """Persist a job + conversion (and optionally its output bytes) with full control of the fields
    the download surface branches on — validation status, availability, and the expiry horizon."""
    job_id = uuid.uuid4().hex
    options = {"output_filename": output_filename} if output_filename else {}
    repository.add_job(
        Job(
            job_id=job_id,
            kind="convert",
            state="completed",
            request={"options": options},
            finished_at=utcnow(),
        )
    )
    conversion_id = f"cnv-{uuid.uuid4().hex}"
    key = f"outputs/{conversion_id}"
    if put_bytes:
        object_store.put(key, [body])
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job_id,
            target_format="xyz",
            output_storage_key=key if output_available else None,
            output_available=output_available,
            output_expires_at=(utcnow() + expires_delta) if expires_delta is not None else None,
            conversion_status="completed",
            validation_status=validation_status,
        )
    )
    return conversion_id


def test_download_round_trips_the_converted_output(
    client: TestClient, repository: Repository
) -> None:
    # The real path: convert XYZ → xyz, then download the output and get back exactly the bytes the
    # engine stored — streamed through the API, under a Content-Disposition naming the output file.
    file_id = _upload(client, XYZ_SAMPLE, "water.xyz")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}).json()
    assert env["state"] == "completed", env
    conversion_id = env["result"]["conversion_id"]

    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    with object_store.open(f"outputs/{conversion_id}") as chunks:
        expected = b"".join(chunks)

    resp = client.get(f"/v1/download/{conversion_id}")
    assert resp.status_code == 200, resp.text
    assert resp.content == expected
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert 'filename="output.xyz"' in disposition


def test_download_unknown_conversion_is_404(client: TestClient) -> None:
    resp = client.get("/v1/download/cnv-does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "CONVERSION_NOT_FOUND"


def test_download_requires_ack_when_validation_failed(
    client: TestClient, repository: Repository
) -> None:
    # A failed-validation output is gated: without acknowledgment it is a 409, never a silent stream
    # of bytes the service could not verify.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(repository, object_store, validation_status="failed")

    blocked = client.get(f"/v1/download/{conversion_id}")
    assert blocked.status_code == 409, blocked.text
    error = blocked.json()["error"]
    assert error["code"] == "VALIDATION_ACK_REQUIRED"
    assert error["details"]["validation_status"] == "failed"


def test_download_with_acknowledgment_streams_the_failed_validation_output(
    client: TestClient, repository: Repository
) -> None:
    # The same failed-validation output downloads once the client explicitly acknowledges it.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(
        repository, object_store, body=b"UNVERIFIED\n", validation_status="failed"
    )

    resp = client.get(
        f"/v1/download/{conversion_id}", params={"acknowledge_validation_failure": "true"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == b"UNVERIFIED\n"


def test_download_past_the_expiry_horizon_is_410(
    client: TestClient, repository: Repository
) -> None:
    # Bytes still on disk but the record's expiry horizon has passed: the lazy expiry check refuses
    # the download (410) even where no lifecycle sweep has run — the Tier 0 / pre-flag-update case.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(repository, object_store, expires_delta=timedelta(hours=-1))

    resp = client.get(f"/v1/download/{conversion_id}")
    assert resp.status_code == 410, resp.text
    assert resp.json()["error"]["code"] == "OUTPUT_EXPIRED"


def test_download_when_bytes_are_gone_is_410(client: TestClient, repository: Repository) -> None:
    # The Tier 1 bucket-lifecycle case: the record still says available and unexpired, but the
    # object itself is absent — caught at open() and rendered as a clean 410, not a mid-stream 500.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(repository, object_store, put_bytes=False)

    resp = client.get(f"/v1/download/{conversion_id}")
    assert resp.status_code == 410, resp.text
    assert resp.json()["error"]["code"] == "OUTPUT_EXPIRED"


def test_download_honours_a_custom_output_filename(
    client: TestClient, repository: Repository
) -> None:
    # The Content-Disposition offers the request's output_filename, matching what the job result's
    # download.filename advertised.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_conversion(repository, object_store, output_filename="my structure.xyz")

    resp = client.get(f"/v1/download/{conversion_id}")
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert 'filename="my structure.xyz"' in disposition
    assert "filename*=UTF-8''my%20structure.xyz" in disposition
