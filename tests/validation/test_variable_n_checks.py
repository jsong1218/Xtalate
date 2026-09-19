"""Per-frame-N validation checks (M73 / MASTER_SPEC Part 5 §2).

The checks compare frame-by-frame; a permutation map (from a species-grouping exporter) is
sized to one frame's N and must apply only to frames whose N matches its domain. A non-identity
map only legitimately arises for constant-N targets — which refuse variable-N at pre-flight — so
a length mismatch means "this frame is not the map's domain": fall back to identity, never crash.
"""

from __future__ import annotations

import numpy as np

from xtalate.schema import AtomsBlock, CanonicalObject, Frame, Provenance
from xtalate.validation.engine import (
    _check_numeric_fields,
    _check_positions_rmsd,
    _check_species,
)
from xtalate.validation.tolerance import ToleranceProfile


def _provenance() -> Provenance:
    return Provenance(
        source_filename="t.extxyz",
        source_format="extxyz",
        original_coordinate_system="cartesian",
    )


def _frame(index: int, symbols: list[str]) -> Frame:
    n = len(symbols)
    return Frame(
        index=index,
        atoms=AtomsBlock(
            symbols=symbols,
            positions=np.array([[float(i), 0.0, 0.0] for i in range(n)]),
        ),
    )


def _variable_n_object() -> CanonicalObject:
    # frame 0 = H2O (3 atoms), frame 1 = H2O2 (4 atoms): a genuine variable-N trajectory.
    return CanonicalObject(
        frames=[
            _frame(0, ["O", "H", "H"]),
            _frame(1, ["O", "O", "H", "H"]),
        ],
        provenance=_provenance(),
    )


def test_species_check_passes_on_variable_n_identity_perm() -> None:
    o = _variable_n_object()
    res = _check_species(o, o, None)
    assert res.status == "pass"


def test_species_check_perm_sized_to_frame0_does_not_crash_on_differing_frame() -> None:
    # A non-identity perm sized to frame 0 (len 3) must not index-error on frame 1 (len 4).
    o = _variable_n_object()
    res = _check_species(o, o, [0, 2, 1])
    assert res.status in {"pass", "fail"}  # never IndexError


def test_positions_rmsd_perm_sized_to_frame0_does_not_crash_on_differing_frame() -> None:
    o = _variable_n_object()
    res = _check_positions_rmsd(
        o, o, [0, 2, 1], ToleranceProfile.named("default"), {"atoms.positions": None}
    )
    assert res.status in {"pass", "warn", "fail"}  # never IndexError/shape crash


def test_numeric_fields_perm_sized_to_frame0_does_not_crash_on_differing_frame() -> None:
    # A per-atom numeric field (masses) of differing N per frame, with a frame0-sized perm.
    frames = [
        Frame(
            index=0,
            atoms=AtomsBlock(
                symbols=["O", "H", "H"],
                positions=np.zeros((3, 3)),
                masses=np.array([16.0, 1.0, 1.0]),
            ),
        ),
        Frame(
            index=1,
            atoms=AtomsBlock(
                symbols=["O", "O", "H", "H"],
                positions=np.zeros((4, 3)),
                masses=np.array([16.0, 16.0, 1.0, 1.0]),
            ),
        ),
    ]
    o = CanonicalObject(frames=frames, provenance=_provenance())
    res = _check_numeric_fields(
        o,
        o,
        [0, 2, 1],
        ToleranceProfile.named("default"),
        {},
        carried_field_keys={},
        stress_output_convention="none",
    )
    assert res.status in {"pass", "warn", "fail", "skipped"}  # never IndexError
