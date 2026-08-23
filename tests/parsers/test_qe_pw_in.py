"""QE pw.x input parser tests (v1.4 M50-S1/S2; Part 3 §3).

The unit tests pin the boundaries the goldens do not reach: the hand-pinned ibrav
expansion formulas (S2), the unsupported-ibrav / CELL_PARAMETERS-conflict / both-spellings
refusals, the malformed/empty refusals, the never-defaulted required cards, the alat
spellings, the verbatim carries (nothing dropped, P1), and the staging-state registration
(parser-only; no exporter until M51).
"""

from __future__ import annotations

import io
import math

import numpy as np
import pytest

from xtalate.capabilities import Registry
from xtalate.parsers import builtin_parsers
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance
from xtalate.sdk import ParseError, ParseResult

PARSER = make_qe_pw_in_parser()

_NAKED_CELL = """\
&SYSTEM
   ibrav = 0, nat = 1, ntyp = 1,
/
ATOMIC_SPECIES
   Fe 55.845 fe.pbe.UPF
"""


def _parse(text: str, *, filename: str = "pw.in") -> ParseResult:
    return PARSER.parse(io.BytesIO(text.encode("utf-8")), filename=filename)


def _cell_block() -> str:
    return "CELL_PARAMETERS {angstrom}\n   3.0 1.0 0.0\n   0.0 4.0 1.0\n   1.0 0.0 5.0\n"


def _positions(unit: str = "angstrom", *xyz: str) -> str:
    row = " ".join(xyz) if xyz else "1.0 2.0 3.0"
    return f"ATOMIC_POSITIONS {{{unit}}}\n   Fe {row}\n"


# --- sniff --------------------------------------------------------------------------


def test_sniff_identifies_a_namelist_input_at_full_confidence() -> None:
    head = b"&CONTROL\n/\n&SYSTEM\n   ibrav = 0\n/\nATOMIC_POSITIONS {angstrom}\n"
    assert PARSER.sniff(head, "pw.in") == 1.0


def test_sniff_scores_partial_on_a_bare_namelist() -> None:
    # A leading QE namelist is already unambiguous (no other registered format writes
    # one), but the ATOMIC_POSITIONS card pushes it to 1.0.
    assert PARSER.sniff(b"&SYSTEM\n   nat = 1\n/\n", "x") == 0.7
    assert PARSER.sniff(b"&system\n", "x") == 0.7


def test_sniff_is_case_insensitive() -> None:
    assert PARSER.sniff(b"&sYsTeM\n/\nATOMIC_POSITIONS {angstrom}\n", "x") == 1.0


def test_sniff_does_not_match_a_non_namelist_ampersand_line() -> None:
    # "& Some title" is not a QE namelist opener (no known namelist name follows the &).
    assert PARSER.sniff(b"& Some title\n1 2 3\n", "x") == 0.0


def test_sniff_rejects_other_formats() -> None:
    assert PARSER.sniff(b"NaCl primitive cell\n1.0\n4.0 0 0\n0 4.0 0\n0 0 4.0\n", "POSCAR") == 0.0
    assert PARSER.sniff(b"2\nframe\nH 0 0 0\nO 0 0 1\n", "water.xyz") == 0.0
    assert PARSER.sniff(b"ITEM: TIMESTEP\n0\n", "dump.lammpstrj") == 0.0
    # A bare non-QE & (e.g. an ASE-style comment) is not enough.
    assert PARSER.sniff(b"&random\n", "x") == 0.0


# --- units (deterministic boundary conversions) --------------------------------------


def test_angstrom_positions_read_as_is() -> None:
    obj = _parse(_NAKED_CELL + _positions("angstrom") + _cell_block()).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 2.0, 3.0]
    assert obj.provenance.source_units == {"positions": "angstrom", "lattice_vectors": "angstrom"}
    assert obj.provenance.original_coordinate_system == "cartesian"


def test_bohr_positions_convert_with_qe_bohr_radius() -> None:
    obj = _parse(_NAKED_CELL + _positions("bohr", "1.0", "1.0", "1.0") + _cell_block()).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [
        0.52917720859,
        0.52917720859,
        0.52917720859,
    ]


def test_crystal_positions_map_through_the_lattice() -> None:
    src = _NAKED_CELL + _positions("crystal", "0.25", "0.25", "0.25") + _cell_block()
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.25, 1.5]
    assert obj.provenance.original_coordinate_system == "fractional"


