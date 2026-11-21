"""Hand-built two-atom frames for the structural-fidelity tests."""

from __future__ import annotations

import numpy as np
from pydantic import JsonValue

from xtalate.schema import AtomsBlock, Cell, Constraint, Dynamics, Frame
from xtalate.sdk.image_flags import IMAGE_FLAGS_CARRY_KEY


def frame_with(
    *,
    occupancies: list[float | None] | None = None,
    constraints: list[Constraint] | None = None,
    space_group: str | None = None,
    image_flags: np.ndarray | None = None,
) -> Frame:
    custom: dict[str, np.ndarray | list[JsonValue]] = {}
    if image_flags is not None:
        custom[IMAGE_FLAGS_CARRY_KEY] = np.asarray(image_flags, dtype=np.float64)
    return Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["H", "O"],
            positions=np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]),
            occupancies=occupancies,
        ),
        cell=Cell(lattice_vectors=np.eye(3) * 5.0, pbc=(True, True, True), space_group=space_group),
        dynamics=Dynamics(constraints=constraints),
        custom_per_atom=custom,
    )


def selective(mask: list[list[bool]]) -> list[Constraint]:
    return [Constraint(kind="selective_dynamics", atom_indices=[0, 1], parameters={"mask": mask})]


def fixed(indices: list[int]) -> list[Constraint]:
    return [Constraint(kind="fixed_atoms", atom_indices=indices, parameters={})]
