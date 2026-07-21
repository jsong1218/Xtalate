"""CIF exporter tests: the `P 1` export policy (D68) and the two boundary conversions (M19).

The policy tests are the ones with teeth. Writing a source's space-group symbol above an atom
list the parser has already expanded produces a file whose header and body describe different
structures — four times the atoms, if a standards-compliant reader honours the header — so the
symbol's *absence* from the output, and its presence in the report's `removed` list, are asserted
directly rather than inferred from a round-trip passing.

The conversions (Cartesian → fractional, lattice vectors → cell parameters) are exact inverses of
what the parser does on the way in, so they are checked against hand-computed values, not against
the parser: a sign error shared by both directions would round-trip perfectly and still be wrong.
"""

from __future__ import annotations

import io
import math
import pathlib

import numpy as np
import pytest
from pydantic import JsonValue

from xtalate.conversion import ConversionEngine
from xtalate.conversion.preflight import build_preflight
from xtalate.exporters.cif import make_cif_exporter
from xtalate.parsers._common import build_provenance
from xtalate.registry import default_registry
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    SimulationMetadata,
    UserMetadata,
)
from xtalate.schema.arrays import ArrayNx
from xtalate.schema.cell import cell_parameters, lattice_from_parameters
from xtalate.schema.paths import OCCUPANCY_CUSTOM_KEY

_REGISTRY = default_registry()
_EXPORTER = make_cif_exporter()


def _object(
    *,
    symbols: list[str] | None = None,
    positions: np.ndarray | None = None,
    lattice: np.ndarray | None = None,
    space_group: str | None = None,
    custom_per_atom: dict[str, ArrayNx | list[JsonValue]] | None = None,
    custom_global: dict[str, JsonValue] | None = None,
    extra: dict[str, str] | None = None,
    n_frames: int = 1,
) -> CanonicalObject:
    symbols = symbols if symbols is not None else ["Na", "Cl"]
    positions = positions if positions is not None else np.array([[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]])
    lattice = lattice if lattice is not None else np.eye(3) * 4.0
    return CanonicalObject(
        frames=[
            Frame(
                index=i,
                atoms=AtomsBlock(symbols=symbols, positions=positions),
                cell=Cell(lattice_vectors=lattice, pbc=(True, True, True), space_group=space_group),
            )
            for i in range(n_frames)
        ],
        simulation=SimulationMetadata(extra=extra) if extra else None,
        user_metadata=UserMetadata(
            custom_global=custom_global or {}, custom_per_atom=custom_per_atom or {}
        ),
        provenance=build_provenance(
            format_id="test",
            filename=None,
            original_coordinate_system="cartesian",
            source_units={},
            parse_notes=[],
        ),
    )


def _write(obj: CanonicalObject) -> str:
    buffer = io.BytesIO()
    _EXPORTER.export(obj, buffer)
    return buffer.getvalue().decode()


def _reparse(text: str) -> CanonicalObject:
    return _REGISTRY.get_parser("cif").parse(io.BytesIO(text.encode()), filename=None).canonical


# --------------------------------------------------------------------------------------------
# D68 — the export symmetry policy
# --------------------------------------------------------------------------------------------


def test_no_space_group_symbol_is_written() -> None:
    # The whole of D68 in one assertion. Not "the source symbol is not echoed" — *no* symbol,
    # including 'P 1'. A symbol is a value in a canonical field, and one Xtalate supplied would
    # make the output assert what no input stated.
    text = _write(_object(space_group="Fm-3m"))
    assert "_space_group_name" not in text
    assert "_symmetry_space_group_name" not in text
    assert "Fm-3m" not in text


def test_the_identity_operation_is_written_explicitly() -> None:
    # Silence about symmetry is not the same claim. The loop states positively that nothing is to
    # be applied, which is what makes the explicit atom list beneath it complete rather than
    # possibly an asymmetric unit — the ambiguity D66 refuses to read on the way in.
    text = _write(_object())
    assert "_space_group_symop_operation_xyz" in text
    assert "'x, y, z'" in text


