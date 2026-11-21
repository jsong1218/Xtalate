"""``missing_lattice=non_periodic`` (D304).

The choice is offered only for a target that both *requires* a lattice and can *say* "not periodic"
(``allows_open_boundaries``): among the built-in exporters that is LAMMPS dump, whose
``ITEM: BOX BOUNDS`` line must carry numbers even when every boundary flag is ``f``. So the
resolver cannot leave the cell absent; it builds the same enclosing box ``bounding_box`` builds and
marks every axis non-periodic. The box is an enclosure the target must state, not a crystal
cell, and the report says so.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests.property import _properties
from xtalate.conversion import ConversionEngine
from xtalate.recovery import RecoveryEngine, RecoveryError, UnresolvedScenario
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

GOLDEN = Path(__file__).parent.parent / "golden"
_REGISTRY = default_registry()

_OPTIONS = ["manual_input", "upload_reference", "bounding_box", "non_periodic"]

# A planar molecule (every z = 0): with zero padding its box would have no thickness on z.
_PLANAR_XYZ = b"3\nplanar\nO 0.0 0.0 0.0\nH 0.96 0.0 0.0\nH -0.24 0.93 0.0\n"


def _parse(format_id: str, data: bytes, filename: str) -> CanonicalObject:
    return _REGISTRY.get_parser(format_id).parse(io.BytesIO(data), filename=filename).canonical


def _water() -> CanonicalObject:
    """A single-frame, cell-less molecule (the first frame of the water trajectory golden)."""
    obj = _parse("xyz", (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes(), "w.xyz")
    return obj.model_copy(update={"frames": [obj.frames[0]]})


def _scenario() -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="missing_lattice", path="cell.lattice_vectors", options=list(_OPTIONS)
    )


def _resolve(source: CanonicalObject, choice: str, padding: float) -> CanonicalObject:
    result = RecoveryEngine().resolve(
        source,
        [_scenario()],
        recovery_choices={
            "missing_lattice": {"choice": choice, "parameters": {"padding_ang": padding}}
        },
    )
    assert result.canonical is not None
    return result.canonical


def test_non_periodic_builds_the_bounding_box_geometry_with_open_boundaries() -> None:
    source = _water()
    boxed = _resolve(source, "bounding_box", 2.0)
    opened = _resolve(source, "non_periodic", 2.0)

    open_cell = opened.frames[0].cell
    box_cell = boxed.frames[0].cell
    assert open_cell is not None and box_cell is not None
    assert open_cell.pbc == (False, False, False)
    # Same enclosure, same rigid shift: only the periodicity claim differs.
    assert np.allclose(open_cell.lattice_vectors, box_cell.lattice_vectors)
    assert np.allclose(opened.frames[0].atoms.positions, boxed.frames[0].atoms.positions)


def test_non_periodic_records_both_supplied_fields_and_says_no_periodicity_is_claimed() -> None:
    result = RecoveryEngine().resolve(
        _water(),
        [_scenario()],
        recovery_choices={
            "missing_lattice": {"choice": "non_periodic", "parameters": {"padding_ang": 1.5}}
        },
    )
    (assumption,) = result.assumptions
    assert assumption.scenario == "missing_lattice"
    assert assumption.choice == "non_periodic"
    assert assumption.parameters["padding_ang"] == 1.5
    supplied = {s.path: s.detail for s in assumption.supplied}
    assert set(supplied) == {"cell.lattice_vectors", "cell.pbc"}
    assert "(F, F, F)" in (supplied["cell.pbc"] or "")
    text = assumption.description.lower()
    assert "non-periodic" in text
    assert "not a crystal cell" in text


def test_non_periodic_requires_a_non_negative_padding() -> None:
    with pytest.raises(RecoveryError, match="padding_ang"):
        RecoveryEngine().resolve(
            _water(),
            [_scenario()],
            recovery_choices={"missing_lattice": {"choice": "non_periodic", "parameters": {}}},
        )


@pytest.mark.parametrize("choice", ["bounding_box", "non_periodic"])
def test_a_box_with_no_thickness_is_refused_by_name(choice: str) -> None:
    """A planar molecule with zero padding would give a lattice with a zero-length side: no volume,
    no valid cell. The resolver refuses and names the axis rather than writing an unrealizable
    box."""
    planar = _parse("xyz", _PLANAR_XYZ, "planar.xyz")
    with pytest.raises(RecoveryError, match=r"padding_ang.*z"):
        _resolve(planar, choice, 0.0)


def test_xyz_to_lammps_dump_writes_open_boundary_flags_and_validates() -> None:
    source = _water()
    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id="xyz",
        target_format_id="lammps_dump",
        mode="permissive",
        recovery_choices={
            "missing_lattice": {"choice": "non_periodic", "parameters": {"padding_ang": 2.0}},
            "ambiguous_units": {"choice": "metal"},
        },
        tolerance_profile=ToleranceProfile.named("strict"),
    )
    report = result.report
    assert report.status == "completed", report.refusal
    assert result.output is not None
    text = result.output.decode() if isinstance(result.output, bytes) else str(result.output)
    assert "ITEM: BOX BOUNDS f f f" in text

    assert any(a.choice == "non_periodic" for a in report.assumptions)
    assert not _properties.completeness_violations(source, report)
    reparsed = _parse("lammps_dump", result.output, "dump.lammpstrj")
    assert reparsed.frames[0].cell is not None
    assert reparsed.frames[0].cell.pbc == (False, False, False)
    assert not _properties.absence_violations(report, reparsed)


def test_cli_offers_a_copyable_flag_for_non_periodic() -> None:
    from xtalate.cli.render import _recover_flag
    from xtalate.recovery.scenarios import describe_choice

    assert _recover_flag("missing_lattice", "non_periodic") == (
        "--recover missing_lattice=non_periodic,padding_ang=5.0"
    )
    assert "not yet available" not in describe_choice("missing_lattice", "non_periodic").lower()
