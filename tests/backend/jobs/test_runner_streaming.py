"""E1: eligible conversions stream (one frame resident) and everything else is unchanged.

The invariant is the engine's own standing rule 3 lifted to the service: the streamed and the
materialized runs produce the *same* reports and the *same* bytes; a pause, a refusal or a parse
failure behaves exactly as before because every unusual outcome falls back to the materialized path.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.config import Settings  # noqa: E402
from backend.db import Repository  # noqa: E402
from backend.jobs import runner  # noqa: E402
from backend.jobs.runner import execute_job  # noqa: E402
from backend.storage import ObjectStore  # noqa: E402
from xtalate.capabilities import Registry  # noqa: E402
from xtalate.conversion import ConversionEngine  # noqa: E402
from xtalate.sdk import ParseError, ParseIssue  # noqa: E402

from .conftest import XYZ_SAMPLE  # noqa: E402

_VOLATILE = {"report_id", "conversion_report_id", "created_at"}


def _extxyz(n_frames: int, n_atoms: int = 3, *, break_last: bool = False) -> bytes:
    parts: list[str] = []
    for f in range(n_frames):
        parts.append(
            f'{n_atoms}\nLattice="5 0 0 0 5 0 0 0 5" Properties=species:S:1:pos:R:3 pbc="T T T"\n'
        )
        rows = n_atoms - 1 if (break_last and f == n_frames - 1) else n_atoms
        for a in range(rows):
            parts.append(f"H {a * 0.5 + f * 0.01:.4f} 0.1 0.2\n")
    return "".join(parts).encode()


# A single-frame extXYZ carrying a stress channel: converting it to extXYZ needs the
# ``ambiguous_stress_convention`` recovery choice, a *data-dependent* refusal discovered only after
# the frames are streamed (M40-S2), so it exercises the streamed-refusal fallback for real.
_STRESS_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0.5 0.25 0.5 2 0.75 0.25 0.75 3" pbc="T T T"\nH 0 0 0\n'
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class _Calls:
    def __init__(self) -> None:
        self.stream = 0
        self.materialized = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    counts = _Calls()
    real_stream = ConversionEngine.convert_stream
    real_convert = ConversionEngine.convert

    def _stream(self: ConversionEngine, *a: Any, **k: Any) -> Any:
        counts.stream += 1
        return real_stream(self, *a, **k)

    def _convert(self: ConversionEngine, *a: Any, **k: Any) -> Any:
        counts.materialized += 1
        return real_convert(self, *a, **k)

    monkeypatch.setattr(ConversionEngine, "convert_stream", _stream)
    monkeypatch.setattr(ConversionEngine, "convert", _convert)
    return counts


def _run(
    request: dict[str, Any],
    content: bytes,
    filename: str,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> str:
    file_id = make_upload(content, filename)
    job_id = submit_job("convert", {"file_id": file_id, **request})
    execute_job(
        job_id,
        repository=repository,
        object_store=object_store,
        registry=registry,
        settings=settings,
    )
    return job_id


def _outcome(job_id: str, repository: Repository, object_store: ObjectStore) -> dict[str, Any]:
    job = repository.get_job(job_id)
    assert job is not None
    reports = [(r.kind, _scrub(r.body)) for r in repository.get_reports_for_job(job_id)]
    conv_bytes: bytes | None = None
    conv_status: str | None = None
    for report in repository.get_reports_for_job(job_id):
        if report.conversion_id:
            conv = repository.get_conversion(report.conversion_id)
            assert conv is not None
            conv_status = conv.conversion_status
            if conv.output_storage_key and conv.output_available:
                with object_store.open(conv.output_storage_key) as chunks:
                    conv_bytes = b"".join(chunks)
            break
    return {
        "state": job.state,
        "error": job.error,
        "reports": reports,
        "bytes": conv_bytes,
        "conversion_status": conv_status,
    }


def _both_ways(
    monkeypatch: pytest.MonkeyPatch,
    request: dict[str, Any],
    content: bytes,
    filename: str,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    args = (repository, object_store, registry, settings, make_upload, submit_job)
    streamed = _outcome(_run(request, content, filename, *args), repository, object_store)
    with monkeypatch.context() as m:
        m.setattr(runner, "_try_convert_streamed", lambda *a, **k: None)
        forced = _outcome(_run(request, content, filename, *args), repository, object_store)
    return streamed, forced


def test_eligible_conversion_streams_and_never_materializes(
    calls: _Calls,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    job_id = _run(
        {"target_format_id": "extxyz", "options": {}},
        XYZ_SAMPLE,
        "mol.xyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert calls.stream == 1
    assert calls.materialized == 0
    out = _outcome(job_id, repository, object_store)
    assert out["state"] == "completed"
    assert out["bytes"] is not None and out["bytes"].startswith(b"3\n")


@pytest.mark.parametrize(
    ("content", "filename", "target"),
    [
        (XYZ_SAMPLE, "mol.xyz", "extxyz"),
        (_extxyz(5), "traj.extxyz", "extxyz"),
        (_extxyz(4, 6), "traj.extxyz", "extxyz"),
    ],
    ids=["xyz->extxyz", "extxyz-5f->extxyz", "extxyz-4f6a->extxyz"],
)
def test_streamed_and_materialized_runs_agree_on_reports_and_bytes(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    filename: str,
    target: str,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    streamed, forced = _both_ways(
        monkeypatch,
        {"target_format_id": target, "options": {}},
        content,
        filename,
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert streamed["state"] == forced["state"] == "completed"
    assert streamed["bytes"] == forced["bytes"]
    assert streamed["conversion_status"] == forced["conversion_status"]
    # If this fails on a key other than a freshly generated id/timestamp, STOP: the streamed path
    # is changing a report and the finding must be reported, not scrubbed away (P1).
    assert streamed["reports"] == forced["reports"]


def test_an_ineligible_pair_uses_the_materialized_path(
    calls: _Calls,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    _run(
        {"target_format_id": "cif", "options": {}},
        XYZ_SAMPLE,
        "mol.xyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert calls.stream == 0
    assert calls.materialized == 1


@pytest.mark.parametrize(
    "options",
    [{"mode": "strict"}, {"recovery_choices": {"missing_masses": {"choice": "iupac"}}}],
    ids=["strict-mode", "recovery-choices"],
)
def test_gated_requests_never_attempt_the_stream(
    options: dict[str, Any],
    calls: _Calls,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    _run(
        {"target_format_id": "extxyz", "options": options},
        XYZ_SAMPLE,
        "mol.xyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert calls.stream == 0


def test_engine_value_error_falls_back_to_the_materialized_path(
    monkeypatch: pytest.MonkeyPatch,
    calls: _Calls,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    def _boom(self: ConversionEngine, *a: Any, **k: Any) -> Any:
        raise ValueError("runtime exclusion: use convert()")

    monkeypatch.setattr(ConversionEngine, "convert_stream", _boom)
    job_id = _run(
        {"target_format_id": "extxyz", "options": {}},
        XYZ_SAMPLE,
        "mol.xyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert calls.materialized == 1
    assert _outcome(job_id, repository, object_store)["state"] == "completed"


def test_mid_stream_parse_error_gives_the_same_failed_job_as_the_materialized_path(
    monkeypatch: pytest.MonkeyPatch,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    streamed, forced = _both_ways(
        monkeypatch,
        {"target_format_id": "extxyz", "options": {}},
        _extxyz(3, break_last=True),
        "bad.extxyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert forced["state"] == "failed"
    assert streamed["state"] == "failed"
    assert streamed["error"]["code"] == forced["error"]["code"]
    assert streamed["error"]["message"] == forced["error"]["message"]
    assert streamed["error"]["details"] == forced["error"]["details"]


def test_data_dependent_refusal_pauses_exactly_like_the_materialized_path(
    monkeypatch: pytest.MonkeyPatch,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    req = {"target_format_id": "extxyz", "options": {"allow_recovery": True}}
    streamed, forced = _both_ways(
        monkeypatch,
        req,
        _STRESS_EXTXYZ,
        "s.extxyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert forced["state"] == "awaiting_recovery"
    assert streamed["state"] == "awaiting_recovery"


def test_data_dependent_refusal_without_allow_recovery_is_a_completed_refusal(
    monkeypatch: pytest.MonkeyPatch,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    streamed, forced = _both_ways(
        monkeypatch,
        {"target_format_id": "extxyz", "options": {}},
        _STRESS_EXTXYZ,
        "s.extxyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert streamed["state"] == forced["state"] == "completed"
    assert streamed["conversion_status"] == forced["conversion_status"] == "refused"
    assert streamed["bytes"] is None and forced["bytes"] is None
    assert streamed["reports"] == forced["reports"]


def test_over_cap_trajectory_fails_with_frame_limit_exceeded(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    capped = settings.model_copy(update={"max_frames": 2})
    job_id = _run(
        {"target_format_id": "extxyz", "options": {}},
        _extxyz(5),
        "big.extxyz",
        repository,
        object_store,
        registry,
        capped,
        make_upload,
        submit_job,
    )
    out = _outcome(job_id, repository, object_store)
    assert out["state"] == "failed"
    assert out["error"]["code"] == "FRAME_LIMIT_EXCEEDED"
    assert out["error"]["details"]["max_frames"] == 2
    # the partial streamed output was never persisted
    assert out["bytes"] is None


def test_no_spool_or_output_temp_files_are_left_behind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    for target, content in (("extxyz", _extxyz(3)), ("cif", XYZ_SAMPLE)):
        _run(
            {"target_format_id": target, "options": {}},
            content,
            "f.xyz" if target == "cif" else "f.extxyz",
            repository,
            object_store,
            registry,
            settings,
            make_upload,
            submit_job,
        )
    assert list(scratch.iterdir()) == []


def test_read_bytes_round_trips_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, object_store: ObjectStore
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    payload = b"x" * (3 * 1024 * 1024 + 17)
    object_store.put("k", [payload[:1000], payload[1000:]])
    assert runner._read_bytes(object_store, "k") == payload
    assert list(scratch.iterdir()) == []


def test_a_parse_error_raised_by_the_stream_is_a_fallback_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
    calls: _Calls,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    make_upload: Callable[..., str],
    submit_job: Callable[..., str],
) -> None:
    def _bad(self: ConversionEngine, *a: Any, **k: Any) -> Any:
        raise ParseError([ParseIssue(severity="error", code="X", message="synthetic")])

    monkeypatch.setattr(ConversionEngine, "convert_stream", _bad)
    job_id = _run(
        {"target_format_id": "extxyz", "options": {}},
        XYZ_SAMPLE,
        "mol.xyz",
        repository,
        object_store,
        registry,
        settings,
        make_upload,
        submit_job,
    )
    assert calls.materialized == 1
    assert _outcome(job_id, repository, object_store)["state"] == "completed"
