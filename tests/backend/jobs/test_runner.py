"""The runner drives the library and lands every job in a persisted terminal state (Part 6 §3).

These are the done-means at the execution layer, independent of HTTP: inspect/convert complete and
persist verbatim reports; a refusal is a *completed* job (not failed); a lost precondition and an
in-run crash both land ``failed`` with a structured envelope — never a stuck ``running`` row.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.config import Settings  # noqa: E402
from backend.db import Repository  # noqa: E402
from backend.db.models import Job  # noqa: E402
from backend.jobs import runner  # noqa: E402
from backend.jobs.runner import execute_job  # noqa: E402
from backend.storage import ObjectStore  # noqa: E402
from xtalate.capabilities import Registry  # noqa: E402

from .conftest import POSCAR_SAMPLE, XYZ_SAMPLE  # noqa: E402


def _run(
    job_id: str,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
) -> None:
    execute_job(
        job_id,
        repository=repository,
        object_store=object_store,
        registry=registry,
        settings=settings,
    )


def _get_job(repository: Repository, job_id: str) -> Job:
    job = repository.get_job(job_id)
    assert job is not None
    return job


def test_inspect_completes_and_persists_a_discovery_report(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job("inspect", {"file_id": file_id, "request_id": "req-1"})

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "completed"
    assert job.started_at is not None and job.finished_at is not None
    reports = repository.get_reports_for_job(job_id)
    assert [r.kind for r in reports] == ["discovery"]
    assert reports[0].body["format"]["format_id"] == "xyz"


def test_convert_with_loss_completes_and_stores_output(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    file_id = make_upload(POSCAR_SAMPLE, "POSCAR")
    job_id = submit_job("convert", {"file_id": file_id, "target_format_id": "xyz", "options": {}})

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "completed"
    conversions = repository.get_reports_for_job(job_id)
    kinds = {r.kind for r in conversions}
    assert kinds == {"conversion", "validation"}
    # The conversion record carries a downloadable output and a completed (not refused) status.
    conv_report = next(r for r in conversions if r.kind == "conversion")
    assert conv_report.body["status"] == "completed"
    conv_id = conv_report.conversion_id
    assert conv_id is not None
    conversion = repository.get_conversion(conv_id)
    assert conversion is not None
    assert conversion.output_available is True
    assert conversion.output_storage_key is not None
    assert object_store.exists(conversion.output_storage_key)


def test_convert_refuses_when_recovery_needed_but_absent_is_a_completed_job(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    # XYZ → POSCAR needs a lattice; with no recovery preset the engine *refuses* — and a refusal is
    # a completed job (HTTP 200), never a failed one (Part 6 §1). This is the honesty-defining rule.
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job(
        "convert", {"file_id": file_id, "target_format_id": "poscar", "options": {}}
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "completed"  # completed, NOT failed
    assert job.error is None
    conv_report = next(r for r in repository.get_reports_for_job(job_id) if r.kind == "conversion")
    assert conv_report.body["status"] == "refused"
    assert conv_report.conversion_id is not None
    conversion = repository.get_conversion(conv_report.conversion_id)
    assert conversion is not None
    assert conversion.output_available is False  # a refusal produces no output


def test_convert_with_recovery_preset_completes(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job(
        "convert",
        {
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {
                "recovery_choices": {
                    "missing_lattice": {
                        "choice": "bounding_box",
                        "parameters": {"padding_ang": 5.0},
                    }
                }
            },
        },
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "completed"
    conv_report = next(r for r in repository.get_reports_for_job(job_id) if r.kind == "conversion")
    assert conv_report.body["status"] == "completed"
    # The fabricated lattice is reported as a supplied field — never silent (P1/P4).
    assert conv_report.body["supplied"]


def test_missing_upload_fails_from_queued(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    submit_job: Callable[..., str],
) -> None:
    job_id = submit_job(
        "convert", {"file_id": "does-not-exist", "target_format_id": "xyz", "options": {}}
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "failed"
    assert job.error is not None and job.error["code"] == "FILE_NOT_FOUND"
    assert job.started_at is None  # never entered running — the queued→failed edge


def test_parse_error_fails_with_parse_error_code(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    file_id = make_upload(b"this is not any chemistry format at all\n", "junk.xyz")
    job_id = submit_job(
        "convert", {"file_id": file_id, "target_format_id": "poscar", "options": {}}
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "failed"
    assert job.error is not None and job.error["code"] in {"PARSE_ERROR", "UNKNOWN_FORMAT"}


def test_crashed_worker_yields_failed_never_stuck_running(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a worker crashing mid-job: the dispatch raises after the job is already `running`.
    # The runner must land it `failed` with a structured envelope, never leave it stuck `running`.
    file_id = make_upload(POSCAR_SAMPLE, "POSCAR")
    job_id = submit_job("convert", {"file_id": file_id, "target_format_id": "xyz", "options": {}})

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("simulated worker crash mid-conversion")

    monkeypatch.setattr(runner, "_dispatch", _boom)

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "failed"
    assert job.error is not None
    assert job.error["code"] == "INTERNAL_ERROR"
    assert "simulated worker crash" not in job.error["message"]  # exception text never leaks
    assert job.finished_at is not None


def test_a_nonqueued_job_is_not_rerun(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job("inspect", {"file_id": file_id})
    repository.transition_job(job_id, "running")
    repository.transition_job(job_id, "completed")

    _run(job_id, repository, object_store, registry, settings)  # must be a no-op

    assert repository.get_reports_for_job(job_id) == []  # no discovery report produced


# A 3-atom structure with a lattice, uploaded as the *reference* an ``upload_reference`` recovery
# borrows from — its atom count matches XYZ_SAMPLE (3), the compatibility guard the engine requires.
REFERENCE_EXTXYZ = b"""3
Lattice="6.0 0.0 0.0 0.0 6.0 0.0 0.0 0.0 6.0" Properties=species:S:1:pos:R:3
O 0.0 0.0 0.0
H 0.1 0.1 0.0
H 0.2 0.1 0.0
"""


def test_convert_with_upload_reference_borrows_a_lattice_from_a_file_id(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    # The service half of the ``upload_reference`` contract (Part 4 §3.3): the client names a second
    # uploaded file by ``file_id``, and the worker resolves it into the parsed CanonicalObject the
    # Recovery Engine consumes. Before this fix the file_id string reached the engine unresolved and
    # the choice always failed — the option was advertised but unfulfillable over HTTP.
    ref_id = make_upload(REFERENCE_EXTXYZ, "ref.extxyz")
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job(
        "convert",
        {
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {
                "recovery_choices": {
                    "missing_lattice": {
                        "choice": "upload_reference",
                        "parameters": {"reference": ref_id},
                    }
                }
            },
        },
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "completed"
    conv_report = next(r for r in repository.get_reports_for_job(job_id) if r.kind == "conversion")
    assert conv_report.body["status"] == "completed"
    assert conv_report.body["supplied"]  # the borrowed lattice is a reported supplied field


def test_upload_reference_to_unknown_file_is_an_invalid_recovery_choice(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    # A reference naming a file that does not exist is a bad *choice* (the client pointed
    # ``upload_reference`` at nothing), not a server fault — INVALID_RECOVERY_CHOICE, not a 500.
    file_id = make_upload(XYZ_SAMPLE, "mol.xyz")
    job_id = submit_job(
        "convert",
        {
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {
                "recovery_choices": {
                    "missing_lattice": {
                        "choice": "upload_reference",
                        "parameters": {"reference": "no-such-file"},
                    }
                }
            },
        },
    )

    _run(job_id, repository, object_store, registry, settings)

    job = _get_job(repository, job_id)
    assert job.state == "failed"
    assert job.error is not None and job.error["code"] == "INVALID_RECOVERY_CHOICE"


def test_cancel_racing_a_running_job_discards_its_products(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A Tier 1 race: a client cancels a genuinely ``running`` job while the worker is mid-dispatch —
    # after it has already persisted a conversion, its reports, and the output bytes. The cancel
    # endpoint moved the row to terminal ``cancelled``; the worker must then *abandon* what it wrote
    # (no output file, no Conversion Report — Part 6 §3.2), never crash on the illegal
    # ``cancelled → completed`` edge and never leave the contradictory artifacts behind.
    from backend.db import utcnow

    file_id = make_upload(POSCAR_SAMPLE, "POSCAR")
    job_id = submit_job("convert", {"file_id": file_id, "target_format_id": "xyz", "options": {}})

    real_dispatch = runner._dispatch
    captured: dict[str, str | None] = {}

    def _dispatch_then_cancel(
        job: Job,
        upload: object,
        repo: Repository,
        store: ObjectStore,
        reg: Registry,
        sett: Settings,
    ) -> None:
        real_dispatch(job, upload, repo, store, reg, sett)  # persists conversion + reports + bytes
        conv_report = next(
            r for r in repo.get_reports_for_job(job.job_id) if r.kind == "conversion"
        )
        assert conv_report.conversion_id is not None
        conversion = repo.get_conversion(conv_report.conversion_id)
        assert conversion is not None
        captured["key"] = conversion.output_storage_key
        # ... and now a cancel races in, before the runner reaches its completion boundary.
        repo.transition_job(job.job_id, "cancelled", finished_at=utcnow(), clear_recovery=True)

    monkeypatch.setattr(runner, "_dispatch", _dispatch_then_cancel)

    _run(job_id, repository, object_store, registry, settings)  # must not raise

    job = _get_job(repository, job_id)
    assert job.state == "cancelled"  # the cancel stands; never overwritten to completed
    assert repository.get_reports_for_job(job_id) == []  # no Conversion Report survives
    assert captured["key"] is not None
    assert not object_store.exists(captured["key"])  # the output bytes were cleaned up
