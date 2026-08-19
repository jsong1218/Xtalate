"""LAMMPS dump parser tests (v1.3 M46-S2; Part 3 §3).

The parser's "ordinary axes" are pinned here against hand-verified expectations: declared
units honored / undeclared refused (the ``ambiguous_units`` scenario), absent velocities
``None``, generic ``compute``/``fix`` columns carried to ``custom_per_atom`` with a warning
(``ix iy iz`` included generically at this slice), and the constant-N boundary enforced as a
measured refusal. The golden cases under ``tests/golden/lammps_dump/`` are diffed through the
same external-truth machinery every other format uses (Part 8 §3); the recovered typed-atoms
expectation exercises ``parse_recover`` against the shared ``missing_species`` scenario.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.sdk import ParseError, ParseResult
from xtalate.sdk.streaming import materialize

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_dump"
PARSER = make_lammps_dump_parser()

# The golden cases that parse cleanly (declared units, element-labeled) with their expected
# issue codes; the typed-atoms case refuses until recovery and is handled separately.
_CLEAN_CASES = {
    "metal-ortho-declared": ["LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED"],
    "real-triclinic-scaled": [],
    "si-ortho-declared": [],
}


def _source(case: str) -> bytes:
    return (GOLDEN / case / "dump.lammpstrj").read_bytes()


def _parse(case: str) -> ParseResult:
    return PARSER.parse(io.BytesIO(_source(case)), filename="dump.lammpstrj")


# --- golden fidelity (whole-file and streamed — D56 one-code-path) -------------------


@pytest.mark.parametrize("case", sorted(_CLEAN_CASES))
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", sorted(_CLEAN_CASES))
def test_streamed_parse_matches_golden(case: str) -> None:
    """The streamed reading must match the *same* external-truth expectation the whole-file
    one does — not merely match the whole-file reading (which would be self-consistent by
    construction, since ``parse`` is defined through ``parse_stream``)."""
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    stream = PARSER.parse_stream(io.BytesIO(_source(case)), filename="dump.lammpstrj")
    obj, _ = materialize(stream)
    assert_matches_golden(obj, expected)


def test_typed_atoms_golden_resolves_through_missing_species() -> None:
    """The typed-atoms golden's expectation is the *recovered* object: the plain parse
    refuses (recoverable), and the ``species_map`` re-read resolves types to symbols."""
    case = "typed-atoms-metal"
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    with pytest.raises(ParseError) as exc:
        _parse(case)
    assert exc.value.issues[0].code == "LAMMPSDUMP_MISSING_SPECIES"
    assert exc.value.issues[0].recovery_hint == "supply_species"
    recovered = PARSER.parse_recover(
        io.BytesIO(_source(case)),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "1:Si 2:O"},
    )
    assert_matches_golden(recovered.canonical, expected)


# --- declared vs undeclared vs unsupported units -------------------------------------


def test_declared_units_parse_with_no_scenario_and_style_in_parse_notes() -> None:
    obj = _parse("metal-ortho-declared").canonical
    issue_codes = [i.code for i in _parse("metal-ortho-declared").issues]
    assert "LAMMPSDUMP_AMBIGUOUS_UNITS" not in issue_codes
    assert any(
        "Unit style in force: metal (Å, ps, eV) — declared in the file." in n
        for n in obj.provenance.parse_notes
    )


def test_undeclared_units_refuse_with_ambiguous_units_hint() -> None:
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS metal\n", b"")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(undeclared), filename="dump.lammpstrj")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDUMP_AMBIGUOUS_UNITS"
    assert issue.recovery_hint == "ambiguous_units"


def test_undeclared_units_recover_under_a_chosen_style() -> None:
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS metal\n", b"")
    recovered = PARSER.parse_recover(
        io.BytesIO(undeclared),
        filename="dump.lammpstrj",
        hint="ambiguous_units",
        choice="metal",
        parameters={},
    )
    # The recovery applies the chosen style's conversion factors through the same code path.
    assert recovered.canonical.frames[0].atoms.positions[0].tolist() == [1.0, 2.0, 3.0]
    assert any(i.code == "LAMMPSDUMP_UNITS_INTERPRETED" for i in recovered.issues)
    assert any("applied by recovery" in n for n in recovered.canonical.provenance.parse_notes)


def test_unknown_recovery_style_refuses() -> None:
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS metal\n", b"")
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(undeclared),
            filename="dump.lammpstrj",
            hint="ambiguous_units",
            choice="lj",
            parameters={},
        )
    assert exc.value.issues[0].code == "LAMMPSDUMP_UNSUPPORTED_UNITS"


def test_declared_unsupported_units_refuse() -> None:
    lj = _source("metal-ortho-declared").replace(b"ITEM: UNITS metal", b"ITEM: UNITS lj")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(lj), filename="dump.lammpstrj")
    assert exc.value.issues[0].code == "LAMMPSDUMP_UNSUPPORTED_UNITS"


# --- absent velocities, generic columns, per-frame variance --------------------------


def test_absent_velocities_stay_none() -> None:
    obj = _parse("si-ortho-declared").canonical
    assert obj.frames[0].dynamics.velocities is None


def test_velocities_converted_from_metal_angstrom_per_picosecond() -> None:
    obj = _parse("metal-ortho-declared").canonical
    velocities = obj.frames[0].dynamics.velocities
    assert velocities is not None
    # 0.1 Å/ps -> 0.0001 Å/fs (the S1 table's metal velocity factor, ×1e-3).
    assert velocities[0].tolist() == [0.0001, 0.0002, 0.0003]


def test_generic_columns_carried_with_warning() -> None:
    result = _parse("metal-ortho-declared")
    assert result.issues[0].code == "LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED"
    carried = result.canonical.user_metadata.custom_per_atom["lammps_dump:c_pe"]
    assert np.asarray(carried).tolist() == [5.0, 6.0]


def test_image_flag_columns_carried_generically_at_s2() -> None:
    """At the end of S2, ix/iy/iz flow through the generic unmapped-column carry — retained,
    a generic warning fires, nothing is silently lost (S3 upgrades them to the specific
    image-flag hazard)."""
    dump = (
        _source("metal-ortho-declared")
        .replace(
            b"ITEM: ATOMS id element x y z vx vy vz c_pe",
            b"ITEM: ATOMS id element x y z ix iy iz",
        )
        .replace(b"1 Si 1.0 2.0 3.0 0.1 0.2 0.3 5.0", b"1 Si 1.0 2.0 3.0 0 0 0")
        .replace(b"2 O 4.0 5.0 6.0 -0.1 -0.2 -0.3 6.0", b"2 O 4.0 5.0 6.0 0 0 0")
        .replace(b"1 Si 1.5 2.5 3.5 0.11 0.21 0.31 5.0", b"1 Si 1.5 2.5 3.5 1 1 1")
        .replace(b"2 O 4.0 5.0 6.0 -0.11 -0.21 -0.31 6.0", b"2 O 4.0 5.0 6.0 1 1 1")
    )
    result = PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    assert "LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED" in {i.code for i in result.issues}
    for name in ("ix", "iy", "iz"):
        key = f"lammps_dump:{name}"
        assert key in result.canonical.user_metadata.custom_per_atom
        assert np.asarray(result.canonical.user_metadata.custom_per_atom[key]).tolist() == [
            0.0,
            0.0,
        ]


def test_per_frame_column_variance_warns_once_per_column() -> None:
    dump = _source("metal-ortho-declared").replace(
        b"1 Si 1.5 2.5 3.5 0.11 0.21 0.31 5.0",
        b"1 Si 1.5 2.5 3.5 0.11 0.21 0.31 9.0",
    )
    result = PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    codes = [i.code for i in result.issues]
    assert codes.count("LAMMPSDUMP_PER_FRAME_COLUMN_NOT_REPRESENTABLE") == 1
    # Frame 0's values are carried; the diverging frame 1 is not silently kept.
    carried = result.canonical.user_metadata.custom_per_atom["lammps_dump:c_pe"]
    assert np.asarray(carried).tolist() == [5.0, 6.0]


# --- constant-N measured refusal -----------------------------------------------------


def test_variable_atom_count_refuses_with_measured_counts() -> None:
    dump = _source("metal-ortho-declared").replace(
        b"ITEM: TIMESTEP\n10\nITEM: NUMBER OF ATOMS\n2",
        b"ITEM: TIMESTEP\n10\nITEM: NUMBER OF ATOMS\n3",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDUMP_VARIABLE_ATOM_COUNT"
    assert "frame 1 declares 3 atoms but frame 0 declares 2" in issue.message
    assert "Per-frame counts seen: [2, 3]" in issue.message
    assert "never padded or truncated" in issue.message


def test_constant_atom_count_two_frames_parse_cleanly() -> None:
    obj = _parse("metal-ortho-declared").canonical
    assert obj.frame_count == 2
    assert [f.index for f in obj.frames] == [0, 1]


# --- typed atoms: species_map + upload_reference -------------------------------------


def test_typed_atoms_refuse_without_a_preset() -> None:
    with pytest.raises(ParseError) as exc:
        _parse("typed-atoms-metal")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDUMP_MISSING_SPECIES"
    assert issue.recovery_hint == "supply_species"


def test_species_map_recovery_validates_against_observed_types() -> None:
    src = _source("typed-atoms-metal")
    ok = PARSER.parse_recover(
        io.BytesIO(src),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "1:Si 2:O"},
    )
    assert ok.canonical.frames[0].atoms.symbols == ["Si", "O"]
    assert any(i.code == "LAMMPSDUMP_SPECIES_SUPPLIED" for i in ok.issues)
    # The original type numbers ride along under the carry key (frame 0, first dim N).
    assert np.asarray(ok.canonical.user_metadata.custom_per_atom["lammps_dump:type"]).tolist() == [
        1.0,
        2.0,
    ]
    # A map that omits an observed type cannot resolve the file.
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src),
            filename="dump.lammpstrj",
            hint="supply_species",
            choice="species_map",
            parameters={"species": "1:Si"},
        )
    assert "does not name observed type(s)" in exc.value.issues[0].message
    # A map naming types the file does not contain is refused, never silently trimmed.
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src),
            filename="dump.lammpstrj",
            hint="supply_species",
            choice="species_map",
            parameters={"species": "1:Si 2:O 3:He"},
        )
    assert "does not match this dump" in exc.value.issues[0].message


def test_upload_reference_choice_resolves_typed_atoms() -> None:
    src = _source("typed-atoms-metal")
    # A matching reference structure (2 atoms: Si, O) supplies the per-atom symbols.
    reference = PARSER.parse_recover(
        io.BytesIO(src),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "1:Si 2:O"},
    ).canonical
    recovered = PARSER.parse_recover(
        io.BytesIO(src),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="upload_reference",
        parameters={"reference": reference},
    )
    assert recovered.canonical.frames[0].atoms.symbols == ["Si", "O"]


def test_upload_reference_requires_a_reference() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(_source("typed-atoms-metal")),
            filename="dump.lammpstrj",
            hint="supply_species",
            choice="upload_reference",
            parameters={},
        )
    assert exc.value.issues[0].code == "LAMMPSDUMP_MISSING_SPECIES"


# --- triclinic exactness (end to end through the parser) -----------------------------


def test_triclinic_box_inversion_and_scaled_conversion_exact() -> None:
    obj = _parse("real-triclinic-scaled").canonical
    frame = obj.frames[0]
    assert frame.cell is not None
    # Edge vectors recovered from the bounding-box rows (a=(20,0,0) b=(5,10,0) c=(3,2,10)).
    assert frame.cell.lattice_vectors.tolist() == [
        [20.0, 0.0, 0.0],
        [5.0, 10.0, 0.0],
        [3.0, 2.0, 10.0],
    ]
    # Scaled (0.5,0.5,0.5) -> 0.5·a + 0.5·b + 0.5·c = (14, 6, 5) Å.
    assert frame.atoms.positions[0].tolist() == [14.0, 6.0, 5.0]
    assert frame.atoms.positions[1].tolist() == [0.0, 0.0, 0.0]


# --- streaming -----------------------------------------------------------------------


def test_streaming_single_pass_and_materialize_equivalence() -> None:
    stream = PARSER.parse_stream(io.BytesIO(_source("metal-ortho-declared")), filename="d.dump")
    obj, issues = materialize(stream)
    assert obj.frame_count == 2
    assert any(i.code == "LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED" for i in issues)
    # The stream is single-pass by contract.
    with pytest.raises(RuntimeError):
        list(stream.frames())


def test_sniff_identifies_dump_unambiguously() -> None:
    assert PARSER.sniff(b"ITEM: TIMESTEP\n0\n", "x.dump") == 1.0
    assert PARSER.sniff(b"ITEM: NUMBER OF ATOMS\n", "x.dump") == 0.0
    assert PARSER.sniff(b"1\nLattice=...", None) == 0.0


def test_empty_file_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(b""), filename="d.dump")
    assert exc.value.issues[0].code == "LAMMPSDUMP_EMPTY"


# --- capabilities / registration -----------------------------------------------------


def test_capabilities_declare_read_side_only() -> None:
    caps = PARSER.capabilities()
    assert caps.format_id == "lammps_dump"
    assert caps.direction == "read"
    assert caps.max_frames is None  # the point of the format: unbounded snapshots
    assert caps.fields["atoms.positions"].level.value == "full"
    assert caps.fields["cell.lattice_vectors"].level.value == "full"
    # Read side: absence is honoured, not required.
    assert caps.required_fields == []
