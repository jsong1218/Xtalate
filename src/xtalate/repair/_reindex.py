"""The shared per-atom reindex spine (v1.7 M65-S1; D252).

``reindex_per_atom`` is the **one place** that touches the atom axis of a Canonical
Object. The per-atom arrays are spread across **four** schema locations
(``AtomsBlock`` per frame, ``Dynamics`` per frame, ``Electronic`` per frame, and the
object-level ``UserMetadata.custom_per_atom`` — both the ndarray and the
``list[JsonValue]`` forms), and ``constraints[].atom_indices`` are per-atom
*references* rather than values. Species reorder (a permutation) and deduplicate (a
survivor selection) both reindex through this single helper, so a half-reindexed
object — positions belonging to one atom, velocities/forces/charges to another — is
impossible by construction (the silent corruption this milestone exists to prevent,
D252).

The helper is **pure and deterministic**: it takes a ``CanonicalObject`` and an index
sequence (output position *i* holds source atom ``sequence[i]``) and returns a new
object via ``model_copy``; the caller's object is never mutated. Every per-atom
array/reference follows the same sequence; every frame is reindexed identically; and
the object-level ``custom_per_atom`` is reindexed **once** (one reindex covers all
frames, because the map is frame-invariant by construction). A
``constraints[].atom_indices`` entry naming an index outside the sequence — a
*removed* atom under a constraint, under dedupe — is refused with a ``RepairError``
rather than silently dropped or reassigned: choosing which surviving atom inherits a
constraint is a scientific judgment the engine may not make (P4).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from xtalate.repair.contract import RepairError
from xtalate.schema import CanonicalObject, Constraint, Frame, UserMetadata


def _validated_sequence(sequence: Any, n: int, *, operation: str) -> list[int]:
    """Validate an index sequence (permutation or survivor selection) against N atoms.

    Both reorder (a full permutation of ``range(n)``) and dedupe (a strictly increasing
    survivor selection) are subsets of the same well-formed set: every index in
    ``[0, n)``, no duplicates. The operation-specific completeness rule (reorder must
    hit every atom) is enforced by the operation itself; here we only refuse an
    incoherent sequence.
    """
    if not isinstance(sequence, (list, tuple)):
        raise RepairError(
            f"{operation}: the reindex sequence must be a list of atom indices, got "
            f"{type(sequence).__name__}"
        )
    idx = [int(i) for i in sequence]
    seen: set[int] = set()
    for i in idx:
        if not 0 <= i < n:
            raise RepairError(f"{operation}: atom index {i} is out of range for an {n}-atom object")
        if i in seen:
            raise RepairError(
                f"{operation}: atom index {i} appears twice in the reindex sequence — a "
                "reindex must map each output position to a distinct source atom"
            )
        seen.add(i)
    return idx


def reindex_per_atom(
    obj: CanonicalObject,
    sequence: list[int],
    *,
    operation: str = "repair",
) -> CanonicalObject:
    """Reindex **every** per-atom array/reference of ``obj`` by ``sequence``.

    ``sequence[i]`` is the source atom written at output position *i*: for reorder a
    permutation of ``range(N)``; for dedupe a survivor selection. Applied identically
    to every frame (atom identity is frame-invariant, so a frame-invariant map is
    always well-defined — the constant-N invariant is trajectory-wide) and once to the
    object-level ``custom_per_atom`` (both the ndarray and ``list[JsonValue]`` forms).
    ``constraints[].atom_indices`` are remapped through the inverse of ``sequence``;
    a reference to an index the sequence does not contain raises ``RepairError``
    (the dedupe removed-atom-under-a-constraint refusal, surfaced here so the two
    operations can never drift on it).
    """
    n = obj.frames[0].atoms.positions.shape[0]
    idx = _validated_sequence(sequence, n, operation=operation)
    # Source index -> output index, for exactly the surviving source atoms.
    inverse = {old: new for new, old in enumerate(idx)}
    frames = [_reindex_frame(f, idx, inverse, operation=operation) for f in obj.frames]
    user_metadata = _reindex_user_metadata(obj.user_metadata, idx)
    return obj.model_copy(update={"frames": frames, "user_metadata": user_metadata})


def _reindex_frame(
    frame: Frame,
    idx: list[int],
    inverse: dict[int, int],
    *,
    operation: str,
) -> Frame:
    atoms = frame.atoms
    masses = None if atoms.masses is None else atoms.masses[idx]
    occupancies = None if atoms.occupancies is None else [atoms.occupancies[i] for i in idx]
    new_atoms = atoms.model_copy(
        update={
            "symbols": [atoms.symbols[i] for i in idx],
            "atomic_numbers": [atoms.atomic_numbers[i] for i in idx],
            "positions": atoms.positions[idx],
            "masses": masses,
            "occupancies": occupancies,
        }
    )

    dyn = frame.dynamics
    velocities = None if dyn.velocities is None else dyn.velocities[idx]
    forces = None if dyn.forces is None else dyn.forces[idx]
    constraints = None
    if dyn.constraints is not None:
        constraints = [
            _reindex_constraint(c, inverse, operation=operation) for c in dyn.constraints
        ]
    new_dynamics = dyn.model_copy(
        update={"velocities": velocities, "forces": forces, "constraints": constraints}
    )

    elec = frame.electronic
    new_electronic = elec.model_copy(
        update={
            "charges": None if elec.charges is None else elec.charges[idx],
            "magnetic_moments": (
                None if elec.magnetic_moments is None else elec.magnetic_moments[idx]
            ),
        }
    )

    return frame.model_copy(
        update={"atoms": new_atoms, "dynamics": new_dynamics, "electronic": new_electronic}
    )


def _reindex_constraint(
    constraint: Constraint, inverse: dict[int, int], *, operation: str
) -> Constraint:
    remapped: list[int] = []
    for old in constraint.atom_indices:
        try:
            remapped.append(inverse[old])
        except KeyError:
            raise RepairError(
                f"{operation}: atom {old} is referenced by the {constraint.kind!r} "
                "constraint but is removed by this reindex — refusing to drop the "
                "reference (or guess a surviving inheritor); choose a survivor set that "
                "keeps constrained atoms or drop the constraint first"
            ) from None
    return constraint.model_copy(update={"atom_indices": remapped})


def _reindex_user_metadata(um: UserMetadata, idx: list[int]) -> UserMetadata:
    """Reindex the object-level ``custom_per_atom`` (ndarray and list forms), once."""
    per_atom: dict[str, Any] = {}
    for key, val in um.custom_per_atom.items():
        if isinstance(val, np.ndarray):
            per_atom[key] = val[idx]
        else:  # list[JsonValue] — the §3.10 carry-through of per-atom free text.
            per_atom[key] = [val[i] for i in idx]
    return um.model_copy(update={"custom_per_atom": per_atom})