def test_alat_positions_resolve_through_celldm1_bohr() -> None:
    # celldm(1) = 2.0 bohr -> alat = 2 × 0.52917720859 = 1.05835441718 Å (hand-computed).
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   celldm(1) = 2.0,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        + _positions("alat", "1.0", "1.0", "1.0")
        + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.05835441718] * 3
    assert any("celldm(1)" in note for note in obj.provenance.parse_notes)


def test_both_lattice_spellings_refuse() -> None:
    # QE's documented contract is "specify either, NOT both" (INPUT_PW &system ibrav);
    # D190 corrects S1's note, which claimed "A wins" — both-present is refused, never
    # silently resolved (P4).
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   celldm(1) = 2.0, A = 4.0,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        + _positions("alat", "0.25", "0.25", "0.25")
        + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_NAMELIST"
    assert "both celldm(1) and A" in exc.value.issues[0].message


def test_alat_angstrom_refuses_both_spellings() -> None:
    # The core's own guard (the reader resolves the refusal first; this pins the core).
    from xtalate.parsers._qe import alat_angstrom

    with pytest.raises(ValueError, match="specify either, not both"):
        alat_angstrom(celldm1=2.0, a=4.0)


def test_alat_positions_without_an_alat_declaration_refuse() -> None:
    # No celldm(1) / A: the scale is uninterpretable — refused, never QE's 1-bohr default.
    with pytest.raises(ParseError) as exc:
        _parse(_NAKED_CELL + _positions("alat", "1.0", "1.0", "1.0") + _cell_block())
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "celldm(1)" in exc.value.issues[0].message


def test_cell_parameters_bohr_convert() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        + _positions("angstrom")
        + "CELL_PARAMETERS {bohr}\n   1.0 0.0 0.0\n   0.0 1.0 0.0\n   0.0 0.0 1.0\n"
    )
    obj = _parse(src).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.lattice_vectors[0].tolist() == [0.52917720859, 0.0, 0.0]
    assert obj.provenance.source_units["lattice_vectors"] == "bohr"


def test_bare_cards_read_as_alat_per_qe_default() -> None:
    # QE's documented default for a unit-less ATOMIC_POSITIONS / CELL_PARAMETERS is alat;
    # the default application is recorded, never silent.
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1, A = 4.0,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        "ATOMIC_POSITIONS\n   Fe 0.25 0.25 0.25\n"
        "CELL_PARAMETERS\n   3.0 1.0 0.0\n   0.0 4.0 1.0\n   1.0 0.0 5.0\n"
    )
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.0, 1.0]
    notes = obj.provenance.parse_notes
    assert any("read as alat per QE's documented default" in n for n in notes)
    assert obj.provenance.source_units == {"positions": "alat", "lattice_vectors": "alat"}


def test_unsupported_position_unit_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(_NAKED_CELL + "ATOMIC_POSITIONS {kelvin}\n   Fe 1 2 3\n" + _cell_block())
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "kelvin" in exc.value.issues[0].message


# --- structure and refusals ----------------------------------------------------------


def test_symbols_follow_position_order() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 2, ntyp = 2,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n   O 15.999 o.pbe.UPF\n"
        "ATOMIC_POSITIONS {angstrom}\n   O 1.0 0.0 0.0\n   Fe 0.0 1.0 0.0\n" + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.symbols == ["O", "Fe"]
    assert obj.frames[0].atoms.positions[1].tolist() == [0.0, 1.0, 0.0]


def test_ibrav_absent_reads_as_zero() -> None:
    # S1's reading (noted in D190): an absent ibrav is treated as the explicit-cell path;
    # with CELL_PARAMETERS present the explicit cell holds. (QE marks ibrav REQUIRED; the
    # refusal-of-missing-ibrav decision is left to a later milestone.)
    obj = _parse(_NAKED_CELL + _positions("angstrom") + _cell_block()).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.lattice_vectors.tolist() == [
        [3.0, 1.0, 0.0],
        [0.0, 4.0, 1.0],
        [1.0, 0.0, 5.0],
    ]


# --- ibrav expansion (M50-S2; D190) --------------------------------------------------


