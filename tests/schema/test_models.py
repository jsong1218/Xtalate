"""Canonical Model construction and invariants (MASTER_SPEC Part 2 §2–§3)."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Frame,
    Provenance,
    UserMetadata,
)


def _provenance() -> Provenance:
    return Provenance(
        source_filename="t.xyz",
        source_format="xyz",
        original_coordinate_system="cartesian",
    )


def _atoms(n: int = 2) -> AtomsBlock:
    return AtomsBlock(
        symbols=["O"] + ["H"] * (n - 1),
        positions=np.array([[float(i), 0.0, 0.0] for i in range(n)]),
    )


def _obj(frames: list[Frame] | None = None) -> CanonicalObject:
    return CanonicalObject(
        frames=frames or [Frame(index=0, atoms=_atoms())],
        provenance=_provenance(),
    )


# --- construction & basics -----------------------------------------------------------


def test_minimal_object_constructs() -> None:
    obj = _obj()
    assert obj.schema_version == SCHEMA_VERSION == "0.1.0"
    assert obj.frame_count == 1
    assert obj.frames[0].cell is None  # absence, not identity lattice


def test_atomic_numbers_derived_from_symbols() -> None:
    a = _atoms(3)
    assert a.atomic_numbers == [8, 1, 1]


def test_frame_count_tracks_len_frames() -> None:
    obj = _obj([Frame(index=0, atoms=_atoms()), Frame(index=1, atoms=_atoms())])
    assert obj.frame_count == 2


# --- absence convention (§2) ---------------------------------------------------------


def test_zero_velocities_distinct_from_absent() -> None:
    at_rest = Dynamics(velocities=np.zeros((2, 3)))
    unstated = Dynamics()
    assert at_rest.velocities is not None
    assert unstated.velocities is None  # different scientific statements (§2 rule 3)


# --- validators ----------------------------------------------------------------------


def test_symbol_length_disagreement_rejected() -> None:
    with pytest.raises(ValidationError):
        # 2 symbols, 1 position
        AtomsBlock(symbols=["O", "H"], positions=np.array([[0.0, 0.0, 0.0]]))


def test_unknown_species_marker_allowed() -> None:
    a = AtomsBlock(symbols=["X"], positions=np.array([[0.0, 0.0, 0.0]]))
    assert a.atomic_numbers == [0]


def test_bogus_symbol_rejected() -> None:
    with pytest.raises(ValidationError):
        AtomsBlock(symbols=["Zz"], positions=np.array([[0.0, 0.0, 0.0]]))


def test_atomic_numbers_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        AtomsBlock(symbols=["O"], atomic_numbers=[1], positions=np.array([[0.0, 0.0, 0.0]]))


def test_constant_atom_count_enforced_across_frames() -> None:
    with pytest.raises(ValidationError):
        CanonicalObject(
            frames=[Frame(index=0, atoms=_atoms(2)), Frame(index=1, atoms=_atoms(3))],
            provenance=_provenance(),
        )


def test_frame_index_must_match_position() -> None:
    with pytest.raises(ValidationError):
        CanonicalObject(
            frames=[Frame(index=5, atoms=_atoms())],
            provenance=_provenance(),
        )


def test_empty_frames_rejected() -> None:
    with pytest.raises(ValidationError):
        CanonicalObject(frames=[], provenance=_provenance())


def test_cell_pbc_carried_as_declared() -> None:
    cell = Cell(lattice_vectors=np.eye(3) * 5.64, pbc=(True, True, True))
    obj = _obj([Frame(index=0, atoms=_atoms(), cell=cell)])
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.pbc == (True, True, True)


def test_custom_per_frame_numeric_becomes_ndarray() -> None:
    # D12: numeric per-frame input coerces to an ndarray (the extXYZ-column branch);
    # non-numeric input (strings) stays a list. left_to_right union picks the array first.
    obj = CanonicalObject(
        frames=[Frame(index=0, atoms=_atoms()), Frame(index=1, atoms=_atoms())],
        provenance=_provenance(),
        user_metadata=UserMetadata(
            custom_per_frame={
                "sim:temperature": np.array([300.0, 305.0]),
                "xyz:comment": ["a", "b"],
            }
        ),
    )
    assert isinstance(obj.user_metadata.custom_per_frame["sim:temperature"], np.ndarray)
    assert obj.user_metadata.custom_per_frame["xyz:comment"] == ["a", "b"]


def test_custom_per_frame_wrong_length_rejected() -> None:
    with pytest.raises(ValidationError):
        CanonicalObject(
            frames=[Frame(index=0, atoms=_atoms())],  # F == 1
            provenance=_provenance(),
            user_metadata=UserMetadata(custom_per_frame={"xyz:comment": ["a", "b"]}),  # len 2
        )


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            source_filename=None,
            source_format="xyz",
            original_coordinate_system="cartesian",
            bogus_key="oops",  # type: ignore[call-arg]
        )