def test_the_source_symbol_is_reported_removed() -> None:
    diff = build_preflight(_object(space_group="Fm-3m"), _REGISTRY.capability_matrix(), "cif")
    entry = next(e for e in diff.removed if e.path == "cell.space_group")
    assert "D68" in entry.reason


def test_reparsing_the_output_recovers_no_space_group() -> None:
    # The property-harness invariant, pinned locally: a path the report calls removed must not
    # reappear in the re-parsed output. Writing 'P 1' would fail exactly here.
    cell = _reparse(_write(_object(space_group="Fm-3m"))).frames[0].cell
    assert cell is not None
    assert cell.space_group is None


def test_declared_symmetry_operations_are_not_written_back() -> None:
    # simulation.extra['cif:symmetry_operations'] holds what the *source* declared. Re-emitting it
    # above an already-expanded atom list would have the next reader expand the structure a second
    # time — the same false assertion as echoing the symbol, one hop later.
    text = _write(_object(extra={"cif:symmetry_operations": "x, y, z\n-x, -y, -z"}))
    assert "-x, -y, -z" not in text


# --------------------------------------------------------------------------------------------
# D72 — the space group is not re-asserted through a carried tag either
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag",
    [
        "space_group_it_number",
        "symmetry_int_tables_number",
        "cod_original_sg_symbol_h-m",
        "space_group_name_h-m_alt",
    ],
)
def test_a_carried_tag_identifying_a_space_group_is_not_written_back(tag: str) -> None:
    # D68 withholds the H-M symbol so the written file cannot claim a setting its expanded
    # coordinates no longer encode. A space group is identified just as completely by its
    # International Tables *number* — 225 is Fm-3m — or by a database's own symbol spelling, and
    # those rode through simulation.extra and were written back, restoring the exact assertion
    # D68 removed. A reader honouring one expands an already-expanded cell.
    text = _write(_object(extra={f"cif:{tag}": "225"}))
    assert f"_{tag}" not in text


def test_a_carried_tag_naming_only_the_crystal_system_is_kept() -> None:
    # The counter-case, so the suppression is a rule and not a blanket. 'cubic' describes the
    # cell, which the written file reproduces unchanged, and no operation set follows from it —
    # so withholding it would be dropping a true statement, which is its own kind of dishonesty.
    text = _write(_object(extra={"cif:symmetry_cell_setting": "cubic"}))
    assert "_symmetry_cell_setting  cubic" in text


def test_a_real_cod_file_round_trips_with_no_space_group_assertion() -> None:
    # The end-to-end form, on the file that exposed this. The unit tests above pin the predicate;
    # this pins the artifact, which is what a user actually gets. Asserted over the output bytes
    # because every in-memory check passed while the file on disk still said 225.
    source = pathlib.Path("tests/wild/cod/nacl-legacy-symmetry-tags/cod-1000041.cif")
    canonical = _REGISTRY.get_parser("cif").parse(
        io.BytesIO(source.read_bytes()), filename=source.name
    )
    text = _write(canonical.canonical)
    assert "_space_group_symop_operation_xyz" in text  # the identity loop is still written
    assert "225" not in text
    assert "F m -3 m" not in text
    assert "-F 4 2 3" not in text  # the Hall symbol
    assert _reparse(text).frames[0].cell.space_group is None  # type: ignore[union-attr]


def test_every_atom_is_listed_explicitly() -> None:
    positions = np.arange(24, dtype=float).reshape(8, 3)
    obj = _object(symbols=["Na"] * 4 + ["Cl"] * 4, positions=positions)
    assert len(_reparse(_write(obj)).frames[0].atoms.symbols) == 8


# --------------------------------------------------------------------------------------------
# The boundary conversions
# --------------------------------------------------------------------------------------------


def test_cell_parameters_of_a_cubic_cell() -> None:
    lengths, angles = cell_parameters(np.eye(3) * 4.0)
    assert lengths == pytest.approx((4.0, 4.0, 4.0))
    assert angles == pytest.approx((90.0, 90.0, 90.0))