def _ibrav_src(
    ibrav: int,
    system_extra: str,
    *,
    positions_unit: str = "angstrom",
    xyz: tuple[str, ...] = (),
) -> str:
    return (
        f"&SYSTEM\n   ibrav = {ibrav}, nat = 1, ntyp = 1,\n   {system_extra}\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions(positions_unit, *xyz)
    )


@pytest.mark.parametrize(
    ("ibrav", "system_extra", "expected"),
    [
        # Hand-computed from QE's documented conventions (INPUT_PW v7.5 ibrav table;
        # Modules/latgen.f90) — every supported value is pinned, never eyeballed.
        (1, "A = 4.0", [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]),
        (2, "A = 4.0", [[-2.0, 0.0, 2.0], [0.0, 2.0, 2.0], [-2.0, 2.0, 0.0]]),
        (3, "A = 4.0", [[2.0, 2.0, 2.0], [-2.0, 2.0, 2.0], [-2.0, -2.0, 2.0]]),
        (
            4,
            "A = 4.0, C = 6.0",
            [[4.0, 0.0, 0.0], [-2.0, 2.0 * math.sqrt(3.0), 0.0], [0.0, 0.0, 6.0]],
        ),
        (6, "A = 4.0, C = 6.0", [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 6.0]]),
        (8, "A = 4.0, B = 5.0, C = 6.0", [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]]),
        (
            12,
            "A = 4.0, B = 5.0, C = 6.0, cosAB = 0.25",
            [[4.0, 0.0, 0.0], [1.25, 5.0 * math.sqrt(0.9375), 0.0], [0.0, 0.0, 6.0]],
        ),
        (
            -12,
            "A = 4.0, B = 5.0, C = 6.0, cosAC = 0.25",
            [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [1.5, 0.0, 6.0 * math.sqrt(0.9375)]],
        ),
        (
            14,
            "A = 4.0, B = 5.0, C = 6.0, cosAB = 0.6, cosAC = 0.6, cosBC = 0.36",
            [[4.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.6, 0.0, 4.8]],
        ),
    ],
)
def test_ibrav_expansion_is_hand_pinned(
    ibrav: int, system_extra: str, expected: list[list[float]]
) -> None:
    obj = _parse(_ibrav_src(ibrav, system_extra)).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.lattice_vectors.tolist() == [pytest.approx(row) for row in expected]
    notes = obj.provenance.parse_notes
    assert any(f"ibrav={ibrav}" in note for note in notes)  # the derivation is recorded
    assert obj.provenance.source_units["lattice_vectors"] == f"ibrav={ibrav}"


def test_ibrav_both_parameter_spellings_reach_identical_vectors() -> None:
    # Done-means #2: the celldm spelling (alat in bohr + ratios + cosines) and the
    # A,B,C,cosAB,cosAC,cosBC spelling (Å) reach the same 3×3 for the same lattice.
    a_bohr = 4.0 / 0.52917720859  # a = 4 Å expressed in bohr, QE's own conversion
    celldm_src = _ibrav_src(
        14,
        f"celldm(1) = {a_bohr}, celldm(2) = 1.25, celldm(3) = 1.5, "
        "celldm(4) = 0.36, celldm(5) = 0.6, celldm(6) = 0.6",
    )
    abc_src = _ibrav_src(14, "A = 4.0, B = 5.0, C = 6.0, cosAB = 0.6, cosAC = 0.6, cosBC = 0.36")
    celldm_cell = _parse(celldm_src).canonical.frames[0].cell
    abc_cell = _parse(abc_src).canonical.frames[0].cell
    assert celldm_cell is not None and abc_cell is not None
    for row_celldm, row_abc in zip(
        celldm_cell.lattice_vectors.tolist(), abc_cell.lattice_vectors.tolist(), strict=True
    ):
        assert row_celldm == pytest.approx(row_abc)


def test_ibrav_outside_supported_set_refuses_naming_the_value() -> None:
    # ibrav = 5 (trigonal R) is deliberately outside the S2 hand-pinned set; the refusal
    # names the value and never guesses a lattice (P4). The set grows by corpus evidence.
    with pytest.raises(ParseError) as exc:
        _parse(_ibrav_src(5, "A = 4.0"))
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_UNSUPPORTED_IBRAV"
    assert "ibrav = 5" in issue.message
    assert issue.recovery_hint is None


