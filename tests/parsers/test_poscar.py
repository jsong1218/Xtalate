"""POSCAR/CONTCAR parser tests (M3b): golden fidelity, coordinate/scale handling,
selective dynamics, VASP-4 recovery error, the CONTCAR tail, and sniffing (Part 3 §3, §6.1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden, parse_bytes
from xtalate.parsers.poscar import make_contcar_parser, make_poscar_parser
from xtalate.sdk import ParseError

GOLDEN = Path(__file__).parent.parent / "golden" / "poscar" / "nacl-primitive"

VASP5_CART = b"""cart test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
Si
2
Cartesian
  0.0 0.0 0.0
  2.0 2.0 2.0
"""

SELECTIVE = b"""sd test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
2
Selective dynamics
Direct
  0.0 0.0 0.0   T T F
  0.5 0.5 0.5   F F F
"""

SELECTIVE_ALL_T = b"""all-T test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
1
Selective dynamics
Direct
  0.0 0.0 0.0   T T T
"""

VASP4 = b"""vasp4 test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
1 1
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

NEG_SCALE = b"""neg scale
-8.0
  1.0  0.0  0.0
  0.0  1.0  0.0
  0.0  0.0  1.0
He
1
Direct
  0.0 0.0 0.0
"""


def test_golden_nacl() -> None:
    source = (GOLDEN / "POSCAR").read_bytes()
    result = parse_bytes(make_poscar_parser(), source, filename="POSCAR")
    assert result.issues == []
    assert_matches_golden(result.canonical, (GOLDEN / "expected.canonical.json").read_text())


def test_fractional_converted_to_cartesian() -> None:
    obj = parse_bytes(make_poscar_parser(), (GOLDEN / "POSCAR").read_bytes()).canonical
    assert np.array_equal(obj.frames[0].atoms.positions[1], [2.82, 2.82, 2.82])
    assert obj.provenance.original_coordinate_system == "fractional"
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.pbc == (True, True, True)  # format-defined (§3 n.3)
    # The scaling factor is folded into the lattice (§4), so it is recorded as a provenance note,
    # not as a presence-bearing simulation.extra field (DECISIONS.md D34): storing it there made
    # every POSCAR→POSCAR conversion false-fail absence-conformance.
    assert obj.simulation is None
    assert any("scaling factor" in note and "1.0" in note for note in obj.provenance.parse_notes)
    assert obj.user_metadata.custom_global == {"poscar:comment": "NaCl primitive test"}


def test_cartesian_mode_scales_positions() -> None:
    obj = parse_bytes(make_poscar_parser(), VASP5_CART).canonical
    assert obj.provenance.original_coordinate_system == "cartesian"
    assert np.array_equal(obj.frames[0].atoms.positions[1], [2.0, 2.0, 2.0])
    assert obj.frames[0].atoms.symbols == ["Si", "Si"]


def test_non_cartesian_mode_line_is_read_as_direct() -> None:
    # VASP rule (§4): only C/c/K/k is Cartesian; every other mode line — here 'Fractional' — is
    # Direct. Keying only off 'd' would silently misread fractional 0.5 as 0.5 Å (undetectable
    # corruption). The ambiguous mode line is flagged, not swallowed.
    fractional = b"t\n1.0\n4 0 0\n0 4 0\n0 0 4\nSi\n1\nFractional\n0.5 0.5 0.5\n"
    result = parse_bytes(make_poscar_parser(), fractional)
    obj = result.canonical
    assert np.array_equal(obj.frames[0].atoms.positions[0], [2.0, 2.0, 2.0])
    assert obj.provenance.original_coordinate_system == "fractional"
    assert any(i.code == "POSCAR_AMBIGUOUS_COORDINATE_MODE" for i in result.issues)


def test_cartesian_k_prefix_mode_line() -> None:
    # A mode line beginning with 'K' (kartesian, a VASP synonym) is Cartesian, no warning.
    kart = b"t\n1.0\n4 0 0\n0 4 0\n0 0 4\nSi\n1\nKartesian\n1.5 1.5 1.5\n"
    result = parse_bytes(make_poscar_parser(), kart)
    assert np.array_equal(result.canonical.frames[0].atoms.positions[0], [1.5, 1.5, 1.5])
    assert result.canonical.provenance.original_coordinate_system == "cartesian"
    assert result.issues == []