def test_cell_parameters_of_a_hand_computed_triclinic_cell() -> None:
    # a along x; b at 60° to a in the xy-plane; c hand-placed so alpha and beta are checkable
    # independently of the parser's own construction.
    lattice = np.array([[3.0, 0.0, 0.0], [2.0 * 0.5, 2.0 * math.sqrt(3) / 2, 0.0], [0.0, 0.0, 5.0]])
    lengths, angles = cell_parameters(lattice)
    assert lengths == pytest.approx((3.0, 2.0, 5.0))
    # alpha = angle(b, c) = 90 (b is in the xy-plane, c is along z); beta = angle(a, c) = 90;
    # gamma = angle(a, b) = 60 by construction.
    assert angles == pytest.approx((90.0, 90.0, 60.0))


def test_cell_parameters_invert_the_parser_construction() -> None:
    # The two directions must compose to the identity on *parameters*, which is the invariant that
    # survives the orientation convention: the lattice matrix is convention-dependent, a, b, c,
    # alpha, beta, gamma are not.
    lengths, angles = (5.0, 6.0, 7.0), (80.0, 95.0, 110.0)
    got_lengths, got_angles = cell_parameters(lattice_from_parameters(lengths, angles))
    assert got_lengths == pytest.approx(lengths)
    assert got_angles == pytest.approx(angles)


@pytest.mark.parametrize("gamma", [30.0, 60.0, 90.0, 120.0, 150.0])
def test_the_standard_angles_invert_exactly_not_approximately(gamma: float) -> None:
    # Equality, deliberately, where the test above uses approx. The parser keeps a table of exact
    # cosines for these angles because cos(radians(90)) is 6.1e-17 and a lattice built through it
    # carries a tilt the source never declared. That table buys nothing if the return trip hands
    # back 120.00000000000001, which misses it on the next read — so CIF→CIF was not idempotent
    # for any hexagonal, trigonal or rhombohedral cell (D73). approx would not have caught it.
    _, angles = cell_parameters(lattice_from_parameters((4.0, 4.0, 6.0), (90.0, 90.0, gamma)))
    assert angles == (90.0, 90.0, gamma)


def test_a_hexagonal_cell_is_a_fixed_point_of_the_cif_round_trip() -> None:
    # The artifact-level form: the exported bytes, re-read and re-exported, must not drift. This
    # is the failure a user sees — a 120° cell that is 120.00000000000001° one hop later.
    source = pathlib.Path("tests/golden/cif/zno-hexagonal-p1/zno_hexagonal.cif")
    once = _write(
        _REGISTRY.get_parser("cif")
        .parse(io.BytesIO(source.read_bytes()), filename=source.name)
        .canonical
    )
    assert "_cell_angle_gamma  120.0\n" in once
    assert _write(_reparse(once)) == once


def test_positions_are_written_as_fractional_coordinates() -> None:
    # A 4 Å cubic cell: the Cartesian (2, 2, 2) atom is at fractional (0.5, 0.5, 0.5).
    text = _write(_object())
    assert "0.5  0.5  0.5" in text


def test_cartesian_positions_survive_the_round_trip() -> None:
    lattice = lattice_from_parameters((5.0, 6.0, 7.0), (80.0, 95.0, 110.0))
    positions = np.array([[0.0, 0.0, 0.0], [1.25, 2.5, 3.75]])
    obj = _object(positions=positions, lattice=lattice)
    got = _reparse(_write(obj)).frames[0].atoms.positions
    # Tight but not exact: the Cartesian → fractional → Cartesian trip is one solve and one
    # multiply, so a few ulp of inversion error is the declared representational bound.
    assert got == pytest.approx(positions, abs=1e-9)


# --------------------------------------------------------------------------------------------
# Carry-through and the contract guards
# --------------------------------------------------------------------------------------------


def test_occupancy_is_written_back_to_its_atom_site_column() -> None:
    obj = _object(custom_per_atom={OCCUPANCY_CUSTOM_KEY: [0.5, 1.0]})
    text = _write(obj)
    assert "_atom_site_occupancy" in text
    assert _reparse(text).user_metadata.custom_per_atom[OCCUPANCY_CUSTOM_KEY] == pytest.approx(
        [0.5, 1.0]
    )


