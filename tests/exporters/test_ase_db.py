"""The `ase_db` exporter (v1.5 M55-S2): Canonical Object → one `.db` row, the exact inverse of
`parsers.ase_db`.

The exporter is the write half of the fourth ASE-wrap. Its behaviour mirrors `exporters.ase_traj`
(charges/moments to the per-atom `initial_*` arrays, energy/forces on a `SinglePointCalculator`,
dual-source stress under a declared sign convention), adapted for a single-row database and the
key-value/data restoration that `.db` alone carries. These tests drive the write side directly and
round-trip through the real parser; the two-hop matrix (`tests/roundtrip`) covers every
cross-format pair.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from xtalate.exporters.ase_db import make_ase_db_exporter
from xtalate.parsers._common import build_provenance
from xtalate.parsers.ase_db import make_ase_db_parser
from xtalate.schema import (
    CanonicalObject,
    Cell,
    Constraint,
    Frame,
    UserMetadata,
)
from xtalate.schema.models import AtomsBlock, Dynamics, Electronic

_STRESS_KEY = "ase_db:stress"
# A non-diagonal symmetric 3×3 in the canonical tension-positive convention — the same tensor the
# extXYZ / ase_traj stress tests carry, so the three formats' resolutions agree number-for-number.
_TENSOR = np.array([[1.0, 0.5, 0.25], [0.5, 2.0, 0.75], [0.25, 0.75, 3.0]], dtype=float)


def _frame(**overrides: object) -> Frame:
    base: dict[str, object] = dict(
        index=0,
        atoms=AtomsBlock(
            symbols=["C", "O"], positions=np.array([[0.0, 0.0, 0.0], [1.13, 0.0, 0.0]])
        ),
    )
    base.update(overrides)
    return Frame(**base)  # type: ignore[arg-type]


def _obj(frames: list[Frame], user_metadata: UserMetadata | None = None) -> CanonicalObject:
    return CanonicalObject(
        frames=frames,
        user_metadata=user_metadata or UserMetadata(),
        provenance=build_provenance(
            format_id="ase_db",
            filename="s.db",
            original_coordinate_system="cartesian",
            source_units={},
            parse_notes=[],
        ),
    )


def _export(obj: CanonicalObject) -> bytes:
    buffer = io.BytesIO()
    make_ase_db_exporter().export(obj, buffer)
    return buffer.getvalue()


def _reparse(data: bytes) -> CanonicalObject:
    canonical = make_ase_db_parser().parse(io.BytesIO(data), filename="s.db").canonical
    assert canonical is not None
    return canonical


# --- the single-structure invariant ---------------------------------------------------


def test_single_frame_exports_one_row() -> None:
    rp = _reparse(_export(_obj([_frame()])))
    assert len(rp.frames) == 1
    assert list(rp.frames[0].atoms.symbols) == ["C", "O"]


def test_multi_frame_refuses_pointing_at_frame_selection() -> None:
    # A .db written on the single-file path holds one structure (the M55 model's load-bearing
    # invariant); a trajectory must be reduced via frame_selection first, never fanned across rows.
    obj = _obj([_frame(index=0), _frame(index=1)])
    with pytest.raises(ValueError, match="one structure"):
        _export(obj)


# --- field round-trips (write side is the parser's inverse) ---------------------------


def test_charges_and_magmoms_ride_the_initial_arrays() -> None:
    # Not the calculator — the ase_traj rule: they enter and leave through initial_charges /
    # initial_magmoms, the same seam the parser reads.
    frame = _frame(
        electronic=Electronic(charges=np.array([0.3, -0.3]), magnetic_moments=np.array([0.0, 1.0]))
    )
    rp = _reparse(_export(_obj([frame])))
    assert rp.frames[0].electronic.charges is not None
    assert rp.frames[0].electronic.magnetic_moments is not None
    assert np.allclose(rp.frames[0].electronic.charges, [0.3, -0.3])
    assert np.allclose(rp.frames[0].electronic.magnetic_moments, [0.0, 1.0])


def test_energy_and_forces_round_trip_via_the_calculator() -> None:
    frame = _frame(
        electronic=Electronic(total_energy=-5.0),
        dynamics=Dynamics(forces=np.array([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]])),
    )
    rp = _reparse(_export(_obj([frame])))
    assert rp.frames[0].electronic.total_energy == pytest.approx(-5.0)
    assert rp.frames[0].dynamics.forces is not None
    assert np.allclose(rp.frames[0].dynamics.forces, [[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]])


def test_velocities_round_trip_through_the_unit_factor() -> None:
    frame = _frame(dynamics=Dynamics(velocities=np.array([[0.01, 0.0, 0.0], [0.0, 0.02, 0.0]])))
    rp = _reparse(_export(_obj([frame])))
    assert rp.frames[0].dynamics.velocities is not None
    assert np.allclose(rp.frames[0].dynamics.velocities, [[0.01, 0.0, 0.0], [0.0, 0.02, 0.0]])


def test_fixed_atoms_constraint_round_trips() -> None:
    frame = _frame(
        dynamics=Dynamics(constraints=[Constraint(kind="fixed_atoms", atom_indices=[0])])
    )
    rp = _reparse(_export(_obj([frame])))
    cons = rp.frames[0].dynamics.constraints
    assert cons is not None
    assert cons[0].kind == "fixed_atoms"
    assert list(cons[0].atom_indices) == [0]


def test_cell_and_pbc_round_trip() -> None:
    frame = _frame(cell=Cell(lattice_vectors=np.eye(3) * 6.0, pbc=(True, True, True)))
    rp = _reparse(_export(_obj([frame])))
    assert rp.frames[0].cell is not None
    assert np.allclose(rp.frames[0].cell.lattice_vectors, np.eye(3) * 6.0)
    assert rp.frames[0].cell.pbc == (True, True, True)


# --- key-value / data restoration (the inverse of the parser's carry) -----------------


def test_ase_db_namespaced_keys_restore_as_key_value_pairs_and_data() -> None:
    meta = UserMetadata(
        custom_global={"ase_db:label": "co-relaxed", "ase_db:data": {"note": [1, 2]}}
    )
    rp = _reparse(_export(_obj([_frame()], meta)))
    assert rp.user_metadata.custom_global["ase_db:label"] == "co-relaxed"
    assert rp.user_metadata.custom_global["ase_db:data"] == {"note": [1, 2]}


def test_foreign_namespace_key_is_not_written() -> None:
    # ASE forbids ':' in a key, so a foreign-namespace custom_global entry cannot be spelled as an
    # ASE key; the exporter drops it (the Conversion Engine reports it removed per the
    # writable_custom_key_pattern). The write itself must not fail on the unwritable key.
    meta = UserMetadata(custom_global={"poscar:comment": "from a POSCAR", "ase_db:tag": "keep"})
    rp = _reparse(_export(_obj([_frame()], meta)))
    assert rp.user_metadata.custom_global.get("ase_db:tag") == "keep"
    assert "poscar:comment" not in rp.user_metadata.custom_global


# --- dual-source stress (D163) --------------------------------------------------------


def test_populated_stress_writes_voigt6_and_reverses_the_sign() -> None:
    # A resolved electronic.stress is written negated (canonical tension-positive → ASE
    # compression-positive) and as Voigt-6, which a .db round-trips as (6,). The re-parse parks it
    # under ase_db:stress verbatim (D18); reversing the sign convention recovers the source tensor.
    frame = _frame(electronic=Electronic(stress=_TENSOR))
    rp = _reparse(_export(_obj([frame])))
    assert rp.frames[0].electronic.stress is None  # parser never maps stress on read
    carried = np.asarray(rp.user_metadata.custom_per_frame[_STRESS_KEY][0], dtype=float)
    assert carried.shape == (6,)
    full = np.asarray(voigt_6_to_full_3x3_stress(carried), dtype=float)
    assert np.allclose(-full, _TENSOR)  # undo the ase_sign_convention negation


def test_populated_stress_fires_the_sign_convention_warning() -> None:
    frame = _frame(electronic=Electronic(stress=_TENSOR))
    warnings = make_ase_db_exporter().export_warnings(_obj([frame]))
    assert [w.code for w in warnings] == ["STRESS_SIGN_CONVENTION_CHANGED"]


def test_opaque_stress_carry_passes_through_verbatim() -> None:
    # No populated field, only the legacy carry: written verbatim so an opaque .db→.db pass-through
    # round-trips the numbers exactly, and no sign-convention warning fires (nothing was reversed).
    voigt = np.array([1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
    meta = UserMetadata(custom_per_frame={_STRESS_KEY: np.array([voigt])})
    obj = _obj([_frame()], meta)
    assert make_ase_db_exporter().export_warnings(obj) == []
    rp = _reparse(_export(obj))
    carried = np.asarray(rp.user_metadata.custom_per_frame[_STRESS_KEY][0], dtype=float)
    assert np.allclose(carried, voigt)


def test_carry_dropped_warning_when_field_and_differing_carry_coexist() -> None:
    # A populated electronic.stress alongside a *differing* ase_db:stress carry: the field wins and
    # the carry's numbers are dropped — both warnings fire (the sign change and the drop).
    other = np.array([[9.0, 0.0, 0.0], [0.0, 9.0, 0.0], [0.0, 0.0, 9.0]])
    frame = _frame(electronic=Electronic(stress=_TENSOR))
    meta = UserMetadata(custom_per_frame={_STRESS_KEY: np.array([other])})
    warnings = make_ase_db_exporter().export_warnings(_obj([frame], meta))
    assert {w.code for w in warnings} == {
        "STRESS_SIGN_CONVENTION_CHANGED",
        "STRESS_CARRY_DROPPED",
    }


def test_length9_flattened_stress_carry_does_not_crash_export_warnings() -> None:
    # ASEDB-1 (review R4): ase.db itself flattens a full 3×3 calculator stress to a bare
    # length-9 array on write, so an externally produced .db can carry exactly that shape. It
    # cannot be judged against the written (3, 3) tensor — the drop-check must skip it, never
    # broadcast-crash (export_warnings runs unguarded from the conversion engine, so a raw
    # exception would abort the whole conversion). The sign-change warning still fires (the
    # field is populated); no STRESS_CARRY_DROPPED is claimed for an uncomparable carry.
    flat9 = np.arange(9, dtype=float) + 1.0
    frame = _frame(electronic=Electronic(stress=_TENSOR))
    meta = UserMetadata(custom_per_frame={_STRESS_KEY: np.array([flat9])})
    warnings = make_ase_db_exporter().export_warnings(_obj([frame], meta))
    assert [w.code for w in warnings] == ["STRESS_SIGN_CONVENTION_CHANGED"]


# --- capabilities ---------------------------------------------------------------------


def test_custom_global_declares_the_ase_db_namespace_pattern() -> None:
    caps = make_ase_db_exporter().capabilities()
    pattern = caps.writable_custom_key_pattern["user_metadata.custom_global"]
    import re

    assert re.fullmatch(pattern, "ase_db:label")
    assert not re.fullmatch(pattern, "poscar:comment")


def test_custom_per_frame_declares_only_the_stress_carry() -> None:
    caps = make_ase_db_exporter().capabilities()
    assert caps.writable_custom_keys["user_metadata.custom_per_frame"] == [_STRESS_KEY]


def test_capabilities_declare_write_direction_and_single_frame() -> None:
    caps = make_ase_db_exporter().capabilities()
    assert caps.direction == "write"
    assert caps.max_frames == 1
    assert caps.stress_output_convention == "ase_sign_convention"
