"""Chunk-aware validation (M12 deliverable 4) produces the *identical* ValidationReport as the batch
Validation Engine on the same input — the standing-rule-3 guarantee applied to Part 5. Covers the
pass path, a lossy target (absence/numeric branches), a frame-count mismatch (tail draining), and an
unparseable output (the reparse-fail contract)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from xtalate.conversion.engine import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry
from xtalate.sdk.streaming import stream_of
from xtalate.validation import ToleranceProfile, ValidationEngine
from xtalate.validation.streaming import validate_stream

_FRAME = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
    "H 0.0 1.0 0.0 0.0 0.0 0.3\n"
)


def _traj(n: int) -> bytes:
    return "".join(_FRAME.format(e=f"-1.{i}") for i in range(n)).encode()


def _norm(v: Any) -> dict[str, Any]:
    d: dict[str, Any] = v.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    d["conversion_report_id"] = "X"
    return d


@pytest.mark.parametrize("n", [1, 3, 6])
def test_streaming_validation_matches_batch_on_convert(n: int) -> None:
    eng = ConversionEngine(default_registry())
    data = _traj(n)
    src = ExtxyzParser().parse(io.BytesIO(data), filename="t.xyz").canonical
    batch = eng.convert(src, source_format_id="extxyz", target_format_id="extxyz")
    out = io.BytesIO()
    streamed = eng.convert_stream(
        io.BytesIO(data), source_format_id="extxyz", target_format_id="extxyz", output=out
    )
    assert streamed.validation is not None and batch.validation is not None
    assert _norm(streamed.validation) == _norm(batch.validation)


def _batch_vs_stream(
    expected_obj: Any, output_bytes: bytes, report: Any, registry: Any
) -> tuple[Any, Any]:
    tol = ToleranceProfile.named("default")
    batch = ValidationEngine(registry).validate(
        expected=expected_obj,
        output=output_bytes,
        target_format_id="extxyz",
        conversion_report=report,
        tolerance=tol,
    )
    streamed = validate_stream(
        registry,
        expected=stream_of(expected_obj),
        output_stream=io.BytesIO(output_bytes),
        target_format_id="extxyz",
        conversion_report=report,
        tolerance=tol,
        expected_schema_version=expected_obj.schema_version,
    )
    return batch, streamed


def test_streaming_validation_matches_batch_frame_count_mismatch() -> None:
    # Expected has 3 frames; the output carries only 2 — exercises the frame_count check and the
    # expected-tail draining (the batch check reads full counts; streaming must too).
    registry = default_registry()
    eng = ConversionEngine(registry)
    src3 = ExtxyzParser().parse(io.BytesIO(_traj(3)), filename="t.xyz").canonical
    res3 = eng.convert(src3, source_format_id="extxyz", target_format_id="extxyz")
    src2 = ExtxyzParser().parse(io.BytesIO(_traj(2)), filename="t.xyz").canonical
    out2 = eng.convert(src2, source_format_id="extxyz", target_format_id="extxyz").output
    assert out2 is not None

    batch, streamed = _batch_vs_stream(res3.canonical_out, out2, res3.report, registry)
    assert _norm(batch) == _norm(streamed)
    fc = next(c for c in streamed.checks if c.check_id == "frame_count")
    assert fc.status == "fail" and fc.measured == {"expected": 3, "found": 2}


def test_streaming_validation_matches_batch_extra_output_frames() -> None:
    # Output has *more* frames than expected — exercises actual-tail draining.
    registry = default_registry()
    eng = ConversionEngine(registry)
    src2 = ExtxyzParser().parse(io.BytesIO(_traj(2)), filename="t.xyz").canonical
    res2 = eng.convert(src2, source_format_id="extxyz", target_format_id="extxyz")
    out4 = eng.convert(
        ExtxyzParser().parse(io.BytesIO(_traj(4)), filename="t.xyz").canonical,
        source_format_id="extxyz",
        target_format_id="extxyz",
    ).output
    assert out4 is not None

    batch, streamed = _batch_vs_stream(res2.canonical_out, out4, res2.report, registry)
    assert _norm(batch) == _norm(streamed)


def test_streaming_validation_matches_batch_on_numeric_divergence() -> None:
    # Validate an expected object against an output built from a *perturbed* trajectory (shifted
    # positions + different forces/energy), so positions_rmsd and numeric_field_fidelity diverge —
    # exercising the fold fail/warn branches, which must still equal the batch verdict.
    registry = default_registry()
    eng = ConversionEngine(registry)
    src = ExtxyzParser().parse(io.BytesIO(_traj(3)), filename="t.xyz").canonical
    res = eng.convert(src, source_format_id="extxyz", target_format_id="extxyz")

    perturbed = _traj(3).replace(b"O 0.0 0.0 0.0 0.1 0.0 0.0", b"O 2.0 0.0 0.0 9.9 0.0 0.0")
    out = eng.convert(
        ExtxyzParser().parse(io.BytesIO(perturbed), filename="p.xyz").canonical,
        source_format_id="extxyz",
        target_format_id="extxyz",
    ).output
    assert out is not None

    batch, streamed = _batch_vs_stream(res.canonical_out, out, res.report, registry)
    assert _norm(batch) == _norm(streamed)
    assert streamed.status == "failed"
    pos = next(c for c in streamed.checks if c.check_id == "positions_rmsd")
    assert pos.status == "fail"


def test_streaming_validation_reparse_failure_is_a_fail() -> None:
    # An unparseable output yields a single failing `reparse` check in both paths (the message text
    # legitimately names whichever re-parser found it unreadable; the status is what must agree).
    registry = default_registry()
    eng = ConversionEngine(registry)
    src = ExtxyzParser().parse(io.BytesIO(_traj(2)), filename="t.xyz").canonical
    res = eng.convert(src, source_format_id="extxyz", target_format_id="extxyz")

    batch, streamed = _batch_vs_stream(
        res.canonical_out, b"not an extxyz file\n", res.report, registry
    )
    assert batch.status == "failed" and streamed.status == "failed"
    assert [c.check_id for c in streamed.checks] == ["reparse"]
    assert streamed.checks[0].status == "fail"