def test_cif_suppresses_the_partial_occupancy_warning() -> None:
    # The P6 hook M19 slice 2 built, now exercised by a real format rather than a stub: CIF names
    # 'cif:occupancy' in writable_custom_keys, so it *represents* occupancy and the warning that
    # fires for all six other targets does not fire here. No edit to the pre-flight diff was
    # needed to make this happen.
    obj = _object(custom_per_atom={OCCUPANCY_CUSTOM_KEY: [0.5, 1.0]})
    diff = build_preflight(obj, _REGISTRY.capability_matrix(), "cif")
    assert "PARTIAL_OCCUPANCY_NOT_REPRESENTED" not in [w.code for w in diff.warnings]


def test_unknown_occupancy_is_written_back_as_unknown() -> None:
    # '?' in, '?' out (P3). Writing 1.0 for an occupancy the source said was unknown would turn
    # its silence into an assertion.
    #
    # `None`, not the string "?", because that is what the parser actually produces: `_resolve`
    # maps the bare marker to `None` on the way in. This fixture used to say "?" and passed for
    # the wrong reason — the bare `?` it asserted came from `_quote` failing to quote a literal
    # (the defect below), not from the absence convention it claims to be testing.
    text = _write(_object(custom_per_atom={OCCUPANCY_CUSTOM_KEY: [None, "1.0"]}))
    assert "  ?" in text
    assert _reparse(text).user_metadata.custom_per_atom[OCCUPANCY_CUSTOM_KEY][0] is None


def test_a_literal_question_mark_is_quoted_so_it_stays_a_value() -> None:
    # The other half of the same distinction. A bare `?` is CIF's *unknown* marker; a source that
    # wrote `'?'` in quotes stated a one-character string. Writing the literal bare collapsed the
    # two, turning a value the source stated into an absence — and `Token.quoted` exists on the
    # read side precisely to keep them apart, so throwing it away on write forfeited that work.
    text = _write(_object(custom_per_atom={"cif:atom_site_label": ["?", "Cl1"]}))
    assert "  '?'  " in text
    assert _reparse(text).user_metadata.custom_per_atom["cif:atom_site_label"] == ["?", "Cl1"]


def test_an_all_unknown_column_falls_back_per_atom_not_per_column() -> None:
    # `or` tests truthiness, and [None, None] is a non-empty list — so the column-level fallback
    # never fired and every atom was written `?` while atoms.symbols held good elements. A source
    # whose _atom_site_type_symbol was `?` on every row is exactly that case.
    text = _write(_object(custom_per_atom={"cif:type_symbol": [None, None]}))
    assert "  Na1  Na  " in text
    assert "  Cl1  Cl  " in text


def test_a_partly_unknown_column_keeps_the_rows_the_source_stated() -> None:
    # The reason the fallback is per atom rather than "use the column only if it is all present":
    # a source that spelled the oxidation state for one site and not the other must get its own
    # spelling back where it made one, and the derived element where it did not.
    text = _write(_object(custom_per_atom={"cif:type_symbol": ["Na1+", None]}))
    assert "  Na1  Na1+  " in text
    assert "  Cl1  Cl  " in text


def test_source_site_labels_are_preserved() -> None:
    obj = _object(custom_per_atom={"cif:atom_site_label": ["Na1a", "Cl1b"]})
    assert _reparse(_write(obj)).user_metadata.custom_per_atom["cif:atom_site_label"] == [
        "Na1a",
        "Cl1b",
    ]


def test_labels_are_generated_when_the_source_carries_none() -> None:
    # CIF keys its site rows on the label, so one must exist; an identifier asserts nothing about
    # the structure, which is why generating it is not a P4 fabrication.
    obj = _object(symbols=["Na", "Na", "Cl"], positions=np.zeros((3, 3)))
    assert _reparse(_write(obj)).user_metadata.custom_per_atom["cif:atom_site_label"] == [
        "Na1",
        "Na2",
        "Cl1",
    ]


