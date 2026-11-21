"""Site occupancies survive an engine conversion to an occupancy-capable target (C1, D303).

Pre-existing since M35: the engine's write-plan filter (``_filter_frame``) rebuilt each frame's
``AtomsBlock`` without ``atoms.occupancies``, so CIF -> CIF dropped the ``_atom_site_occupancy``
column while the Conversion Report listed the field under ``preserved`` and validation passed (the
expected object had lost the field too). This pins the end-to-end flow: the column is written, the
re-read keeps the P3 split between a known partial site and an unknown (``?``) one, and the
``structural_fidelity`` check is emitted and passes; a tampered output fails it.

The streamed path cannot reach this with a real occupancy-capable route: CIF is the only target that
writes the field, and it declares ``max_frames=1`` (and does not stream), so
``streaming_eligible`` routes it through the materialized ``convert``. ``_filter_stream_frame``
delegates to the same ``_filter_frame``, so the filter-level test below covers the streamed filter.
"""

from __future__ import annotations

import io

import numpy as np

from xtalate.conversion import ConversionEngine
from xtalate.conversion.engine import ConversionResult, _filter_frame
from xtalate.registry import default_registry
from xtalate.schema import AtomsBlock, CanonicalObject, Frame
from xtalate.validation.engine import ValidationEngine
from xtalate.validation.report import CheckResult
from xtalate.validation.tolerance import ToleranceProfile

_REGISTRY = default_registry()
_OCC = "atoms.occupancies"

_CIF = """data_occupancy_roundtrip
_cell_length_a     4.0
_cell_length_b     4.0
_cell_length_c     4.0
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma  90.0
_space_group_name_H-M_alt 'P 1'
loop_
_space_group_symop_operation_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1  Na  0.0   0.0   0.0   0.5
Cl1  Cl  0.5   0.5   0.5   ?
K1   K   0.25  0.25  0.25  1.0
"""


def _parse_cif(data: bytes) -> CanonicalObject:
    return _REGISTRY.get_parser("cif").parse(io.BytesIO(data), filename="case.cif").canonical


def _convert() -> tuple[CanonicalObject, ConversionResult]:
    source = _parse_cif(_CIF.encode())
    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id="cif",
        target_format_id="cif",
        source_filename="case.cif",
        target_filename="out.cif",
    )
    return source, result


def _structural(checks: list[CheckResult]) -> CheckResult | None:
    return next((c for c in checks if c.check_id == "structural_fidelity"), None)


def test_cif_to_cif_writes_and_preserves_partial_and_unknown_occupancies() -> None:
    source, result = _convert()
    assert source.frames[0].atoms.occupancies == [0.5, None, 1.0]
    assert result.report.status == "completed"
    assert _OCC in {e.path for e in result.report.preserved}
    assert _OCC not in {e.path for e in result.report.removed}

    output = result.output
    assert output is not None
    assert b"_atom_site_occupancy" in output
    reread = _parse_cif(output)
    assert reread.frames[0].atoms.occupancies == [0.5, None, 1.0]

    # The expected object handed to validation carries the field, so the check actually runs.
    expected = result.canonical_out
    assert expected is not None
    assert expected.frames[0].atoms.occupancies == [0.5, None, 1.0]
    validation = result.validation
    assert validation is not None
    check = _structural(validation.checks)
    assert check is not None, "structural_fidelity must be emitted when occupancies are carried"
    assert check.status == "pass"
    # The re-read of a file that now really carries partial sites warns about them, exactly as the
    # source parse did (CIF_PARTIAL_OCCUPANCY) — the output is faithful, so nothing fails.
    assert validation.status == "passed_with_warnings"
    assert [i.code for i in validation.reparse_issues] == ["CIF_PARTIAL_OCCUPANCY"]


def test_tampered_occupancy_column_fails_structural_fidelity() -> None:
    _, result = _convert()
    output = result.output
    assert output is not None and result.canonical_out is not None
    # Turn the known 0.5 site into a full one: an unreported drift the check must catch.
    lines = output.decode().splitlines()
    na_row = next(i for i, line in enumerate(lines) if line.split()[:1] == ["Na1"])
    fields = lines[na_row].split()
    assert float(fields[-1]) == 0.5
    fields[-1] = "1.0"
    lines[na_row] = "  ".join(fields)
    tampered = ("\n".join(lines) + "\n").encode()
    assert _parse_cif(tampered).frames[0].atoms.occupancies == [1.0, None, 1.0]

    validation = ValidationEngine(_REGISTRY).validate(
        expected=result.canonical_out,
        output=tampered,
        target_format_id="cif",
        conversion_report=result.report,
        tolerance=ToleranceProfile.named("default"),
    )
    check = _structural(validation.checks)
    assert check is not None
    assert check.status == "fail"
    assert _OCC in check.paths


def test_filter_frame_keeps_occupancies_only_when_planned() -> None:
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["Na", "Cl"],
            positions=np.zeros((2, 3)),
            occupancies=[0.5, None],
        ),
    )
    assert _filter_frame(frame, {"atoms.occupancies"}).atoms.occupancies == [0.5, None]
    assert _filter_frame(frame, set()).atoms.occupancies is None
