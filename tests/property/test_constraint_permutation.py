"""Property test: POSCAR's species grouping permutes selective-dynamics masks with the atoms."""

from __future__ import annotations

import io

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from xtalate.exporters.poscar import make_poscar_exporter
from xtalate.parsers._common import build_provenance
from xtalate.parsers.poscar import make_poscar_parser
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Constraint, Dynamics, Frame

_SYMBOLS = st.lists(st.sampled_from(["H", "O", "C"]), min_size=2, max_size=9)


def _masked_object(symbols: list[str], mask: list[list[bool]]) -> CanonicalObject:
    n = len(symbols)
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=symbols,
                    positions=np.arange(3 * n, dtype=np.float64).reshape(n, 3) * 0.1,
                ),
                cell=Cell(lattice_vectors=np.eye(3) * 10.0, pbc=(True, True, True)),
                dynamics=Dynamics(
                    constraints=[
                        Constraint(
                            kind="selective_dynamics",
                            atom_indices=list(range(n)),
                            parameters={"mask": mask},
                        )
                    ]
                ),
            )
        ],
        provenance=build_provenance(
            format_id="test",
            filename=None,
            original_coordinate_system="cartesian",
            source_units={},
            parse_notes=[],
        ),
    )


@st.composite
def _case(draw: st.DrawFn) -> tuple[list[str], list[list[bool]]]:
    symbols = draw(_SYMBOLS)
    mask = [[draw(st.booleans()) for _ in range(3)] for _ in symbols]
    return symbols, mask


@given(case=_case())
def test_mask_follows_the_atom_permutation(case: tuple[list[str], list[list[bool]]]) -> None:
    symbols, mask = case
    obj = _masked_object(symbols, mask)
    exporter = make_poscar_exporter()
    perm = exporter.atom_permutation(obj) or list(range(len(symbols)))
    buf = io.BytesIO()
    exporter.export(obj, buf)
    buf.seek(0)
    constraints = (
        make_poscar_parser().parse(buf, filename="POSCAR").canonical.frames[0].dynamics.constraints
    )
    if all(all(row) for row in mask):
        # An all-True mask is "present but unconstrained": the parser reports [] (not None).
        assert constraints == []
        return
    assert constraints is not None and len(constraints) == 1
    parsed = constraints[0].parameters["mask"]
    # Output position i holds source atom perm[i] (the validation convention), so its mask row must
    # be the source atom's row.
    for i in range(len(symbols)):
        assert list(parsed[i]) == list(mask[perm[i]])
