"""LAMMPS dump exporter tests (v1.3 M47-S1; Part 4 §1).

Pins the write side's "ordinary axes": the ``ITEM:``-block shape, the element column plus
the deterministically generated type map (reported as the audit-line export warning), the
velocities-only-when-present contract (P3), the orthogonal and triclinic boxes written back
exactly, the unit-style header from the resolved ``ambiguous_units`` choice (with an honest
refusal when no style is resolved — the exporter never guesses), and the small round-trip
through the M46 parser. The full-scale identity round-trip and the image-flag symmetry are
M47-S3 / M47-S2.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_scientifically_equal
from xtalate.exporters.lammps_dump import (
    _TYPES_ASSIGNED,
    _UNITS_KEY,
    LammpsDumpExporter,
    make_lammps_dump_exporter,
)
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.schema import CanonicalObject
from xtalate.sdk import ParseResult

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_dump"
EXPORTER = make_lammps_dump_exporter()

# The source dumps carry their declared style and their step numbers; the exporter needs the
# *resolved* style on the object, which in the engine the ambiguous_units recovery places
# under custom_global['lammps_dump:units']. These helpers simulate that resolution so the
# exporter is exercised directly (SDK-level, as the plan's reconciliation 3 permits).
_METAL = "metal-ortho-declared"
_TRICLINIC = "real-triclinic-scaled"


def parse_dump_case(case: str) -> ParseResult:
    """Parse one element-labeled golden source plainly (the two cases these tests use are both
    element-labeled; the typed goldens are exercised via the M46 parser suite)."""
    src = (GOLDEN / case / "dump.lammpstrj").read_bytes()
    return make_lammps_dump_parser().parse(io.BytesIO(src), filename=None)


def _resolved(case: str = _METAL) -> CanonicalObject:
    obj = parse_dump_case(case).canonical
    style = obj.user_metadata.custom_global[_UNITS_KEY]
    return obj.model_copy(
        update={
            "user_metadata": obj.user_metadata.model_copy(
                update={"custom_global": {**obj.user_metadata.custom_global, _UNITS_KEY: style}}
            )
        }
    )


def _export(obj: CanonicalObject) -> bytes:
    buf = io.BytesIO()
    EXPORTER.export(obj, buf)
    return buf.getvalue()


def _reparse(data: bytes) -> CanonicalObject:
    return make_lammps_dump_parser().parse(io.BytesIO(data), filename=None).canonical


def test_export_requires_a_resolved_unit_style() -> None:
    """Without the resolved style the exporter refuses loudly — the write-side analogue of the
    parse-side ``ambiguous_units`` refusal, so a dump with a guessed unit basis cannot exit
    Xtalate (the engine refuses before the exporter is reached; this guards direct SDK use)."""
    obj = parse_dump_case(_METAL).canonical
    obj = obj.model_copy(
        update={"user_metadata": obj.user_metadata.model_copy(update={"custom_global": {}})}
    )
    with pytest.raises(ValueError, match="ambiguous_units"):
        EXPORTER.export(obj, io.BytesIO())


def test_export_writes_units_header_and_roundtrips_declared_style() -> None:
    out = _export(_resolved()).decode()
    assert "ITEM: UNITS\nmetal" in out
    reparsed = _reparse(_export(_resolved()))
    assert reparsed.user_metadata.custom_global == {"lammps_dump:units": "metal"}


def test_export_writes_element_column_and_type_column() -> None:
    out = _export(_resolved()).decode()
    header = next(line for line in out.splitlines() if line.startswith("ITEM: ATOMS"))
    assert "element" in header.split()
    assert "type" in header.split()
    # First-appearance order: the metal-ortho fixture is Si, O → type 1 = Si, type 2 = O.
    first_atom = [line for line in out.splitlines() if not line.startswith("ITEM")][-2]
    tokens = first_atom.split()
    assert tokens[1] == "Si"
    assert tokens[2] == "1"


def test_type_map_is_reported_as_the_audit_line() -> None:
    warnings = EXPORTER.export_warnings(_resolved())
    assert [w.code for w in warnings] == [_TYPES_ASSIGNED]
    assert "type 1 → Si" in warnings[0].message
    assert "type 2 → O" in warnings[0].message


def test_velocities_written_only_when_present() -> None:
    # The triclinic fixture declares xs/ys/zs only — no velocity block, so none is written
    # (P3: absence is information; a zero-filled vx vy vz would assert a rest state the
    # source never claimed).
    obj = _resolved(_TRICLINIC)
    out = _export(obj).decode()
    assert "vx" not in out
    # Give the object velocities: the columns appear, unit-converted to the style's basis.
    n = len(obj.frames[0].atoms.symbols)
    obj = obj.model_copy(
        update={
            "frames": [
                frame.model_copy(
                    update={
                        "dynamics": frame.dynamics.model_copy(
                            update={"velocities": np.ones((n, 3), dtype=float)}
                        )
                    }
                )
                for frame in obj.frames
            ]
        }
    )
    out2 = _export(obj).decode()
    assert "vx vy vz" in out2
    reparsed = _reparse(_export(obj))
    assert reparsed.frames[0].dynamics.velocities is not None
    np.testing.assert_allclose(reparsed.frames[0].dynamics.velocities, np.ones((n, 3)))


def test_orthogonal_box_written_back_exactly() -> None:
    obj = _resolved(_METAL)
    assert obj.frames[0].cell is not None
    reparsed = _reparse(_export(obj))
    assert reparsed.frames[0].cell is not None
    np.testing.assert_allclose(
        reparsed.frames[0].cell.lattice_vectors, obj.frames[0].cell.lattice_vectors
    )


def test_triclinic_box_written_back_exactly() -> None:
    obj = _resolved(_TRICLINIC)
    # The restricted triclinic form (a=(20,0,0), b=(5,10,0), c=(3,2,10)) round-trips through
    # the bounding-box inversion exactly.
    out = _export(obj).decode()
    assert "ITEM: BOX BOUNDS xy xz yz p p p" in out
    reparsed = _reparse(_export(obj))
    assert reparsed.frames[0].cell is not None
    np.testing.assert_allclose(
        reparsed.frames[0].cell.lattice_vectors,
        [[20.0, 0.0, 0.0], [5.0, 10.0, 0.0], [3.0, 2.0, 10.0]],
    )


def test_general_non_restricted_lattice_is_refused_not_rotated() -> None:
    """A lattice outside LAMMPS's restricted triclinic form is refused loudly — rotating it
    would silently change the trajectory's frame of reference (D43, the D177 cut line)."""
    obj = _resolved(_METAL)
    frame = obj.frames[0]
    assert frame.cell is not None
    lattice = np.asarray(frame.cell.lattice_vectors, dtype=float).copy()
    lattice[0, 1] = 2.0  # a=(lx, 2, 0) — not expressible in restricted form
    obj = obj.model_copy(
        update={
            "frames": [
                frame.model_copy(
                    update={"cell": frame.cell.model_copy(update={"lattice_vectors": lattice})}
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="restricted triclinic"):
        EXPORTER.export(obj, io.BytesIO())


def test_small_roundtrip_reproduces_scientific_content() -> None:
    """dump → canonical → dump: the M46 parser reads the written dump back to the same
    scientific content. The one intentional addition is the writer's own ``type`` column (the
    generated type map), which the re-parse carries as ``lammps_dump:type`` — excluded below,
    since the source dump never had it (its element column was the identity)."""
    obj = _resolved(_METAL)
    reparsed = _reparse(_export(obj))
    left = obj.model_copy(
        update={
            "user_metadata": obj.user_metadata.model_copy(
                update={
                    "custom_per_atom": {
                        k: v
                        for k, v in obj.user_metadata.custom_per_atom.items()
                        if k != "lammps_dump:type"
                    }
                }
            )
        }
    )
    right = reparsed.model_copy(
        update={
            "user_metadata": reparsed.user_metadata.model_copy(
                update={
                    "custom_per_atom": {
                        k: v
                        for k, v in reparsed.user_metadata.custom_per_atom.items()
                        if k != "lammps_dump:type"
                    }
                }
            )
        }
    )
    assert_scientifically_equal(left, right)


def test_image_flags_are_written_back_with_the_coordinate_convention() -> None:
    obj = _resolved("wrapped-flags-metal")
    out = _export(obj).decode()
    atoms_header = next(line for line in out.splitlines() if line.startswith("ITEM: ATOMS"))
    assert "x y z ix iy iz" in atoms_header
    rows = out.split(atoms_header, 1)[1].strip().splitlines()
    assert rows[0].split()[-3:] == ["0", "0", "0"]
    assert rows[1].split()[-3:] == ["1", "0", "0"]
    reparsed = _reparse(_export(obj))
    np.testing.assert_array_equal(
        reparsed.user_metadata.custom_per_atom["lammps_dump:image_flags"],
        obj.user_metadata.custom_per_atom["lammps_dump:image_flags"],
    )


def test_image_flags_are_absent_never_zero_filled() -> None:
    out = _export(_resolved(_METAL)).decode()
    atoms_header = next(line for line in out.splitlines() if line.startswith("ITEM: ATOMS"))
    assert all(name not in atoms_header.split() for name in ("ix", "iy", "iz"))
    assert all(" ix " not in line for line in out.splitlines())


@pytest.mark.parametrize(
    ("case", "coordinate_header"),
    [
        ("wrapped-flags-metal", "x y z"),
        ("xu-counterpart-metal", "xu yu zu"),
        (_TRICLINIC, "xs ys zs"),
    ],
)
def test_coordinate_convention_is_preserved(case: str, coordinate_header: str) -> None:
    out = _export(_resolved(case)).decode()
    atoms_header = next(line for line in out.splitlines() if line.startswith("ITEM: ATOMS"))
    assert coordinate_header in atoms_header


def test_wrapped_flags_roundtrip_reconstructs_unwrapped_positions_in_test() -> None:
    wrapped = _resolved("wrapped-flags-metal")
    reparsed = _reparse(_export(wrapped))
    xu = _resolved("xu-counterpart-metal")
    flags = np.asarray(reparsed.user_metadata.custom_per_atom["lammps_dump:image_flags"])
    cell = reparsed.frames[0].cell
    assert cell is not None
    reconstructed = reparsed.frames[0].atoms.positions + flags * np.diag(cell.lattice_vectors)
    np.testing.assert_allclose(reconstructed, xu.frames[0].atoms.positions)


@pytest.mark.parametrize("direction", ["read", "write"])
def test_registered_as_full_axis(direction: str) -> None:
    from xtalate.registry import default_registry

    registry = default_registry()
    plugin = (
        registry.get_parser("lammps_dump")
        if direction == "read"
        else registry.get_exporter("lammps_dump")
    )
    assert plugin is not None
    assert isinstance(plugin, LammpsDumpExporter) or direction == "read"