def test_non_utf8_input_is_parse_error() -> None:
    # A non-text file handed to the text parser must fail through the ParseError contract (§5),
    # not raise a raw UnicodeDecodeError.
    with pytest.raises(ParseError) as exc:
        parse_bytes(make_poscar_parser(), b"t\n1.0\n\xff 0 0\n0 4 0\n0 0 4\nSi\n1\nDirect\n0 0 0\n")
    assert exc.value.issues[0].code == "POSCAR_ENCODING_ERROR"


def test_negative_scale_is_target_volume() -> None:
    # scale -8.0 on a unit cube => volume 8 => 2x2x2 cell.
    obj = parse_bytes(make_poscar_parser(), NEG_SCALE).canonical
    cell = obj.frames[0].cell
    assert cell is not None
    assert np.allclose(cell.lattice_vectors, np.diag([2.0, 2.0, 2.0]))


def test_selective_dynamics_maps_to_constraint() -> None:
    obj = parse_bytes(make_poscar_parser(), SELECTIVE).canonical
    constraints = obj.frames[0].dynamics.constraints
    assert constraints is not None and len(constraints) == 1
    c = constraints[0]
    assert c.kind == "selective_dynamics"
    assert c.parameters["mask"] == [[True, True, False], [False, False, False]]


def test_selective_dynamics_all_true_is_empty_list_not_none() -> None:
    # Present-but-all-T => constraints == [] (explicitly unconstrained), distinct from None.
    obj = parse_bytes(make_poscar_parser(), SELECTIVE_ALL_T).canonical
    assert obj.frames[0].dynamics.constraints == []


def test_no_selective_dynamics_is_none() -> None:
    obj = parse_bytes(make_poscar_parser(), (GOLDEN / "POSCAR").read_bytes()).canonical
    assert obj.frames[0].dynamics.constraints is None


def test_vasp4_missing_species_is_recoverable_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(make_poscar_parser(), VASP4)
    issue = exc.value.issues[0]
    assert issue.code == "POSCAR_MISSING_SPECIES"
    assert issue.recovery_hint == "supply_species"


def test_inconsistent_atom_count_raises() -> None:
    truncated = b"x\n1.0\n4 0 0\n0 4 0\n0 0 4\nH\n2\nDirect\n  0 0 0\n"
    with pytest.raises(ParseError) as exc:
        parse_bytes(make_poscar_parser(), truncated)
    assert exc.value.issues[0].code == "POSCAR_INCONSISTENT_ATOM_COUNT"


def test_contcar_parser_reads_same_fields() -> None:
    # CONTCAR is byte-identical to POSCAR; same implementation, different reported label.
    obj = parse_bytes(make_contcar_parser(), (GOLDEN / "POSCAR").read_bytes()).canonical
    assert obj.provenance.source_format == "contcar"
    assert np.array_equal(obj.frames[0].atoms.positions[1], [2.82, 2.82, 2.82])


def test_velocity_and_predictor_tail_carried_through() -> None:
    with_tail = (
        b"md\n1.0\n"
        b"  4.0 0.0 0.0\n  0.0 4.0 0.0\n  0.0 0.0 4.0\n"
        b"H\n1\nDirect\n  0.0 0.0 0.0\n"
        b"\nCartesian\n  0.1 0.2 0.3\n"
        b"\n  99.0 99.0\n"  # predictor-corrector remainder (not 3-float velocity rows)
    )
    result = parse_bytes(make_contcar_parser(), with_tail)
    obj = result.canonical
    assert obj.frames[0].dynamics.velocities is not None
    assert np.array_equal(obj.frames[0].dynamics.velocities[0], [0.1, 0.2, 0.3])
    assert "contcar:predictor_corrector" in obj.user_metadata.custom_global
    assert any(i.code == "POSCAR_PREDICTOR_CORRECTOR_CARRIED" for i in result.issues)
    # A velocity block came from the file, so its unit is annotated and noted (not left implicit).
    assert obj.provenance.source_units.get("velocities") == "angstrom/fs"
    assert any("velocity block read from the CONTCAR tail" in n for n in obj.provenance.parse_notes)


def test_sniff_exact_names() -> None:
    poscar = make_poscar_parser()
    contcar = make_contcar_parser()
    data = (GOLDEN / "POSCAR").read_bytes()
    assert poscar.sniff(data, "POSCAR") == 1.0
    assert contcar.sniff(data, "CONTCAR") == 1.0
    # Nameless file: both match structurally, POSCAR scores higher (§6.1 tie-break).
    assert poscar.sniff(data, None) > contcar.sniff(data, None)
    assert poscar.sniff(data, None) >= 0.5
