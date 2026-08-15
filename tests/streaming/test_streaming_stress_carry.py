"""The M44-S1 regression: a first-class-stress source streamed → extXYZ validates via the carry.

The VASP-output parsers (``outcar``/``vasprun``, M42/M43) map stress to the **first-class**
``electronic.stress`` field directly — their format declares the convention, so no
``ambiguous_stress_convention`` recovery is needed. Streamed to extXYZ, the re-parse holds the
stress under the parser's declared carry key (``extxyz:stress``), never the canonical field (D18),
so the streaming validator must find it there, reverse the exporter's declared output convention,
and compare — the D151 batch comparison, mirrored into ``validation.streaming`` (D168). Before the
fix the flagship ``convert OUTCAR --to extxyz --validation-report`` false-failed
``numeric_field_fidelity`` with stress ``missing: true`` and exited 3.

Pins three things: (1) the direct regression — the streamed conversion passes via the carry; (2)
the streamed==batch agreement (M12 standing rule 3) on the stress verdict — VASP is the first
source to exercise it; and (3) the teeth — a corrupted (wrong-sign) carry still fails, so the
check executes honestly rather than rubber-stamping a carried value.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.sdk.streaming import stream_of
from xtalate.validation import ToleranceProfile
from xtalate.validation.streaming import validate_stream

_GOLDEN = Path(__file__).parent.parent / "golden"
_VASP_SOURCES = [
    ("outcar", _GOLDEN / "outcar" / "relax-h2o" / "OUTCAR", "OUTCAR"),
    ("vasprun", _GOLDEN / "vasprun" / "relax-h2o" / "vasprun.xml", "vasprun.xml"),
]


@pytest.fixture(scope="module")
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


def _norm(v: Any) -> dict[str, Any]:
    """Per-run bookkeeping normalised away, per the standing-rule-3 comparison convention."""
    d: dict[str, Any] = v.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    d["conversion_report_id"] = "X"
    return d


def _numeric(report: Any) -> Any:
    return next(c for c in report.checks if c.check_id == "numeric_field_fidelity")


@pytest.mark.parametrize("format_id,path,filename", _VASP_SOURCES)
def test_first_class_stress_streamed_to_extxyz_validates_via_carry(
    engine: ConversionEngine, format_id: str, path: Path, filename: str
) -> None:
    """The bug's direct regression guard: a first-class ``electronic.stress`` VASP source streamed
    → extXYZ validates ``pass`` with the stress compared via the ``extxyz:stress`` carry — never a
    false ``missing``, no exit-3."""
    data = path.read_bytes()
    out = io.BytesIO()
    result = engine.convert_stream(
        io.BytesIO(data),
        source_format_id=format_id,
        target_format_id="extxyz",
        output=out,
        source_filename=filename,
    )
    assert result.report.status == "completed"
    assert result.validation is not None
    assert result.validation.status == "passed"

    numeric = _numeric(result.validation)
    assert numeric.status == "pass"
    measured = numeric.measured["electronic.stress"]
    assert isinstance(measured, dict)
    assert measured["missing"] is False
    assert measured["compared_via_carry"] is True
    assert measured["carry_key"] == "extxyz:stress"
    bound = ToleranceProfile.named("default").effective("stress").fail
    assert isinstance(measured["max_abs_diff"], (int, float))
    assert measured["max_abs_diff"] <= bound


@pytest.mark.parametrize("format_id,path,filename", _VASP_SOURCES)
def test_streamed_and_batch_stress_verdicts_agree(
    engine: ConversionEngine, format_id: str, path: Path, filename: str
) -> None:
    """The invariant VASP is the first source to exercise (M12 standing rule 3): the streaming and
    materialized validators produce the identical ``ValidationReport`` on the same first-class
    stress conversion — the carry comparison now agrees, where it previously diverged (streamed
    false-failed ``missing``, batch passed via the carry)."""
    registry = default_registry()
    data = path.read_bytes()
    src = registry.get_parser(format_id).parse(io.BytesIO(data), filename=filename).canonical

    batch = engine.convert(
        src, source_format_id=format_id, target_format_id="extxyz", source_filename=filename
    )
    out = io.BytesIO()
    streamed = engine.convert_stream(
        io.BytesIO(data),
        source_format_id=format_id,
        target_format_id="extxyz",
        output=out,
        source_filename=filename,
    )
    assert batch.validation is not None and streamed.validation is not None
    assert batch.validation.status == "passed"
    assert streamed.validation.status == "passed"
    # Substantive-content identity (per-run ids/timestamps normalised away), then the stress
    # verdict pinned explicitly so a regression on the carry flags is obvious in the failure.
    assert _norm(batch.validation) == _norm(streamed.validation)
    batch_stress = _numeric(batch.validation).measured["electronic.stress"]
    streamed_stress = _numeric(streamed.validation).measured["electronic.stress"]
    assert batch_stress == streamed_stress
    assert batch_stress["compared_via_carry"] is True
    assert batch_stress["carry_key"] == "extxyz:stress"


def test_corrupted_stress_carry_still_fails(engine: ConversionEngine) -> None:
    """The teeth: the fix executes the check honestly, it does not rubber-stamp a carried value.

    A wrong-sign stress carry (negated on write, the corruption the carry comparison exists to
    catch) still fails ``numeric_field_fidelity`` — the comparison reverses the declared convention
    and diffs for real, so a value that no longer matches the expected canonical tensor is a
    ``fail``, not a skip.
    """
    registry = default_registry()
    data = _VASP_SOURCES[0][1].read_bytes()
    src = registry.get_parser("outcar").parse(io.BytesIO(data), filename="OUTCAR").canonical
    conv = engine.convert(src, source_format_id="outcar", target_format_id="extxyz")
    assert conv.output is not None and conv.validation is not None
    assert conv.validation.status == "passed"

    # Re-parse the faithful output (stress now a Voigt-6 ``extxyz:stress`` carry), corrupt the
    # carry's sign, and re-export the corrupted object through the ordinary exporter.
    reparsed = registry.get_parser("extxyz").parse(io.BytesIO(conv.output), filename=None).canonical
    carry = reparsed.user_metadata.custom_per_frame["extxyz:stress"]
    reparsed.user_metadata.custom_per_frame["extxyz:stress"] = -np.asarray(carry, dtype=float)
    buf = io.BytesIO()
    registry.get_exporter("extxyz").export(reparsed, buf)

    tol = ToleranceProfile.named("default")
    streamed = validate_stream(
        registry,
        expected=stream_of(src),
        output_stream=io.BytesIO(buf.getvalue()),
        target_format_id="extxyz",
        conversion_report=conv.report,
        tolerance=tol,
        expected_schema_version=src.schema_version,
    )
    numeric = _numeric(streamed)
    assert numeric.status == "fail"
    measured = numeric.measured["electronic.stress"]
    assert isinstance(measured, dict)
    assert measured["missing"] is False
    assert measured["compared_via_carry"] is True  # the comparison ran — and rejected the value
    assert measured["carry_key"] == "extxyz:stress"
    assert isinstance(measured["max_abs_diff"], (int, float))
    assert measured["max_abs_diff"] > tol.effective("stress").fail
