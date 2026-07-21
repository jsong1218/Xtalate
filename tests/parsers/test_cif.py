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
from xtalate.parsers.cif._build import charge_of_type_symbol, element_of
from xtalate.schema.cell import lattice_from_parameters
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


def test_a_leading_header_block_is_skipped_for_the_one_carrying_atoms() -> None:
    # `data_global` headers carrying only bibliography are standard in CCDC/CSD depositions, and
    # taking blocks[0] refused the whole file with CIF_MISSING_CELL — an error naming a cause the
    # file does not have, on a file that is complete and readable. Which block is *the structure*
    # is a different question from n.4's principle that blocks are not frames, and n.4 is
    # unchanged: one block is read, the rest are named.
    data = b"data_global\n_journal_name_full 'J. Test'\n\n" + CUBIC
    result = _parse(data)
    assert result.canonical.frames[0].atoms.symbols == ["Na", "Cl"]
    warnings = [i for i in result.issues if i.code == "CIF_ADDITIONAL_BLOCKS_NOT_READ"]
    assert len(warnings) == 1
    assert "global" in warnings[0].message


def test_a_file_with_no_atom_site_block_still_reports_its_own_defect() -> None:
    # The fallback matters as much as the selection: with no atom-bearing block anywhere, the
    # parser must fail on what is actually wrong with the structure block rather than on the
    # block choice, or the error message misdirects exactly as CIF_MISSING_CELL used to.
    with pytest.raises(ParseError) as exc:
        _parse(b"data_global\n_journal_name_full 'J. Test'\n")
    assert exc.value.issues[0].code == "CIF_MISSING_CELL"


# --- unquoted symmetry operations ------------------------------------------------------------


def _with_symops(ops: bytes) -> bytes:
    """A one-site cell carrying ``ops``. The site is a **general** position (0.1, 0.2, 0.3): on a
    special position every image coincides with the source and merges, so the atom count would be
    1 however many operations were read — and the test could not tell expansion from failure."""
    return (
        b"data_sym\n_cell_length_a 4.0\n_cell_length_b 4.0\n_cell_length_c 4.0\n"
        b"_cell_angle_alpha 90.0\n_cell_angle_beta 90.0\n_cell_angle_gamma 90.0\n"
        b"loop_\n_symmetry_equiv_pos_as_xyz\n" + ops + b"\n"
        b"loop_\n_atom_site_label\n_atom_site_type_symbol\n"
        b"_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
        b"Na1 Na 0.1 0.2 0.3\n"
    )


def test_unquoted_operations_containing_spaces_are_read() -> None:
    # `x, y, z` unquoted is three whitespace-separated tokens, so a one-column loop silently
    # became three one-fragment rows — and the row-count check cannot catch it, because
    # len(values) % 1 is zero for any number of values. It surfaced two stages later as
    # "'x,' has 2 components", naming a defect the file does not have. gemmi, ASE and PyCIFRW all
    # read this, and D65's stage-1/2 seam exists so this reader can be swapped for gemmi.
    result = _parse(_with_symops(b"x, y, z\n-x, -y, -z"))
    assert len(result.canonical.frames[0].atoms.symbols) == 2  # 1 general site x 2 operations
    assert result.canonical.simulation is not None


def test_quoted_operations_are_unaffected_by_the_repair() -> None:
    result = _parse(_with_symops(b"'x, y, z'\n'-x, -y, -z'"))
    assert len(result.canonical.frames[0].atoms.symbols) == 2


