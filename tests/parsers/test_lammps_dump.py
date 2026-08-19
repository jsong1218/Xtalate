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
    # M46-S3 proof fixtures: the wrapped+flags case fires the specific image-flag warning
    # (never the generic unmapped-column one); the xu counterpart carries no flags at all.
    "wrapped-flags-metal": ["LAMMPSDUMP_IMAGE_FLAGS_CARRIED"],
    "xu-counterpart-metal": [],
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
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS\nmetal\n", b"")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(undeclared), filename="dump.lammpstrj")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDUMP_AMBIGUOUS_UNITS"
    assert issue.recovery_hint == "ambiguous_units"


def test_undeclared_units_recover_under_a_chosen_style() -> None:
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS\nmetal\n", b"")
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
    undeclared = _source("metal-ortho-declared").replace(b"ITEM: UNITS\nmetal\n", b"")
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
    lj = _source("metal-ortho-declared").replace(b"ITEM: UNITS\nmetal\n", b"ITEM: UNITS\nlj\n")
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


def test_image_flags_carried_specifically_and_never_applied() -> None:
    """M46-S3: a complete ix/iy/iz family is a specific, named carry — distinct from the
    generic unmapped-column path — and the flags are never applied on parse (D43)."""
    result = _parse("wrapped-flags-metal")
    codes = [i.code for i in result.issues]
    assert "LAMMPSDUMP_IMAGE_FLAGS_CARRIED" in codes
    assert "LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED" not in codes
    carried = result.canonical.user_metadata.custom_per_atom["lammps_dump:image_flags"]
    assert np.asarray(carried).tolist() == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    # The positions stay wrapped — the parser never unwraps (D43); atom 2 is at (0.5,0.5,0.5),
    # not (10.5,0.5,0.5).
    assert result.canonical.frames[0].atoms.positions[1].tolist() == [0.5, 0.5, 0.5]


def test_image_flags_warning_states_the_coordinate_convention() -> None:
    result = _parse("wrapped-flags-metal")
    warning = next(i for i in result.issues if i.code == "LAMMPSDUMP_IMAGE_FLAGS_CARRIED")
    assert "wrapped Cartesian (x/y/z)" in warning.message
    assert "unwrapping is reconstructable at frame 0" in warning.message
    assert "only frame 0's flags are retained" in warning.message
    assert "never applied on parse (D43)" in warning.message


def test_partial_image_flag_family_is_malformed() -> None:
    dump = _source("wrapped-flags-metal")
    dump = dump.replace(
        b"ITEM: ATOMS id element x y z ix iy iz", b"ITEM: ATOMS id element x y z ix"
    )
    dump = dump.replace(b"1 Si 1.0 2.0 3.0 0 0 0", b"1 Si 1.0 2.0 3.0 0")
    dump = dump.replace(b"2 O 0.5 0.5 0.5 1 0 0", b"2 O 0.5 0.5 0.5 1")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    assert "partial image-flag family" in exc.value.issues[0].message


def test_xu_counterpart_carries_no_image_flags() -> None:
    result = _parse("xu-counterpart-metal")
    assert "lammps_dump:image_flags" not in result.canonical.user_metadata.custom_per_atom
    assert all(i.code != "LAMMPSDUMP_IMAGE_FLAGS_CARRIED" for i in result.issues)


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


def test_upload_reference_applies_per_atom_symbols_when_atoms_exceed_types() -> None:
    """Finding 2: the reference supplies one symbol per *atom*, not one per distinct type. A dump
    with more atoms than distinct types (3 atoms, types 1/2/1) must resolve — the earlier
    index-keyed mapping refused any dump whose atom count exceeded its type count."""
    src = (
        b"ITEM: UNITS\nmetal\n"
        b"ITEM: TIMESTEP\n0\n"
        b"ITEM: NUMBER OF ATOMS\n3\n"
        b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
        b"ITEM: ATOMS id type x y z\n1 1 1.0 2.0 3.0\n2 2 4.0 5.0 6.0\n3 1 7.0 8.0 9.0\n"
    )
    # Build a matching 3-atom reference (Si, O, Si) via the species-map path, then upload it.
    reference = PARSER.parse_recover(
        io.BytesIO(src),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "1:Si 2:O"},
    ).canonical
    assert reference.frames[0].atoms.symbols == ["Si", "O", "Si"]
    recovered = PARSER.parse_recover(
        io.BytesIO(src),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="upload_reference",
        parameters={"reference": reference},
    )
    assert recovered.canonical.frames[0].atoms.symbols == ["Si", "O", "Si"]