def test_the_oxidation_state_suffix_of_a_type_symbol_survives() -> None:
    obj = _object(custom_per_atom={"cif:type_symbol": ["Na1+", "Cl1-"]})
    reparsed = _reparse(_write(obj))
    assert reparsed.user_metadata.custom_per_atom["cif:type_symbol"] == ["Na1+", "Cl1-"]
    assert reparsed.frames[0].atoms.symbols == ["Na", "Cl"]


def test_bibliographic_tags_are_written_back() -> None:
    obj = _object(extra={"cif:chemical_name_common": "rock salt", "cif:journal_year": "1963"})
    reparsed = _reparse(_write(obj))
    assert reparsed.simulation is not None
    assert reparsed.simulation.extra["cif:chemical_name_common"] == "rock salt"
    assert reparsed.simulation.extra["cif:journal_year"] == "1963"


def test_a_value_containing_a_newline_is_written_as_a_text_field() -> None:
    # The semicolon form is the only CIF value spelling with no escape sequence, so it is the one
    # that can hold an arbitrary string verbatim.
    obj = _object(extra={"cif:publ_section_title": "a title\nover two lines"})
    reparsed = _reparse(_write(obj))
    assert reparsed.simulation is not None
    assert reparsed.simulation.extra["cif:publ_section_title"] == "a title\nover two lines"


def test_the_data_block_name_round_trips() -> None:
    obj = _object(custom_global={"cif:data_block_name": "rocksalt"})
    assert _reparse(_write(obj)).user_metadata.custom_global["cif:data_block_name"] == "rocksalt"


@pytest.mark.parametrize("name", ["my structure", "", "  ", "two\ttabs"])
def test_a_block_name_the_grammar_cannot_spell_is_refused_not_truncated(name: str) -> None:
    # writable_custom_keys declares cif:data_block_name writable, so the pre-flight reports it
    # *preserved* — and the writer took name.split()[0], so "my structure" became `data_my`. The
    # report claimed preservation of a value the artifact did not carry. That is worse than the
    # over-declarations D69 fixed: those dropped a value, this substituted a different one.
    # Refusing is D66's answer — decline rather than emit a file that disagrees with its report.
    with pytest.raises(ValueError, match="data-block heading"):
        _write(_object(custom_global={"cif:data_block_name": name}))


def test_a_missing_block_name_is_synthesized_not_refused() -> None:
    # Absence is not a defect: a structure arriving from POSCAR never had a block name, and CIF
    # requires a heading. Only a *stated* name this grammar cannot spell is refused.
    assert _write(_object()).startswith("data_xtalate")


def test_a_legal_block_name_survives_whole() -> None:
    # The regression the truncation would show up as: a legal multi-token-looking name is not
    # clipped, and re-parsing recovers it byte for byte.
    obj = _object(custom_global={"cif:data_block_name": "cod_1000041_phase2"})
    assert _write(obj).startswith("data_cod_1000041_phase2\n")
    assert (
        _reparse(_write(obj)).user_metadata.custom_global["cif:data_block_name"]
        == "cod_1000041_phase2"
    )


def test_a_multi_frame_object_is_refused_rather_than_truncated() -> None:
    # Reducing a trajectory to one structure is the Conversion Engine's recorded choice, never an
    # exporter's silent one (Part 4 §3).
    with pytest.raises(ValueError, match="frame_selection"):
        _write(_object(n_frames=3))


def test_an_object_with_no_cell_is_refused() -> None:
    obj = _object()
    obj.frames[0].cell = None
    with pytest.raises(ValueError, match="missing_lattice"):
        _write(obj)


def test_a_conversion_to_cif_completes_with_a_report() -> None:
    result = ConversionEngine(_REGISTRY).convert(
        _object(space_group="Fm-3m"),
        source_format_id="cif",
        target_format_id="cif",
        mode="permissive",
    )
    assert result.report.status == "completed"
    assert result.output is not None
    assert any(e.path == "cell.space_group" for e in result.report.removed)
