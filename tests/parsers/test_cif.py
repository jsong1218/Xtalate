"""CIF parser tests (M17): the four-stage reader, cell construction, fractional exactness,
block policy, carry-through, and the refusal contract (Part 3 §3; DECISIONS.md D65, D66)."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden, parse_bytes
from xtalate.parsers.cif import make_cif_parser
from xtalate.parsers.cif._build import element_of, lattice_from_parameters
from xtalate.sdk import ParseError, ParseResult

GOLDEN = Path(__file__).parent.parent / "golden" / "cif" / "zno-hexagonal-p1"

# Minimal well-formed P 1 cubic cell — the base every focused test mutates.
CUBIC = b"""data_cubic
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1 Na 0.0 0.0 0.0
Cl1 Cl 0.5 0.5 0.5
"""


def _parse(data: bytes, *, filename: str | None = "test.cif") -> ParseResult:
    return parse_bytes(make_cif_parser(), data, filename=filename)


# --- golden -------------------------------------------------------------------------------


def test_golden_hexagonal_matches_expectation() -> None:
    result = _parse((GOLDEN / "zno_hexagonal.cif").read_bytes(), filename="zno_hexagonal.cif")
    expected = (GOLDEN / "expected.canonical.json").read_text()
    assert_matches_golden(result.canonical, expected)


def test_fractional_to_cartesian_is_exact_against_hand_computation() -> None:
    """The M17 exactness anchor, computed by hand rather than by the code under test.

    For a=b=3, c=5, gamma=120 the lattice rows are a=(3,0,0), b=(-1.5, 3*sqrt(3)/2, 0),
    c=(0,0,5). Site O1 at fractional (1/3, 2/3, 1/2) is therefore
        x = 3/3 - 1.5*2/3      = 1.0 - 1.0        = 0
        y = 3*sqrt(3)/2 * 2/3  = sqrt(3)          = 1.7320508...
        z = 5/2                                   = 2.5
    """
    result = _parse((GOLDEN / "zno_hexagonal.cif").read_bytes())
    positions = result.canonical.frames[0].atoms.positions
    np.testing.assert_allclose(positions[0], [0.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(positions[1], [0.0, math.sqrt(3.0), 2.5], atol=1e-9)


def test_lattice_from_parameters_matches_standard_orientation() -> None:
    lattice = lattice_from_parameters((3.0, 3.0, 5.0), (90.0, 90.0, 120.0))
    np.testing.assert_allclose(lattice[0], [3.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(lattice[1], [-1.5, 3.0 * math.sqrt(3.0) / 2.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(lattice[2], [0.0, 0.0, 5.0], atol=1e-12)


def test_right_angles_give_exactly_zero_components() -> None:
    """A 90 degree angle means *exactly* orthogonal.

    Routing it through ``cos(radians(90))`` yields 6.1e-17, which both fabricates a tilt the
    source never declared (P1) and varies in its last bit between platforms, making any golden
    file built from it machine-dependent. Exact equality, not a tolerance, is the assertion.
    """
    lattice = lattice_from_parameters((3.0, 4.0, 5.0), (90.0, 90.0, 90.0))
    assert lattice.tolist() == [[3.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 5.0]]

    hexagonal = lattice_from_parameters((3.0, 3.0, 5.0), (90.0, 90.0, 120.0))
    assert hexagonal[1][0] == -1.5
    assert hexagonal[2].tolist() == [0.0, 0.0, 5.0]


def test_lattice_preserves_cell_lengths_and_angles() -> None:
    """Round-tripping parameters through the matrix is the orientation-independent check:
    whatever convention is chosen, the lengths and angles must come back unchanged."""
    lengths, angles = (4.1, 5.3, 6.7), (73.0, 88.0, 115.0)
    lattice = lattice_from_parameters(lengths, angles)
    got_lengths = [float(np.linalg.norm(row)) for row in lattice]
    np.testing.assert_allclose(got_lengths, lengths, atol=1e-9)
    pairs = ((1, 2), (0, 2), (0, 1))  # alpha is b^c, beta is a^c, gamma is a^b
    for (i, j), expected in zip(pairs, angles, strict=True):
        cos = float(
            lattice[i] @ lattice[j] / (np.linalg.norm(lattice[i]) * np.linalg.norm(lattice[j]))
        )
        assert math.degrees(math.acos(cos)) == pytest.approx(expected, abs=1e-9)


# --- block policy (Part 3 §3 n.4) ----------------------------------------------------------


def test_second_block_is_named_in_a_warning_not_silently_skipped() -> None:
    two_blocks = (
        CUBIC
        + b"""