def test_cell_parameters_with_ibrav_nonzero_refuses_the_conflict() -> None:
    # A CELL_PARAMETERS card alongside ibrav ≠ 0 is a QE contradiction — refused, never
    # silently resolved (D190's rejected alternative (b)).
    with pytest.raises(ParseError) as exc:
        _parse(_ibrav_src(4, "A = 4.0, C = 6.0") + _cell_block())
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_MALFORMED_CARD"
    assert "contradicts ibrav" in issue.message


def test_ibrav_without_a_scale_refuses() -> None:
    # The expansion needs celldm(1) or A; neither declared -> refused, never a guessed
    # scale (P3).
    with pytest.raises(ParseError) as exc:
        _parse(_ibrav_src(1, ""))
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_MALFORMED_NAMELIST"
    assert "lattice scale" in issue.message


def test_ibrav_requires_its_ratios() -> None:
    # ibrav = 4 needs c/a > 0; C missing -> refused, mirroring QE's "wrong celldm(3)".
    with pytest.raises(ParseError) as exc:
        _parse(_ibrav_src(4, "A = 4.0"))
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_MALFORMED_NAMELIST"
    assert "c/a" in issue.message


def test_crystal_positions_convert_against_the_derived_lattice() -> None:
    # The S2 cross case: fractional -> Cartesian runs against the *derived* ibrav lattice.
    src = _ibrav_src(4, "A = 4.0, C = 6.0", positions_unit="crystal", xyz=("0.25", "0.25", "0.25"))
    obj = _parse(src).canonical
    # frac 0.25·v1 + 0.25·v2 + 0.25·v3 with v1=(4,0,0), v2=(-2,2√3,0), v3=(0,0,6):
    # (0.5, √3/2, 1.5) — hand-computed.
    assert obj.frames[0].atoms.positions[0].tolist() == pytest.approx(
        [0.5, math.sqrt(3.0) / 2.0, 1.5]
    )
    assert obj.provenance.original_coordinate_system == "fractional"


def test_ibrav_positions_in_alat_scale_with_the_derived_alat() -> None:
    # ATOMIC_POSITIONS {alat} with ibrav ≠ 0 scales against the same resolved alat the
    # expansion used (A here).
    src = _ibrav_src(1, "A = 4.0", positions_unit="alat", xyz=("0.5", "0.5", "0.5"))
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [2.0, 2.0, 2.0]


def test_missing_cell_parameters_refuses_never_defaults() -> None:
    # ibrav = 0 declares an explicit cell; a missing CELL_PARAMETERS is a ParseError, never
    # a defaulted lattice (P3).
    with pytest.raises(ParseError) as exc:
        _parse(_NAKED_CELL + _positions("angstrom"))
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "CELL_PARAMETERS" in exc.value.issues[0].message


def test_missing_atomic_positions_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(_NAKED_CELL + _cell_block())
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "ATOMIC_POSITIONS" in exc.value.issues[0].message


def test_missing_atomic_species_refuses() -> None:
    src = "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n" + _positions("angstrom") + _cell_block()
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "ATOMIC_SPECIES" in exc.value.issues[0].message


def test_missing_nat_refuses() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_NAMELIST"
    assert "nat" in exc.value.issues[0].message


def test_position_count_must_match_nat() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(
            _NAKED_CELL
            + "ATOMIC_POSITIONS {angstrom}\n   Fe 1.0 0.0 0.0\n   Fe 0.0 1.0 0.0\n"
            + _cell_block()
        )
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "nat=1" in exc.value.issues[0].message


def test_species_count_must_match_ntyp() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 2,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "ntyp=2" in exc.value.issues[0].message


def test_unknown_position_label_refuses() -> None:
    src = _NAKED_CELL + "ATOMIC_POSITIONS {angstrom}\n   Ni 1.0 2.0 3.0\n" + _cell_block()
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_CARD"
    assert "Ni" in exc.value.issues[0].message


def test_decorated_labels_resolve_and_are_recorded() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 2, ntyp = 2,\n/\n"
        "ATOMIC_SPECIES\n   Fe1 55.845 fe.pbe.UPF\n   O_vac 15.999 o.pbe.UPF\n"
        "ATOMIC_POSITIONS {angstrom}\n   Fe1 1.0 2.0 3.0\n   O_vac 3.0 2.0 1.0\n" + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.symbols == ["Fe", "O"]
    notes = obj.provenance.parse_notes
    assert any("Fe1" in note and "Fe" in note for note in notes)
    assert any("O_vac" in note and "O" in note for note in notes)