def test_a_genuinely_malformed_operation_still_reports_its_own_error() -> None:
    # The repair joins fragments only where every value becomes a complete triplet. A real defect
    # must not be mangled into its neighbour and reported as something else — which is the failure
    # mode being fixed, and it would be perverse to reintroduce it from the other direction.
    with pytest.raises(ParseError) as exc:
        _parse(_with_symops(b"'x, y'\n'-x, -y, -z'"))
    assert exc.value.issues[0].code == "CIF_MALFORMED_SYMOP"


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
    assert list(per_atom["cif:occupancy"]) == pytest.approx([1.0, 0.5, 0.5])
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


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Ow1", "O"),  # water oxygen — ubiquitous in hydrate CIFs
        ("Hw1", "H"),  # its hydrogens
        ("Co1", "Co"),  # the two-letter symbol still wins: cobalt, never carbon
        ("O1", "O"),
    ],
)
def test_a_decorated_site_label_falls_back_to_its_one_letter_element(
    label: str, expected: str
) -> None:
    # `_LABEL` is greedy over [A-Za-z]{1,2} and a regex alternation does not backtrack once a
    # branch matches, so `Ow1` matched `Ow`, failed the element table, and raised
    # CIF_INVALID_SYMBOL on a file whose element is unambiguous. The retry is ordered longest
    # first, which is what keeps `Co1` cobalt.
    data = CUBIC.replace(b"Na1 Na ", label.encode() + b" ? ")
    assert _parse(data).canonical.frames[0].atoms.symbols[0] == expected


def test_the_one_letter_fallback_never_manufactures_the_unknown_marker() -> None:
    # `X` is a valid symbol, so without an explicit bar every unrecognizable two-letter label
    # beginning with x would shorten to `X` and become an atom of unknown species — turning the
    # error `element_of` promises into the placeholder it promises never to invent. This is the
    # case that caught it.
    with pytest.raises(ParseError) as exc:
        _parse(CUBIC.replace(b"Na1 Na ", b"Xx1 Qq "))
    assert exc.value.issues[0].code == "CIF_INVALID_SYMBOL"


def test_a_site_stating_unknown_species_parses_but_says_so() -> None:
    # `elements.py` states that a parser emitting the reserved `X` must accompany it with a
    # warning, and that "that policy lives in the parsers" — where no parser implemented it. Real
    # CIFs use X labels for unassigned electron density, so this stays a valid parse: the file
    # really does say a scatterer sits there. It just stops being silent.
    result = _parse(CUBIC.replace(b"Na1 Na ", b"X1 X "))
    assert result.canonical.frames[0].atoms.symbols[0] == "X"
    warnings = [i for i in result.issues if i.code == "CIF_UNKNOWN_SPECIES"]
    assert len(warnings) == 1
    assert "unidentified species" in warnings[0].message


def test_element_case_is_normalized_through_the_shared_helper() -> None:
    # `FE` and `Fe` are the same element; which one a file writes is typography, not information.
    # The normalizer now lives beside `is_valid_symbol` in schema.elements rather than only in
    # this parser — see its docstring for why the other parsers deliberately still reject `FE`.
    assert (
        _parse(CUBIC.replace(b"Na1 Na ", b"Na1 FE ")).canonical.frames[0].atoms.symbols[0] == "Fe"
    )


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
    np.testing.assert_allclose(np.asarray(carried["cif:occupancy"]), [1.0, 1.0])
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
        # float() accepts "nan" and "inf", and NaN then defeats every ordinary range guard
        # downstream (`value <= 0.0` is False for NaN), so these used to escape the ParseError
        # contract entirely and surface as a pydantic ValidationError traceback out of the CLI.
        (lambda d: d.replace(b"_cell_length_a 4.0", b"_cell_length_a nan"), "CIF_MALFORMED_NUMBER"),
        (lambda d: d.replace(b"_cell_length_a 4.0", b"_cell_length_a inf"), "CIF_MALFORMED_NUMBER"),
        (lambda d: d.replace(b"0.5 0.5 0.5", b"0.5 0.5 nan"), "CIF_MALFORMED_NUMBER"),
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


def test_a_non_finite_value_never_escapes_the_parse_error_contract() -> None:
    # The contract, not just the code: whatever this parser rejects, it rejects *as* a ParseError.
    # A NaN cell length used to reach AtomsBlock construction and raise pydantic's ValidationError,
    # which is not a ParseError — so the CLI printed a stack trace and exited 1 where a structured
    # parse error exits 4. Asserting the type is what pins that; asserting the code is not enough.
    for value in (b"nan", b"inf", b"-inf", b"NaN", b"Infinity"):
        with pytest.raises(ParseError):
            _parse(CUBIC.replace(b"_cell_length_a 4.0", b"_cell_length_a " + value))


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


# --- occupancy: the flagged schema gap (M19, Part 3 §3 n.11) --------------------------------


