"""The job envelope projects the ORM row faithfully and embeds ``result`` verbatim (Part 6 §3.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.db.models import Job  # noqa: E402
from backend.jobs.envelope import JobEnvelope  # noqa: E402


def _job(**overrides: object) -> Job:
    base = dict(
        job_id="job-1",
        kind="convert",
        state="running",
        request={},
        created_at=datetime(2026, 7, 22, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 22, 10, 0, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return Job(**base)


def test_timestamps_render_as_iso_utc() -> None:
    env = JobEnvelope.from_row(_job())
    assert env.created_at == "2026-07-22T10:00:00+00:00"
    assert env.updated_at == "2026-07-22T10:00:01+00:00"
    assert env.started_at is None  # unset stays None, never a fabricated zero-time


def test_result_is_embedded_verbatim() -> None:
    # A convert result carries the report bodies unchanged — the M22 cut line's verbatim rule.
    result = {"conversion_id": "c-1", "conversion_report": {"status": "completed", "x": [1, 2]}}
    env = JobEnvelope.from_row(_job(state="completed"), result=result)
    assert env.result == result
    assert env.model_dump()["result"]["conversion_report"]["x"] == [1, 2]


def test_progress_defaults_to_empty_when_column_null() -> None:
    env = JobEnvelope.from_row(_job(progress=None))
    assert env.progress.phase is None
    assert env.progress.frames_processed is None


def test_progress_column_projects_into_envelope() -> None:
    env = JobEnvelope.from_row(
        _job(progress={"phase": "converting", "frames_processed": 3, "frames_total": 10})
    )
    assert env.progress.phase == "converting"
    assert env.progress.frames_processed == 3
    assert env.progress.frames_total == 10


def test_error_body_rides_through_for_failed_jobs() -> None:
    err = {"code": "PARSE_ERROR", "message": "bad file", "details": {}}
    env = JobEnvelope.from_row(_job(state="failed", error=err))
    assert env.error == err