def test_unresolvable_label_refuses_with_the_missing_species_hint() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Zz 15.999 zz.pbe.UPF\n"
        "ATOMIC_POSITIONS {angstrom}\n   Zz 1.0 2.0 3.0\n" + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_UNRESOLVED_SPECIES_LABEL"
    assert issue.recovery_hint == "supply_species"
    assert "Zz" in issue.message


def test_empty_file_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        _parse("")
    assert exc.value.issues[0].code == "QEIN_EMPTY"


def test_unterminated_namelist_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        _parse("&SYSTEM\n   ibrav = 0, nat = 1,\n")
    assert exc.value.issues[0].code == "QEIN_MALFORMED_NAMELIST"
    assert "never terminated" in exc.value.issues[0].message


def test_duplicate_namelist_refuses() -> None:
    src = "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n&SYSTEM\n/\n"
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_MALFORMED_NAMELIST"
    assert "twice" in exc.value.issues[0].message


def test_malformed_namelist_value_refuses_with_location() -> None:
    with pytest.raises(ParseError) as exc:
        _parse("&SYSTEM\n   ibrav = ,\n/\n")
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_MALFORMED_NAMELIST"
    assert issue.location == "&system"


def test_encoding_error_names_the_byte_offset() -> None:
    data = b"&SYSTEM\n/\n" + b"\xff\xfe not utf-8\n"
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(data), filename="pw.in")
    issue = exc.value.issues[0]
    # The shared decode_text machinery derives the code from the format_id (the same
    # spelling every other text parser uses: LAMMPSDUMP_ENCODING_ERROR, OUTCAR_ENCODING_ERROR…).
    assert issue.code == "QE_PW_IN_ENCODING_ERROR"
    assert issue.location is not None and issue.location.startswith("byte")


# --- verbatim carries (nothing dropped, P1) ------------------------------------------


def test_atomic_species_table_and_pseudopotentials_carried_verbatim() -> None:
    obj = _parse(
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    ).canonical
    carried = obj.user_metadata.custom_global["qe_pw_in:atomic_species"]
    assert carried == {"Fe": [55.845, "fe.pbe.UPF"]}
    assert obj.user_metadata.custom_global["qe:pseudopotentials"] == {"Fe": "fe.pbe.UPF"}
    # M50-S3 promotes the declared mass to atoms.masses (present-with-value, P3).
    assert obj.frames[0].atoms.masses is not None
    assert obj.frames[0].atoms.masses.tolist() == [55.845]


def test_k_points_card_carried_verbatim_with_a_warning() -> None:
    src = (
        _NAKED_CELL
        + _positions("angstrom")
        + _cell_block()
        + "K_POINTS {automatic}\n   4 4 4 0 0 0\n"
    )
    result = _parse(src)
    # Kept + reported, never refused (P1): the warning names the card, and the note
    # states the schema has no canonical k-point model rather than inventing one.
    codes = [issue.code for issue in result.issues]
    assert codes == ["QEIN_UNMAPPED_ENTRY_CARRIED"]
    assert all(issue.severity == "warning" for issue in result.issues)
    assert any(
        "no canonical k-point model" in note for note in result.canonical.provenance.parse_notes
    )
    carried = result.canonical.user_metadata.custom_global["qe_pw_in:unmapped_cards"]
    assert carried == [{"card": "K_POINTS", "unit": "automatic", "lines": ["4 4 4 0 0 0"]}]


def test_occupations_card_carried_verbatim() -> None:
    src = _NAKED_CELL + _positions("angstrom") + _cell_block() + "OCCUPATIONS\n   1.0 1.0\n"
    carried = _parse(src).canonical.user_metadata.custom_global["qe_pw_in:unmapped_cards"]
    assert carried == [{"card": "OCCUPATIONS", "unit": None, "lines": ["1.0 1.0"]}]


