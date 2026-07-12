"""POSCAR exporter tests: the element-grouping permutation map (Part 5 §2) and the
selective-dynamics constraint guard (Part 3 §4.2).

The permutation map is load-bearing for validation: POSCAR groups atoms by element, so the
Validation Engine must compare species/positions under the *same* grouping the exporter wrote.
An exporter that reordered atoms but reported the identity map would false-fail every
element-interleaved source as "chemistry lost".
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from xtalate.exporters.poscar import make_poscar_exporter
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Constraint,
    Dynamics,
    Frame,
)


def _object(symbols: list[str], *, constraints: list[Constraint] | None = None) -> CanonicalObject:
    n = len(symbols)
    positions = np.arange(n * 3, dtype=float).reshape(n, 3)
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=symbols, positions=positions),
                cell=Cell(lattice_vectors=np.eye(3) * 10.0, pbc=(True, True, True)),
                dynamics=Dynamics(constraints=constraints),
            )
        ],
        provenance=build_provenance(
            format_id="test", filename=None, original_coordinate_system="cartesian",
            source_units={}, parse_notes=[],
        ),
    )


def test_atom_permutation_reports_element_grouping() -> None:
    # Interleaved H O H → POSCAR groups to H H O, so output position 1 holds source atom 2.
    perm = make_poscar_exporter().atom_permutation(_object(["H", "O", "H"]))
    assert perm == [0, 2, 1]


def test_atom_permutation_none_when_already_grouped() -> None:
    # Source already contiguous by element → identity → None (no reorder to report).
    assert make_poscar_exporter().atom_permutation(_object(["H", "H", "O"])) is None


def test_export_groups_atoms_by_element() -> None:
    buf = io.BytesIO()
    make_poscar_exporter().export(_object(["H", "O", "H"]), buf)
    lines = buf.getvalue().decode().splitlines()
    assert lines[5].split() == ["H", "O"]  # species line, first-occurrence order
    assert lines[6].split() == ["2", "1"]  # counts grouped


def test_non_selective_constraint_raises_clear_error() -> None:
    obj = _object(["Si"], constraints=[Constraint(kind="fixed_atoms", atom_indices=[0])])
    with pytest.raises(ValueError, match="selective_dynamics"):
        make_poscar_exporter().export(obj, io.BytesIO())


def test_selective_dynamics_mask_wrong_length_raises() -> None:
    bad = [
        Constraint(
            kind="selective_dynamics",
            atom_indices=[0],
            parameters={"mask": [[True, True, True], [False, False, False]]},
        )
    ]
    obj = _object(["Si"], constraints=bad)  # 1 atom but a 2-row mask
    with pytest.raises(ValueError, match="mask has 2 rows"):
        make_poscar_exporter().export(obj, io.BytesIO())