data_second_structure
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
K1 K 0.0 0.0 0.0
"""
    )
    result = _parse(two_blocks)
    assert result.canonical.frames[0].atoms.symbols == ["Na", "Cl"]
    assert len(result.canonical.frames) == 1  # blocks are structures, never frames
    warnings = [i for i in result.issues if i.code == "CIF_ADDITIONAL_BLOCKS_NOT_READ"]
    assert len(warnings) == 1
    assert "second_structure" in warnings[0].message


def test_single_block_file_emits_no_block_warning() -> None:
    result = _parse(CUBIC)
    assert not [i for i in result.issues if i.code == "CIF_ADDITIONAL_BLOCKS_NOT_READ"]


# --- symmetry refusals (D66) ---------------------------------------------------------------


def test_space_group_symbol_without_operations_is_refused() -> None:
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_space_group_name_H-M_alt 'F m -3 m'\n")
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_UNEXPANDABLE_SYMMETRY"


def test_p1_symbol_without_operations_parses() -> None:
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_space_group_name_H-M_alt 'P 1'\n")
    result = _parse(data)
    assert result.canonical.frames[0].cell is not None
    assert result.canonical.frames[0].cell.space_group == "P 1"


def test_p_minus_1_is_not_treated_as_p1() -> None:
    # P -1 carries an inversion centre, so its sites are an asymmetric unit like any other
    # non-trivial group — the string similarity to 'P 1' must not leak into the check.
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_space_group_name_H-M_alt 'P -1'\n")
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_UNEXPANDABLE_SYMMETRY"


def test_non_identity_operations_expand_the_structure() -> None:
    # A site off any symmetry element: inversion genuinely doubles it. This is the base case the
    # milestone exists for — the atoms an asymmetric unit implies but does not list.
    data = CUBIC.replace(b"Cl1 Cl 0.5 0.5 0.5\n", b"Cl1 Cl 0.25 0.25 0.25\n").replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
        b"loop_\n_atom_site_label",
    )
    atoms = _parse(data).canonical.frames[0].atoms
    assert atoms.symbols == ["Na", "Cl", "Cl"]
    # The generated Cl sits at fractional (0.75, 0.75, 0.75) — 3.0 Å along each axis of a 4 Å cell.
    assert atoms.positions[2] == pytest.approx([3.0, 3.0, 3.0])


def test_identity_only_operation_loop_parses() -> None:
    data = CUBIC.replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\nloop_\n_atom_site_label",
    )
    assert _parse(data).canonical.frames[0].atoms.symbols == ["Na", "Cl"]


def test_legacy_symmetry_tag_spelling_is_expanded_too() -> None:
    # A file using the legacy _symmetry_equiv_pos_as_xyz spelling must expand exactly as the
    # modern one does; missing the alias would silently read an asymmetric unit as a full cell.
    data = CUBIC.replace(b"Cl1 Cl 0.5 0.5 0.5\n", b"Cl1 Cl 0.25 0.25 0.25\n").replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_symmetry_equiv_pos_as_xyz\n'x, y, z'\n'-x, -y, -z'\nloop_\n_atom_site_label",
    )
    assert _parse(data).canonical.frames[0].atoms.symbols == ["Na", "Cl", "Cl"]


def test_sites_on_a_symmetry_element_merge_rather_than_double() -> None:
    """Both CUBIC sites sit on inversion centres, so inversion adds no atoms at all.

    Multiplicity below the operation count is the whole reason the merge exists: without it this
    file would report four atoms where the crystal has two, which is the wrong-stoichiometry
    failure every other guard in this milestone is also aimed at.
    """
    data = CUBIC.replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
        b"loop_\n_atom_site_label",
    )
    result = _parse(data)
    assert result.canonical.frames[0].atoms.symbols == ["Na", "Cl"]
    note = next(n for n in result.canonical.provenance.parse_notes if "Symmetry expansion" in n)
    assert "Per-site multiplicities: [1, 1]" in note
    assert "2 coincident image(s) were merged" in note


def test_generated_coordinates_are_wrapped_but_declared_ones_are_not() -> None:
    """Wrapping is construction, not laundering of source data (DECISIONS.md D67 rule 3).

    The declared site at z=1.25 stays at 1.25 — rewriting it to 0.25 would be editing what the
    file said. Its inversion image has no source spelling to be faithful to, so it is placed in
    the unit cell as part of being constructed: -1.25 is reported at 0.75, not at -1.25.
    """
    data = CUBIC.replace(b"Cl1 Cl 0.5 0.5 0.5\n", b"Cl1 Cl 0.0 0.0 1.25\n").replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
        b"loop_\n_atom_site_label",
    )
    positions = _parse(data).canonical.frames[0].atoms.positions
    assert positions[1][2] == pytest.approx(5.0)  # declared 1.25 × 4 Å, carried verbatim
    assert positions[2][2] == pytest.approx(3.0)  # generated -1.25 → 0.75 × 4 Å


def test_per_site_columns_are_replicated_onto_generated_atoms() -> None:
    """Occupancy and label describe the site, so every atom it generates carries them."""
    data = CUBIC.replace(
        b"_atom_site_fract_z\nNa1 Na 0.0 0.0 0.0\nCl1 Cl 0.5 0.5 0.5\n",
        b"_atom_site_fract_z\n_atom_site_occupancy\n"
        b"Na1 Na 0.0 0.0 0.0 1.0\nCl1 Cl 0.25 0.25 0.25 0.5\n",
    ).replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
        b"loop_\n_atom_site_label",
    )
    per_atom = _parse(data).canonical.user_metadata.custom_per_atom
    assert list(per_atom["cif:atom_site_occupancy"]) == pytest.approx([1.0, 0.5, 0.5])
    assert list(per_atom["cif:atom_site_label"]) == ["Na1", "Cl1", "Cl1"]


def test_declared_operations_are_carried_verbatim() -> None:
    data = CUBIC.replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
        b"loop_\n_atom_site_label",
    )
    simulation = _parse(data).canonical.simulation
    assert simulation is not None
    assert simulation.extra["cif:symmetry_operations"] == "x, y, z\n-x, -y, -z"


def test_an_operation_loop_without_the_identity_is_refused() -> None:
    """Expanding without it would move every atom off the position the file declared."""
    data = CUBIC.replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_space_group_symop_operation_xyz\n'-x, -y, -z'\nloop_\n_atom_site_label",
    )
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_MALFORMED_SYMOP"


def test_cartesian_sites_with_real_symmetry_are_refused() -> None:
    """Operations are defined on fractional axes; applying them to Å would be nonsense."""
    data = (
        CUBIC.replace(b"_atom_site_fract_x", b"_atom_site_Cartn_x")
        .replace(b"_atom_site_fract_y", b"_atom_site_Cartn_y")
        .replace(b"_atom_site_fract_z", b"_atom_site_Cartn_z")
        .replace(
            b"loop_\n_atom_site_label",
            b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
            b"loop_\n_atom_site_label",
        )
    )
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_CARTESIAN_SITES_WITH_SYMMETRY"


# --- type-symbol laundering ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_symbol", "expected"),
    [("Fe", "Fe"), ("Fe3+", "Fe"), ("O2-", "O"), ("Ca+", "Ca"), ("na", "Na"), ("CL", "Cl")],
)
def test_type_symbol_oxidation_suffix_is_split_off(type_symbol: str, expected: str) -> None:
    assert element_of(type_symbol, None, line=1) == expected


@pytest.mark.parametrize("label", ["O1", "Fe2A", "Ca1_2", "H"])
def test_label_fallback_reads_leading_element_letters(label: str) -> None:
    assert element_of(None, label, line=1) == label[:2].rstrip("0123456789_").capitalize()


def test_unrecognisable_species_is_an_error_not_a_placeholder() -> None:
    data = CUBIC.replace(b"Na1 Na ", b"Xx1 Qq ")
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_INVALID_SYMBOL"


def test_raw_type_symbol_is_preserved_per_atom() -> None:
    data = CUBIC.replace(b"Na1 Na ", b"Na1 Na1+ ")
    result = _parse(data)
    assert result.canonical.frames[0].atoms.symbols == ["Na", "Cl"]
    assert result.canonical.user_metadata.custom_per_atom["cif:type_symbol"] == ["Na1+", "Cl"]


# --- carry-through (P1) --------------------------------------------------------------------


def test_unmapped_atom_site_columns_are_carried_verbatim() -> None:
    result = _parse((GOLDEN / "zno_hexagonal.cif").read_bytes())
    carried = result.canonical.user_metadata.custom_per_atom
    # A wholly-numeric column lands as a float array, a textual one as strings — the schema's
    # custom_per_atom union decides, and either way the source value is preserved.
    np.testing.assert_allclose(np.asarray(carried["cif:atom_site_occupancy"]), [1.0, 1.0])
    assert carried["cif:atom_site_label"] == ["Zn1", "O1"]
    assert carried["cif:type_symbol"] == ["Zn", "O"]


def test_bibliographic_tags_are_carried_into_simulation_extra() -> None:
    result = _parse((GOLDEN / "zno_hexagonal.cif").read_bytes())
    assert result.canonical.simulation is not None
    extra = result.canonical.simulation.extra
    assert extra["cif:publ_author_name"] == "Xtalate test corpus"
    assert extra["cif:chemical_formula_sum"] == "Zn O"
    assert [i for i in result.issues if i.code == "CIF_TAGS_CARRIED"]


def test_pbc_is_recorded_as_format_defined_not_assumed() -> None:
    result = _parse(CUBIC)
    cell = result.canonical.frames[0].cell
    assert cell is not None and cell.pbc == (True, True, True)
    assert any("format-defined" in note for note in result.canonical.provenance.parse_notes)


def test_original_coordinate_system_records_fractional() -> None:
    result = _parse(CUBIC)
    assert result.canonical.provenance.original_coordinate_system == "fractional"
    assert result.canonical.provenance.source_units["positions"] == "fractional"


def test_cartesian_atom_sites_are_read_without_conversion() -> None:
    data = CUBIC.replace(b"_atom_site_fract_", b"_atom_site_Cartn_")
    result = _parse(data)
    np.testing.assert_allclose(
        result.canonical.frames[0].atoms.positions[1], [0.5, 0.5, 0.5], atol=1e-12
    )
    assert result.canonical.provenance.original_coordinate_system == "cartesian"


# --- syntax ---------------------------------------------------------------------------------


def test_semicolon_text_field_is_read_as_one_value() -> None:
    data = CUBIC.replace(
        b"data_cubic\n",
        b"data_cubic\n_publ_section_title\n;\nA long title\nspanning two lines\n;\n",
    )
    result = _parse(data)
    assert result.canonical.simulation is not None
    assert (
        result.canonical.simulation.extra["cif:publ_section_title"]
        == "A long title\nspanning two lines"
    )


def test_quoted_value_containing_an_apostrophe_survives() -> None:
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_publ_author_name 'O'Brien, K'\n")
    result = _parse(data)
    assert result.canonical.simulation is not None
    assert result.canonical.simulation.extra["cif:publ_author_name"] == "O'Brien, K"


def test_comments_are_ignored() -> None:
    data = b"# leading comment\n" + CUBIC.replace(b"_cell_length_a 4.0", b"_cell_length_a 4.0 # a")
    assert _parse(data).canonical.frames[0].atoms.symbols == ["Na", "Cl"]


def test_case_insensitive_tags_are_recognised() -> None:
    data = CUBIC.replace(b"_cell_length_a", b"_Cell_Length_A")
    cell = _parse(data).canonical.frames[0].cell
    assert cell is not None
    np.testing.assert_allclose(cell.lattice_vectors[0], [4.0, 0.0, 0.0], atol=1e-12)


def test_standard_uncertainty_is_read_as_the_value_and_noted() -> None:
    data = CUBIC.replace(b"_cell_length_a 4.0", b"_cell_length_a 4.0(3)")
    result = _parse(data)
    cell = result.canonical.frames[0].cell
    assert cell is not None
    np.testing.assert_allclose(cell.lattice_vectors[0], [4.0, 0.0, 0.0], atol=1e-12)


def test_bare_question_mark_is_absence_not_a_value() -> None:
    # '?' means "unknown"; treating it as the literal string would smuggle a fake value into
    # simulation.extra and violate the absence convention (P3).
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_chemical_name_common ?\n")
    result = _parse(data)
    extra = result.canonical.simulation.extra if result.canonical.simulation else {}
    assert "cif:chemical_name_common" not in extra


def test_quoted_question_mark_is_a_literal_value() -> None:
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_chemical_name_common '?'\n")
    result = _parse(data)
    assert result.canonical.simulation is not None
    assert result.canonical.simulation.extra["cif:chemical_name_common"] == "?"


# --- error contract (M17 deliverable 6) ------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda d: b"# a comment and nothing else\n", "CIF_NO_DATA_BLOCK"),
        (lambda d: d.replace(b"_cell_length_a 4.0\n", b""), "CIF_MISSING_CELL"),
        (
            lambda d: d.replace(b"_cell_length_a 4.0", b"_cell_length_a four"),
            "CIF_MALFORMED_NUMBER",
        ),
        (lambda d: d.replace(b"_cell_length_a 4.0", b"_cell_length_a -4.0"), "CIF_INVALID_CELL"),
        (
            lambda d: d.replace(b"_cell_angle_alpha 90.0", b"_cell_angle_alpha 180.0"),
            "CIF_INVALID_CELL",
        ),
        # Renamed rather than deleted, so the loop keeps its column count: dropping the tag
        # outright makes the loop ragged, which is a syntax error one stage earlier.
        (
            lambda d: d.replace(b"_atom_site_fract_z", b"_atom_site_U_iso_or_equiv"),
            "CIF_INCOMPLETE_COORDINATES",
        ),
        (
            lambda d: d.replace(b"Na1 Na 0.0 0.0 0.0\nCl1 Cl 0.5 0.5 0.5\n", b""),
            "CIF_EMPTY_ATOM_SITES",
        ),
        (lambda d: d.replace(b"0.5 0.5 0.5", b"0.5 0.5 ?"), "CIF_MISSING_COORDINATE"),
    ],
)
def test_error_fixtures_raise_structured_parse_errors(
    mutation: Callable[[bytes], bytes], code: str
) -> None:
    with pytest.raises(ParseError) as exc:
        _parse(mutation(CUBIC))
    assert exc.value.issues[0].code == code
    assert exc.value.issues[0].severity == "error"


def test_unterminated_text_field_is_a_syntax_error() -> None:
    data = CUBIC.replace(b"data_cubic\n", b"data_cubic\n_publ_section_title\n;\nno closing\n")
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_SYNTAX_ERROR"


def test_ragged_loop_is_a_syntax_error() -> None:
    data = CUBIC + b"Na2 Na 0.1\n"
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_SYNTAX_ERROR"


def test_tag_before_any_data_block_is_a_syntax_error() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(b"_cell_length_a 4.0\n")
    assert exc.value.issues[0].code == "CIF_SYNTAX_ERROR"


def test_missing_species_columns_are_refused() -> None:
    data = (
        CUBIC.replace(b"_atom_site_label\n_atom_site_type_symbol\n", b"")
        .replace(b"Na1 Na ", b"")
        .replace(b"Cl1 Cl ", b"")
    )
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_MISSING_SPECIES"


def test_parse_errors_carry_a_source_location() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(CUBIC.replace(b"_cell_length_a 4.0", b"_cell_length_a four"))
    assert exc.value.issues[0].location is not None


# --- sniffing -------------------------------------------------------------------------------


def test_sniff_recognises_cif_by_name_and_content() -> None:
    assert make_cif_parser().sniff(CUBIC, "structure.cif") == 1.0


def test_sniff_recognises_cif_without_a_filename() -> None:
    assert make_cif_parser().sniff(CUBIC, None) >= 0.9


def test_sniff_rejects_a_data_heading_without_cif_tags() -> None:
    assert make_cif_parser().sniff(b"data_something\nnot a cif at all\n", None) == 0.0


def test_sniff_rejects_other_formats() -> None:
    parser = make_cif_parser()
    assert parser.sniff(b"2\ncomment\nH 0 0 0\nH 0 0 1\n", "water.xyz") == 0.0