def test_recognized_simulation_context_routes_to_simulation_extra() -> None:
    src = (
        "&CONTROL\n   calculation = 'scf', ecutwfc = 30.0,\n/\n"
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.simulation is not None
    assert obj.simulation.extra == {"calculation": "scf", "ecutwfc": "30.0"}
    # Promoted here means consumed — no double-report in the namelist carry.
    assert "qe_pw_in:namelists" not in obj.user_metadata.custom_global
    assert any("simulation.extra" in note for note in obj.provenance.parse_notes)


def test_unrecognized_namelist_entries_carried_verbatim_with_a_warning() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   nspin = 2,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    result = _parse(src)
    assert [i.code for i in result.issues] == ["QEIN_UNMAPPED_ENTRY_CARRIED"]
    carried = result.canonical.user_metadata.custom_global["qe_pw_in:namelists"]
    assert carried == {"system": {"nspin": 2}}
    assert any("nspin" in i.message for i in result.issues)


# --- provenance / capabilities / registration ----------------------------------------


def test_provenance_records_parse_record_and_notes() -> None:
    obj = _parse(_NAKED_CELL + _positions("angstrom") + _cell_block()).canonical
    assert obj.provenance.source_format == "qe_pw_in"
    assert obj.provenance.source_filename == "pw.in"
    assert obj.provenance.history[0].operation == "parse"
    assert any("pbc set to (true,true,true)" in note for note in obj.provenance.parse_notes)


def test_capabilities_declare_read_side_only() -> None:
    caps = PARSER.capabilities()
    assert caps.format_id == "qe_pw_in"
    assert caps.direction == "read"
    assert caps.max_frames == 1
    assert caps.fields["atoms.positions"].level.value == "full"
    assert caps.fields["cell.lattice_vectors"].level.value == "full"
    assert caps.fields["atoms.symbols"].level.value == "full"
    assert caps.fields["atoms.masses"].level.value == "full"


def test_registered_parser_only_as_a_staging_state() -> None:
    # The plan's done-means #3: parser-only registration (the lammps precedent D175/D180,
    # not the vasprun/OUTCAR permanent seam D159/D164) — no exporter until M51.
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    assert "qe_pw_in" in {p.format_id for p in reg.parsers()}
    assert "qe_pw_in" not in {e.format_id for e in reg.exporters()}
    matrix = reg.capability_matrix()
    assert matrix.get("qe_pw_in", "read").format_id == "qe_pw_in"
    with pytest.raises(KeyError):
        matrix.get("qe_pw_in", "write")


# --- M50-S3: species resolution / masses / carries / recovery -----------------------


def _two_species_src(*, labels: tuple[str, str], masses: tuple[str, str]) -> str:
    return (
        "&SYSTEM\n   ibrav = 0, nat = 2, ntyp = 2,\n/\n"
        "ATOMIC_SPECIES\n"
        f"   {labels[0]} {masses[0]} a.upf\n"
        f"   {labels[1]} {masses[1]} b.upf\n"
        "ATOMIC_POSITIONS {angstrom}\n"
        f"   {labels[0]} 1.0 2.0 3.0\n"
        f"   {labels[1]} 3.0 2.0 1.0\n" + _cell_block()
    )


def test_masses_promote_present_with_value_never_defaulted() -> None:
    obj = _parse(_two_species_src(labels=("Fe1", "O_vac"), masses=("55.845", "15.999"))).canonical
    assert obj.frames[0].atoms.masses is not None
    assert obj.frames[0].atoms.masses.tolist() == [55.845, 15.999]
    # The declared pseudopotential filenames ride label → filename, never dropped.
    assert obj.user_metadata.custom_global["qe:pseudopotentials"] == {
        "Fe1": "a.upf",
        "O_vac": "b.upf",
    }


def test_same_label_mass_repeats_per_atom() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 2, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        "ATOMIC_POSITIONS {angstrom}\n   Fe 1.0 2.0 3.0\n   Fe 3.0 2.0 1.0\n" + _cell_block()
    )
    masses = _parse(src).canonical.frames[0].atoms.masses
    assert masses is not None
    assert masses.tolist() == [55.845, 55.845]