def _with_occupancy(*values: str) -> bytes:
    rows = b"".join(
        f"{label} {sym} {x} 0.0 0.0 {occ}\n".encode()
        for label, sym, x, occ in (("Na1", "Na", "0.0", values[0]), ("Cl1", "Cl", "0.5", values[1]))
    )
    return CUBIC.replace(
        b"_atom_site_fract_z\nNa1 Na 0.0 0.0 0.0\nCl1 Cl 0.5 0.5 0.5\n",
        b"_atom_site_fract_z\n_atom_site_occupancy\n" + rows,
    )


def test_occupancy_lands_under_the_spec_named_key_not_the_tag_spelling() -> None:
    """The one _atom_site column whose custom key is not its tag: occupancy is a *named*
    limitation with a documented promotion path (Part 2 §6 rule 4), so the key it will be
    promoted from is pinned rather than left to the generic carry-through."""
    per_atom = _parse(_with_occupancy("1.0", "0.5")).canonical.user_metadata.custom_per_atom
    assert list(per_atom["cif:occupancy"]) == pytest.approx([1.0, 0.5])
    # And it arrives under exactly one name, never two.
    assert "cif:atom_site_occupancy" not in per_atom


def test_occupancy_warns_that_it_is_carried_rather_than_modelled() -> None:
    result = _parse(_with_occupancy("1.0", "0.5"))
    issue = next(i for i in result.issues if i.code == "CIF_OCCUPANCY_NOT_MODELLED")
    assert issue.severity == "warning"
    assert "cif:occupancy" in issue.message
    # The same statement survives into the object itself, so a consumer reading only the
    # Canonical Object — not the ParseResult — still learns the field is unmodelled.
    assert any(
        "occupancy carried as a custom" in n for n in result.canonical.provenance.parse_notes
    )


def test_full_occupancy_still_warns() -> None:
    """The warning is about the *model*, not about the values: a file stating occupancy 1.0
    everywhere has still had a column carried rather than modelled, and a reader who is told
    nothing cannot tell that from a file that stated no occupancy at all."""
    assert any(
        i.code == "CIF_OCCUPANCY_NOT_MODELLED" for i in _parse(_with_occupancy("1.0", "1.0")).issues
    )


def test_a_file_without_occupancy_does_not_warn_about_it() -> None:
    assert not any(i.code == "CIF_OCCUPANCY_NOT_MODELLED" for i in _parse(CUBIC).issues)


def test_unknown_occupancy_is_carried_as_absence_not_as_one() -> None:
    """'?' is absence (P3). CIF's *default* occupancy is 1.0, but a default is a convention the
    file did not state, and filling it here would put an invented number in a preserved column."""
    per_atom = _parse(_with_occupancy("1.0", "?")).canonical.user_metadata.custom_per_atom
    # A column that is not wholly numeric cannot be a float array, so the schema's custom_per_atom
    # union keeps it as the source spelled it — the absent row stays absent rather than becoming
    # a number, which is the property under test.
    assert list(per_atom["cif:occupancy"]) == ["1.0", None]


# --- formal charges (M19 deliverable 2) ----------------------------------------------------


def _with_oxidation(*rows: str, types: tuple[str, str] = ("Na1+", "Cl1-")) -> bytes:
    loop = "loop_\n_atom_type_symbol\n_atom_type_oxidation_number\n" + "".join(
        f"{r}\n" for r in rows
    )
    return CUBIC.replace(
        b"loop_\n_atom_site_label", loop.encode() + b"loop_\n_atom_site_label"
    ).replace(
        b"Na1 Na 0.0 0.0 0.0\nCl1 Cl 0.5 0.5 0.5\n",
        f"Na1 {types[0]} 0.0 0.0 0.0\nCl1 {types[1]} 0.5 0.5 0.5\n".encode(),
    )


def test_declared_oxidation_numbers_populate_charges_with_a_scheme_label() -> None:
    result = _parse(_with_oxidation("Na1+ 1", "Cl1- -1"))
    frame = result.canonical.frames[0]
    assert frame.electronic.charges is not None
    np.testing.assert_allclose(frame.electronic.charges, [1.0, -1.0])
    assert result.canonical.simulation is not None
    # A formal oxidation state is integer bookkeeping, not a population analysis; without the
    # label a consumer could read an idealized +1 as a computed Mulliken charge.
    assert result.canonical.simulation.extra["cif:charge_scheme"] == "formal_oxidation_state"


