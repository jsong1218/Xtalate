"""Reports outlive bytes — enforced by FK direction, verified on both backends (v0.5 M21 slice 3).

The mission promise is that a Conversion Report remains retrievable after the file bytes it
describes are swept away (input-byte expiry and output-byte expiry run on shorter windows than
report retention). This is not application care — it is the schema: ``conversions.source_file_id``
is ``ON DELETE SET NULL``, and reports depend only on the conversion/job metadata rows, never on any
stored bytes. These tests delete the bytes-side rows and assert the reports survive intact.

The SQLite leg only enforces this because ``build_engine`` turns on ``PRAGMA foreign_keys`` — so a
regression that dropped that pragma would fail here, not pass quietly.
"""

from __future__ import annotations

from backend.db import Conversion, Job, Report, Repository, Upload

from .conftest import unique_id


def _seed_conversion_with_report(repository: Repository) -> tuple[str, str, str]:
    """Create upload → job → conversion → conversion-report; return their ids."""
    upload = Upload(
        file_id=unique_id("up"),
        sha256="b" * 64,
        size_bytes=100,
        storage_key="uploads/y/in.xyz",
    )
    job = Job(job_id=unique_id("job"), kind="convert", state="completed")
    repository.add_upload(upload)
    repository.add_job(job)

    conversion = Conversion(
        conversion_id=unique_id("conv"),
        job_id=job.job_id,
        source_file_id=upload.file_id,
        source_format="xyz",
        target_format="cif",
        output_storage_key="outputs/y/out.cif",
        output_available=True,
    )
    repository.add_conversion(conversion)

    report = Report(
        report_id=unique_id("rep"),
        job_id=job.job_id,
        conversion_id=conversion.conversion_id,
        kind="conversion",
        body={"status": "completed", "losses": []},
    )
    repository.add_report(report)
    return upload.file_id, conversion.conversion_id, report.report_id


def test_deleting_input_upload_nulls_fk_but_keeps_conversion_and_report(
    repository: Repository,
) -> None:
    file_id, conversion_id, report_id = _seed_conversion_with_report(repository)

    repository.delete_upload(file_id)  # input-byte expiry removes the upload row

    assert repository.get_upload(file_id) is None
    conversion = repository.get_conversion(conversion_id)
    assert conversion is not None  # survived
    assert conversion.source_file_id is None  # ON DELETE SET NULL fired
    assert conversion.target_format == "cif"  # metadata intact

    report = repository.get_report(report_id)
    assert report is not None
    assert report.body == {"status": "completed", "losses": []}  # verbatim, still there


def test_clearing_output_bytes_keeps_conversion_and_report(
    repository: Repository,
) -> None:
    _file_id, conversion_id, report_id = _seed_conversion_with_report(repository)

    cleared = repository.clear_output_bytes(conversion_id)  # output-byte expiry
    assert cleared is not None
    assert cleared.output_storage_key is None
    assert cleared.output_available is False

    # Re-read to confirm it persisted, and the report is untouched.
    conversion = repository.get_conversion(conversion_id)
    assert conversion is not None
    assert conversion.output_available is False
    assert repository.get_report(report_id) is not None


def test_marking_bytes_deleted_keeps_row_and_reports(repository: Repository) -> None:
    file_id, _conversion_id, report_id = _seed_conversion_with_report(repository)

    repository.mark_upload_bytes_deleted(file_id)

    upload = repository.get_upload(file_id)
    assert upload is not None  # row briefly retained
    assert upload.bytes_deleted is True
    assert repository.get_report(report_id) is not None


def test_deleting_job_cascades_to_conversion_and_reports(
    repository: Repository,
) -> None:
    """The other direction: deleting a *job* (account/retention delete) DOES cascade — that is the
    intended CASCADE, the counterpart to the SET NULL above."""
    _file_id, conversion_id, report_id = _seed_conversion_with_report(repository)
    conversion = repository.get_conversion(conversion_id)
    assert conversion is not None
    job_id = conversion.job_id

    repository.delete_upload(_file_id)  # detach the SET NULL side first is not needed; delete job
    with repository._session_factory.begin() as session:  # direct: no delete_job API until M24
        job = session.get(Job, job_id)
        assert job is not None
        session.delete(job)

    assert repository.get_conversion(conversion_id) is None  # CASCADE removed it
    assert repository.get_report(report_id) is None
