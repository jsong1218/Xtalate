"""Ownership-boundary behavior in anonymous mode (MASTER_SPEC Part 6 §4; M25 integration suite).

v0.5 has no accounts and no per-user resources: authorization is **instance-level** (a configured
static key is valid or it is not), never **resource-level** (there is no owner column, so a job or
conversion is not "yours"). The security boundary is therefore the *unguessable id* — a
capability-URL model — not a per-caller filter. This test pins that down so a v0.6 accounts feature
that adds real ownership does so as a deliberate, visible change, and so no accidental scoping bug
(or leak) creeps in meanwhile:

* two distinct valid principals on one keyed instance both read the *same* record by id — there is
  no ownership filter that would hide one caller's conversion from another;
* the only thing standing between a caller and a record is knowing its id — an unknown id is a
  clean ``404``, not a permission error that would confirm the id exists.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, cast

from fastapi.testclient import TestClient

from backend.db.models import Conversion, Job, Report

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.db import Repository


def _seed_completed_conversion(repository: Repository) -> str:
    """Persist a minimal completed convert (job + conversion + report), returning its id."""
    job_id = uuid.uuid4().hex
    repository.add_job(Job(job_id=job_id, kind="convert", state="completed", request={}))
    conversion_id = f"cnv-{uuid.uuid4().hex}"
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job_id,
            source_format="xyz",
            target_format="xyz",
            output_available=False,  # bytes irrelevant here; the record is what we read back
            conversion_status="completed",
            validation_status="passed",
        )
    )
    repository.add_report(
        Report(
            report_id=uuid.uuid4().hex,
            job_id=job_id,
            conversion_id=conversion_id,
            kind="conversion",
            body={"report_id": uuid.uuid4().hex, "status": "completed"},
        )
    )
    return conversion_id


def test_distinct_keys_read_the_same_record_no_owner_scoping(
    build_client: Callable[..., TestClient],
) -> None:
    """Two valid keys are two principals but not two owners — both see the same conversion by id."""
    app = build_client(api_keys="key-a,key-b")
    repository = cast("Repository", app.app.state.repository)  # type: ignore[attr-defined]
    conversion_id = _seed_completed_conversion(repository)

    as_a = app.get(f"/v1/conversions/{conversion_id}", headers={"Authorization": "Bearer key-a"})
    as_b = app.get(f"/v1/conversions/{conversion_id}", headers={"Authorization": "Bearer key-b"})
    assert as_a.status_code == 200, as_a.text
    assert as_b.status_code == 200, as_b.text
    # Same record, byte-for-byte — there is no per-principal view of it.
    assert as_a.json() == as_b.json()


def test_unknown_id_is_a_clean_not_found_not_a_permission_error(client: TestClient) -> None:
    """The boundary is the id itself: an unknown id is ``404``, never ``401``/``403``."""
    resp = client.get(f"/v1/conversions/cnv-{uuid.uuid4().hex}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "CONVERSION_NOT_FOUND"