def test_charges_are_replicated_onto_symmetry_generated_atoms() -> None:
    """A charge belongs to the site, so every atom the site generates carries it."""
    # Cl sits off the inversion centre, so it genuinely doubles; Na at the origin does not.
    data = (
        _with_oxidation("Na1+ 1", "Cl1- -1")
        .replace(b"Cl1 Cl1- 0.5 0.5 0.5\n", b"Cl1 Cl1- 0.25 0.25 0.25\n")
        .replace(
            b"loop_\n_atom_site_label",
            b"loop_\n_space_group_symop_operation_xyz\n'x, y, z'\n'-x, -y, -z'\n"
            b"loop_\n_atom_site_label",
        )
    )
    charges = _parse(data).canonical.frames[0].electronic.charges
    assert charges is not None
    np.testing.assert_allclose(charges, [1.0, -1.0, -1.0])  # Na on a special position, Cl doubled


def test_a_partial_oxidation_declaration_leaves_charges_unset() -> None:
    """charges is all-or-nothing per atom; filling the undeclared atoms with 0.0 would assert a
    neutrality the file never stated (P4)."""
    result = _parse(_with_oxidation("Na1+ 1"))
    assert result.canonical.frames[0].electronic.charges is None
    issue = next(i for i in result.issues if i.code == "CIF_PARTIAL_OXIDATION_NUMBERS")
    assert "Cl1-" in issue.message


def test_type_symbol_suffix_alone_does_not_populate_charges() -> None:
    """'Fe3+' is an identifier that conventionally encodes a charge, not a statement of one.
    Promoting a spelling to a physical quantity is interpretation, so only the tag CIF defines
    for the purpose populates the field — the suffix stays preserved verbatim."""
    result = _parse(CUBIC.replace(b"Na1 Na ", b"Na1 Na1+ "))
    assert result.canonical.frames[0].electronic.charges is None
    assert result.canonical.user_metadata.custom_per_atom["cif:type_symbol"] == ["Na1+", "Cl"]


def test_a_symbol_disagreeing_with_its_declared_number_is_reported() -> None:
    result = _parse(_with_oxidation("Na1+ 2", "Cl1- -1"))
    issue = next(i for i in result.issues if i.code == "CIF_OXIDATION_NUMBER_DISAGREES_WITH_SYMBOL")
    assert "+1" in issue.message and "+2" in issue.message
    charges = result.canonical.frames[0].electronic.charges
    assert charges is not None
    np.testing.assert_allclose(charges, [2.0, -1.0])  # the declared number wins


def test_an_oxidation_loop_with_no_symbol_column_is_refused() -> None:
    """Two independent tables joined by row order would assign charges the file never paired."""
    data = CUBIC.replace(
        b"loop_\n_atom_site_label",
        b"loop_\n_atom_type_oxidation_number\n1\n-1\nloop_\n_atom_site_label",
    )
    with pytest.raises(ParseError) as exc:
        _parse(data)
    assert exc.value.issues[0].code == "CIF_UNJOINABLE_OXIDATION_NUMBERS"


def test_conflicting_oxidation_numbers_for_one_type_are_refused() -> None:
    with pytest.raises(ParseError) as exc:
        _parse(_with_oxidation("Na1+ 1", "Na1+ 3", "Cl1- -1"))
    assert exc.value.issues[0].code == "CIF_CONFLICTING_OXIDATION_NUMBERS"


def test_a_file_without_oxidation_numbers_leaves_charges_absent() -> None:
    """Absence of a declaration is not a declaration of zero (P3)."""
    result = _parse(CUBIC)
    assert result.canonical.frames[0].electronic.charges is None
    assert (
        result.canonical.simulation is None
        or "cif:charge_scheme" not in result.canonical.simulation.extra
    )


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("Fe", None), ("Fe3+", 3.0), ("O2-", -2.0), ("Ca+", 1.0), ("Cl-", -1.0), ("Na+1", 1.0)],
)
def test_charge_spelled_by_a_type_symbol(symbol: str, expected: float | None) -> None:
    assert charge_of_type_symbol(symbol) == expected
