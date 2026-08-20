"""Write-side value-level representability refusals (v1.3 M47-S3, D179; Part 4 §1, §4).

A LAMMPS dump holds a lattice *and* velocities, so the Capability Matrix — which reasons at field
granularity — predicts no loss for either. But a dump can state only *some* values of those fields:

* **Geometry.** Only the *restricted* triclinic form (upper-triangle zeros: edge **a** along x,
  **b** in the xy-plane). A general-triclinic cell would need a rotation to write — a silent change
  to the trajectory's frame of reference Xtalate refuses to make (D43).
* **Mixed-presence velocities.** A dump's per-atom column layout must be identical across every
  snapshot, so it cannot carry ``vx vy vz`` on only some frames. Velocities present on some frames
  and absent on others is a legitimate canonical state (the presence model calls it ``mixed``);
  writing it would demand either per-frame-varying columns (output the parser rejects) or a
  fabricated rest state for the gap frames (forbidden, P3/P1).

Both are value-level facts the Capability diff cannot see, so the engine consults the exporter's
additive ``unrepresentable`` hook (D179) right before writing and turns a returned reason into a
clean ``UNREPRESENTABLE_VALUE`` refused report — a completed HTTP-200 outcome, never an export-time
crash (P1). The companion is the *restricted* cell (with uniform velocities) that writes cleanly:
same pipeline, same units preset, but representable values, so the conversion completes. The trio
pins that the gate refuses exactly the unrepresentable values and nothing else.
"""

from __future__ import annotations

import io

import numpy as np

from xtalate.conversion import ConversionEngine
from xtalate.parsers.poscar import make_poscar_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

# A general-triclinic POSCAR: the first lattice vector carries a y-component (a = (4, 1, 0)), so the
# cell is NOT in LAMMPS's restricted triclinic form (lattice[0, 1] != 0). POSCAR stores the vectors
# verbatim, so the non-restricted geometry survives parsing to the Canonical Object unchanged.
_GENERAL_TRICLINIC = b"""tilted
1.0
  4.0  1.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
Si O
1 1
Cartesian
  0.0 0.0 0.0
  2.0 2.0 2.0
"""

# The same cell straightened into restricted form (a along x): representable, so it writes cleanly.
_RESTRICTED = b"""orthorhombic
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
Si O
1 1
Cartesian
  0.0 0.0 0.0
  2.0 2.0 2.0
"""

_METAL = {"ambiguous_units": {"choice": "metal", "parameters": {}}}

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)


def _source(poscar: bytes) -> CanonicalObject:
    return make_poscar_parser().parse(io.BytesIO(poscar), filename=None).canonical


def test_general_triclinic_cell_refuses_with_unrepresentable_geometry() -> None:
    source = _source(_GENERAL_TRICLINIC)
    # The source really is non-restricted — otherwise the refusal proves nothing.
    assert source.frames[0].cell is not None
    lattice = np.asarray(source.frames[0].cell.lattice_vectors, dtype=float)
    assert not np.allclose(lattice[0, 1], 0.0)

    result = _ENGINE.convert(
        source,
        source_format_id="poscar",
        target_format_id="lammps_dump",
        recovery_choices=_METAL,  # units are resolved, so the geometry gate is what fires
    )
    # A refusal is a completed job, not an error, and it writes no bytes (Part 4 §4; P1).
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "UNREPRESENTABLE_VALUE"
    assert "restricted triclinic" in result.report.refusal["message"]
    # The refused report still carries the pre-flight prediction (completeness holds over it).
    assert result.report.preserved or result.report.removed


def test_restricted_cell_writes_cleanly() -> None:
    result = _ENGINE.convert(
        _source(_RESTRICTED),
        source_format_id="poscar",
        target_format_id="lammps_dump",
        recovery_choices=_METAL,
    )
    assert result.report.status == "completed"
    assert result.output is not None
    assert b"ITEM: UNITS\nmetal" in result.output


# Two identical orthorhombic frames, neither declaring a momenta column — so the extXYZ parser
# leaves velocities absent on both (it populates them only from a momenta column). The test then
# gives ONLY the first frame velocities, manufacturing the mixed-presence state a real trajectory
# reaches when some snapshots carried velocities and others did not.
_TWO_ORTHO_FRAMES = b"""2
Lattice="4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0" Properties=species:S:1:pos:R:3 pbc="T T T"
Si 0.0 0.0 0.0
O 2.0 2.0 2.0
2
Lattice="4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0" Properties=species:S:1:pos:R:3 pbc="T T T"
Si 0.0 0.0 0.0
O 2.0 2.0 2.0
"""


def test_mixed_presence_velocities_refuses_with_unrepresentable_value() -> None:
    parsed = _REGISTRY.get_parser("extxyz").parse(io.BytesIO(_TWO_ORTHO_FRAMES), filename=None)
    source = parsed.canonical
    # Give ONLY the first frame velocities → the field is `mixed`, a legitimate canonical state a
    # dump's constant per-atom column layout cannot carry. Both cells are restricted, so the
    # geometry gate passes and the velocity gate is unambiguously what fires.
    source.frames[0].dynamics.velocities = np.array([[0.1, 0.0, 0.0], [0.0, 0.1, 0.0]])
    assert source.frames[0].dynamics.velocities is not None
    assert source.frames[1].dynamics.velocities is None

    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id="lammps_dump",
        recovery_choices=_METAL,
    )
    # Refused (P1): a completed job that writes no bytes, never a mid-write crash or a mangled dump.
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "UNREPRESENTABLE_VALUE"
    assert "constant per-atom column layout" in result.report.refusal["message"]
