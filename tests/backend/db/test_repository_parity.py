"""The repository behaves identically on both backends (v0.5 M21 slice 3).

Every test here runs twice — once on SQLite (Tier 0) and once on PostgreSQL (Tier 1, when
configured) — through the parametrized ``repository`` fixture. Two backends behind one interface,
proven by one suite (Part 9 §1.1).
"""

from __future__ import annotations

from backend.db import Conversion, Job, Report, Repository, Upload

from .conftest import unique_id


def _make_upload(**over: object) -> Upload:
    kwargs: dict[str, object] = {
        "file_id": unique_id("up"),
        "sha256": "a" * 64,
        "size_bytes": 42,
        "storage_key": "uploads/x/data.xyz",
    }
    kwargs.update(over)
    return Upload(**kwargs)


def _make_job(**over: object) -> Job:
    kwargs: dict[str, object] = {
        "job_id": unique_id("job"),
        "kind": "convert",
        "state": "queued",
    }
    kwargs.update(over)
    return Job(**kwargs)


def test_upload_round_trips(repository: Repository) -> None:
    upload = _make_upload()
    repository.add_upload(upload)

    fetched = repository.get_upload(upload.file_id)
    assert fetched is not None
    assert fetched.sha256 == "a" * 64
    assert fetched.size_bytes == 42
    assert fetched.bytes_deleted is False
    # created_at was defaulted app-side (not left NULL), timezone-aware.
    assert fetched.created_at is not None


def test_get_missing_returns_none(repository: Repository) -> None:
    assert repository.get_upload("does-not-exist") is None
    assert repository.get_job("does-not-exist") is None
    assert repository.get_conversion("does-not-exist") is None
    assert repository.get_report("does-not-exist") is None


def test_job_request_json_round_trips_verbatim(repository: Repository) -> None:
    body = {"target_format": "cif", "options": {"nested": [1, 2, 3]}, "flag": True}
    job = _make_job(request=body)
    repository.add_job(job)

    fetched = repository.get_job(job.job_id)
    assert fetched is not None
    assert fetched.request == body  # no reshaping — stored and served verbatim


def test_conversion_and_reports_round_trip(repository: Repository) -> None:
    upload = _make_upload()
    job = _make_job()
    repository.add_upload(upload)
    repository.add_job(job)

    conversion = Conversion(
        conversion_id=unique_id("conv"),
        job_id=job.job_id,
        source_file_id=upload.file_id,
        source_format="xyz",
        target_format="cif",
        output_storage_key="outputs/x/out.cif",
        output_available=True,
    )
    repository.add_conversion(conversion)

    disc = Report(
        report_id=unique_id("rep"),
        job_id=job.job_id,
        conversion_id=None,
        kind="discovery",
        body={"present": ["positions"]},
    )
    conv_report = Report(
        report_id=unique_id("rep"),
        job_id=job.job_id,
        conversion_id=conversion.conversion_id,
        kind="conversion",
        body={"status": "completed"},
    )
    repository.add_report(disc)
    repository.add_report(conv_report)

    for_conv = repository.get_reports_for_conversion(conversion.conversion_id)
    assert [r.report_id for r in for_conv] == [conv_report.report_id]

    for_job = repository.get_reports_for_job(job.job_id)
    assert {r.report_id for r in for_job} == {disc.report_id, conv_report.report_id}
