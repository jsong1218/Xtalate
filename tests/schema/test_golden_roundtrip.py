"""Golden round-trip of the Part 2 §8.1 / §8.2 worked examples (M1 done-criterion).

Equality is *deserialize-then-compare* (DECISIONS.md D8): the serialized JSON is parsed
back to values and compared structurally, never compared as text. The committed fixtures
are the canonical serialization of the two worked examples — with the §6.1 carry-through
keys corrected (POSCAR title in ``custom_global['poscar:comment']``; XYZ comments in
``custom_per_frame['xyz:comment']``).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from chembridge.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden" / "schema"
CASES = ["xyz_2frame_3atom.json", "poscar_nacl.json"]


@pytest.mark.parametrize("name", CASES)
def test_load_dump_roundtrip_is_faithful(name: str) -> None:
    text = (GOLDEN / name).read_text()
    expected = json.loads(text)
    obj = CanonicalObject.model_validate_json(text)
    produced = json.loads(obj.model_dump_json())
    assert produced == expected  # deserialize-then-compare, never text compare (D8)


def test_xyz_values_and_presence() -> None:
    obj = CanonicalObject.model_validate_json((GOLDEN / "xyz_2frame_3atom.json").read_text())
    assert obj.frame_count == 2  # rendered projection; not a stored field (§3.5)
    assert obj.frames[0].cell is None  # absence, not an identity lattice (§2 rule 2)
    assert np.array_equal(obj.frames[1].atoms.positions[:, 2], [0.01, 0.01, 0.01])
    # XYZ comment lines survive verbatim as a length-F string list (§6.1).
    assert obj.user_metadata.custom_per_frame["xyz:comment"] == ["frame 0", "frame 1"]

    pm = obj.field_presence()
    assert pm.status_of("atoms.symbols") == "present"
    assert pm.status_of("atoms.positions") == "present"
    assert pm.status_of("cell.lattice_vectors") == "absent"
    assert pm.status_of("dynamics.velocities") == "absent"
    assert pm.status_of("electronic.total_energy") == "absent"
    assert "user_metadata.custom_per_frame['xyz:comment']" in pm.present_paths()


def test_poscar_values_and_presence() -> None:
    obj = CanonicalObject.model_validate_json((GOLDEN / "poscar_nacl.json").read_text())
    assert obj.frame_count == 1
    assert obj.trajectory is None  # a single structure has no time axis (§3.2)

    cell = obj.frames[0].cell
    assert cell is not None
    assert cell.pbc == (True, True, True)  # format-defined, not guessed (§3.4)
    assert cell.space_group is None  # POSCAR declares no symmetry (§3.4)
    # Fractional (0.5, 0.5, 0.5) became Cartesian (2.82, 2.82, 2.82) at parse (§4).
    assert np.array_equal(obj.frames[0].atoms.positions[1], [2.82, 2.82, 2.82])
    assert obj.provenance.original_coordinate_system == "fractional"

    assert obj.simulation is not None
    assert obj.simulation.extra == {"poscar:scaling_factor": "1.0"}  # structural param (§6.1)
    assert obj.user_metadata.custom_global == {"poscar:comment": "NaCl primitive test"}  # title

    pm = obj.field_presence()
    assert pm.status_of("cell.lattice_vectors") == "present"
    assert pm.status_of("cell.pbc") == "present"
    assert "user_metadata.custom_global['poscar:comment']" in pm.present_paths()