def test_upload_reference_atom_count_mismatch_refuses() -> None:
    """A reference whose atom count does not match the dump cannot supply per-atom symbols."""
    src = _source("typed-atoms-metal")  # 2 atoms
    three_atom_ref = PARSER.parse_recover(
        io.BytesIO(
            b"ITEM: UNITS\nmetal\n"
            b"ITEM: TIMESTEP\n0\n"
            b"ITEM: NUMBER OF ATOMS\n3\n"
            b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
            b"ITEM: ATOMS id type x y z\n1 1 1.0 2.0 3.0\n2 2 4.0 5.0 6.0\n3 1 7.0 8.0 9.0\n"
        ),
        filename="dump.lammpstrj",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "1:Si 2:O"},
    ).canonical
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src),
            filename="dump.lammpstrj",
            hint="supply_species",
            choice="upload_reference",
            parameters={"reference": three_atom_ref},
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


# --- id-order alignment (finding 1) --------------------------------------------------


def test_unsorted_dump_is_realigned_by_id_with_a_warning() -> None:
    """A dump written without `dump_modify sort id` lists atoms in arbitrary order. The parser
    sorts each frame by ascending id so the per-atom arrays line up, warns once, and never
    changes the atoms themselves."""
    dump = _source("metal-ortho-declared").replace(
        b"1 Si 1.0 2.0 3.0 0.1 0.2 0.3 5.0\n2 O 4.0 5.0 6.0 -0.1 -0.2 -0.3 6.0\n",
        b"2 O 4.0 5.0 6.0 -0.1 -0.2 -0.3 6.0\n1 Si 1.0 2.0 3.0 0.1 0.2 0.3 5.0\n",
    )
    result = PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    # Reordered back into id order: Si (id 1) precedes O (id 2), positions follow the id.
    assert result.canonical.frames[0].atoms.symbols == ["Si", "O"]
    assert result.canonical.frames[0].atoms.positions[0].tolist() == [1.0, 2.0, 3.0]
    warning = next(i for i in result.issues if i.code == "LAMMPSDUMP_ATOMS_REORDERED")
    assert "sorted by ascending atom id" in warning.message
    assert "only reordered" in warning.message


def test_inconsistent_atom_ids_across_frames_refuse() -> None:
    """Constant N is not constant identity: frames with the same count but different id sets are
    not the same atoms, so the trajectory is refused rather than silently aligned by row."""
    dump = _source("metal-ortho-declared").replace(
        b"1 Si 1.5 2.5 3.5 0.11 0.21 0.31 5.0",
        b"3 Si 1.5 2.5 3.5 0.11 0.21 0.31 5.0",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    assert exc.value.issues[0].code == "LAMMPSDUMP_VARIABLE_ATOM_IDENTITY"


# --- ITEM: TIME carry-through (finding 5) --------------------------------------------


def test_item_time_preamble_carried_per_frame() -> None:
    """`dump_modify time yes` writes a two-line `ITEM: TIME` block before each `ITEM: TIMESTEP`.
    The wall-clock time is not a canonical dt, so it rides verbatim per frame (P3)."""
    dump = (
        b"ITEM: UNITS\nmetal\n"
        b"ITEM: TIME\n0.005\n"
        b"ITEM: TIMESTEP\n0\n"
        b"ITEM: NUMBER OF ATOMS\n2\n"
        b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
        b"ITEM: ATOMS id element x y z\n1 Si 1.0 2.0 3.0\n2 O 4.0 5.0 6.0\n"
        b"ITEM: TIME\n0.010\n"
        b"ITEM: TIMESTEP\n10\n"
        b"ITEM: NUMBER OF ATOMS\n2\n"
        b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
        b"ITEM: ATOMS id element x y z\n1 Si 1.5 2.5 3.5\n2 O 4.0 5.0 6.0\n"
    )
    result = PARSER.parse(io.BytesIO(dump), filename="dump.lammpstrj")
    assert result.canonical.frame_count == 2
    times = result.canonical.user_metadata.custom_per_frame["lammps_dump:time"]
    assert np.asarray(times).tolist() == [0.005, 0.010]
    # The declared step numbers still ride alongside — TIME does not replace TIMESTEP.
    steps = result.canonical.user_metadata.custom_per_frame["lammps_dump:timestep"]
    assert np.asarray(steps).tolist() == [0.0, 10.0]


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
