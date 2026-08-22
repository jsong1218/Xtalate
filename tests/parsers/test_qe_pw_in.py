"""QE pw.x input parser tests (v1.4 M50-S1; Part 3 §3).

The unit tests pin the S1 boundaries the goldens do not reach: the ibrav refusal stub,
the malformed/empty refusals, the never-defaulted required cards, the alat spellings, the
verbatim carries (nothing dropped, P1), and the staging-state registration (parser-only;
no exporter until M51).
"""

from __future__ import annotations

import io

import pytest

from xtalate.capabilities import Registry
from xtalate.parsers import builtin_parsers
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
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


def test_alat_prefers_a_over_celldm1() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   celldm(1) = 2.0, A = 4.0,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n"
        + _positions("alat", "0.25", "0.25", "0.25")
        + _cell_block()
    )
    obj = _parse(src).canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.0, 1.0]
    assert any("QE prefers A over celldm(1)" in note for note in obj.provenance.parse_notes)


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


def test_ibrav_nonzero_refuses_unsupported_ibrav_stub() -> None:
    src = (
        "&SYSTEM\n   ibrav = 1, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_UNSUPPORTED_IBRAV"
    assert "M50-S2" in issue.message
    assert issue.recovery_hint is None  # no recovery scenario exists; S2 replaces the stub


def test_ibrav_absent_reads_as_zero() -> None:
    # QE's documented ibrav default is 0; with CELL_PARAMETERS present the explicit-cell
    # path holds and the default is recorded.
    obj = _parse(_NAKED_CELL + _positions("angstrom") + _cell_block()).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.lattice_vectors.tolist() == [
        [3.0, 1.0, 0.0],
        [0.0, 4.0, 1.0],
        [1.0, 0.0, 5.0],
    ]


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


def test_decorated_label_refuses_naming_s3() -> None:
    src = (
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe1 55.845 fe.pbe.UPF\n"
        "ATOMIC_POSITIONS {angstrom}\n   Fe1 1.0 2.0 3.0\n" + _cell_block()
    )
    with pytest.raises(ParseError) as exc:
        _parse(src)
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_MALFORMED_CARD"
    assert "Fe1" in issue.message
    assert "M50-S3" in issue.message


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


def test_atomic_species_table_carried_verbatim() -> None:
    obj = _parse(
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    ).canonical
    carried = obj.user_metadata.custom_global["qe_pw_in:atomic_species"]
    assert carried == {"Fe": [55.845, "fe.pbe.UPF"]}
    assert obj.frames[0].atoms.masses is None  # S1 carries; S3 promotes


def test_k_points_card_carried_verbatim() -> None:
    src = (
        _NAKED_CELL
        + _positions("angstrom")
        + _cell_block()
        + "K_POINTS {automatic}\n   4 4 4 0 0 0\n"
    )
    result = _parse(src)
    assert result.issues == []
    carried = result.canonical.user_metadata.custom_global["qe_pw_in:unmapped_cards"]
    assert carried == [{"card": "K_POINTS", "unit": "automatic", "lines": ["4 4 4 0 0 0"]}]


def test_occupations_card_carried_verbatim() -> None:
    src = _NAKED_CELL + _positions("angstrom") + _cell_block() + "OCCUPATIONS\n   1.0 1.0\n"
    carried = _parse(src).canonical.user_metadata.custom_global["qe_pw_in:unmapped_cards"]
    assert carried == [{"card": "OCCUPATIONS", "unit": None, "lines": ["1.0 1.0"]}]


def test_unconsumed_namelist_entries_carried_verbatim() -> None:
    src = (
        "&CONTROL\n   calculation = 'scf',\n/\n"
        "&SYSTEM\n   ibrav = 0, nat = 1, ntyp = 1,\n   ecutwfc = 30.0,\n/\n"
        "ATOMIC_SPECIES\n   Fe 55.845 fe.pbe.UPF\n" + _positions("angstrom") + _cell_block()
    )
    carried = _parse(src).canonical.user_metadata.custom_global["qe_pw_in:namelists"]
    assert carried == {"control": {"calculation": "scf"}, "system": {"ecutwfc": 30.0}}


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
    assert caps.fields["atoms.symbols"].level.value == "partial"


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