def test_convergence_and_cutoff_context_routes_to_simulation_extra() -> None:
    src = (
        "&CONTROL\n   calculation = 'relax', ecutwfc = 40.0, ecutrho = 320.0,\n/\n"
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   degauss = 0.01, smearing = 'gaussian',"
        " occupations = 'smearing',\n/\n"
        "&ELECTRONS\n   conv_thr = 1.0d-8,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.simulation is not None
    assert obj.simulation.extra == {
        "calculation": "relax",
        "ecutwfc": "40.0",
        "ecutrho": "320.0",
        "degauss": "0.01",
        "smearing": "gaussian",
        "occupations": "smearing",
        "conv_thr": "1e-08",
    }


def test_empty_namelists_produce_no_simulation_metadata() -> None:
    obj = _parse(_NAKED_CELL + _positions("angstrom") + _cell_block()).canonical
    assert obj.simulation is None


def test_unknown_marker_label_resolves_to_the_shared_marker() -> None:
    # The shared element table's reserved pseudo-element "X" (unknown-species marker) is a
    # symbol in that table, so a label whose leading character is X resolves to the marker,
    # recorded — never silently a real element (D191).
    obj = _parse(_two_species_src(labels=("Fe", "Xx"), masses=("55.845", "1.008"))).canonical
    assert obj.frames[0].atoms.symbols == ["Fe", "X"]
    assert any("Xx" in note and "marker" not in note for note in obj.provenance.parse_notes)


def test_recovery_species_map_completes_the_read_and_is_recorded() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    with pytest.raises(ParseError) as exc:
        _parse(src)
    assert exc.value.issues[0].code == "QEIN_UNRESOLVED_SPECIES_LABEL"
    result = PARSER.parse_recover(
        io.BytesIO(src.encode()),
        filename="pw.in",
        hint="supply_species",
        choice="species_map",
        parameters={"species": {"Fe1": "Fe", "Zz": "O"}},
    )
    assert result.canonical.frames[0].atoms.symbols == ["Fe", "O"]
    masses = result.canonical.frames[0].atoms.masses
    assert masses is not None
    assert masses.tolist() == [55.845, 15.999]
    assert any(
        issue.code == "QEIN_SPECIES_SUPPLIED" and issue.severity == "warning"
        for issue in result.issues
    )


def test_recovery_species_map_cli_string_form() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    result = PARSER.parse_recover(
        io.BytesIO(src.encode()),
        filename="pw.in",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "Fe1:Fe Zz:O"},
    )
    assert result.canonical.frames[0].atoms.symbols == ["Fe", "O"]


def test_recovery_map_value_that_is_not_an_element_refuses() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src.encode()),
            filename="pw.in",
            hint="supply_species",
            choice="species_map",
            parameters={"species": {"Fe1": "Fe", "Zz": "NotAnElement"}},
        )
    assert exc.value.issues[0].code == "QEIN_UNRESOLVED_SPECIES_LABEL"


def _reference_object(symbols: list[str]) -> CanonicalObject:
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=symbols, positions=np.asarray([[0.0, 0.0, 0.0] for _ in symbols])
                ),
                cell=Cell(
                    lattice_vectors=np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
                    pbc=(True, True, True),
                ),
            )
        ],
        provenance=Provenance(
            source_filename=None,
            source_format="qe_pw_in",
            original_coordinate_system="cartesian",
        ),
    )


def test_recovery_upload_reference_applies_per_atom_symbols() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    reference = _reference_object(["Fe", "O"])
    result = PARSER.parse_recover(
        io.BytesIO(src.encode()),
        filename="pw.in",
        hint="supply_species",
        choice="upload_reference",
        parameters={"reference": reference},
    )
    assert result.canonical.frames[0].atoms.symbols == ["Fe", "O"]


def test_recovery_upload_reference_count_mismatch_refuses() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    reference = _reference_object(["Fe"])
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src.encode()),
            filename="pw.in",
            hint="supply_species",
            choice="upload_reference",
            parameters={"reference": reference},
        )
    assert exc.value.issues[0].code == "QEIN_UNRESOLVED_SPECIES_LABEL"


def test_recovery_unknown_hint_or_choice_refuses() -> None:
    src = _two_species_src(labels=("Fe1", "Zz"), masses=("55.845", "15.999"))
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src.encode()),
            filename="pw.in",
            hint="ambiguous_units",
            choice="metal",
            parameters={},
        )
    assert exc.value.issues[0].code == "QEIN_UNRESOLVED_SPECIES_LABEL"
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src.encode()),
            filename="pw.in",
            hint="supply_species",
            choice="not_a_choice",
            parameters={},
        )
    assert "no choice" in exc.value.issues[0].message
