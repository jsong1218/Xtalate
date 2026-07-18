"""XDATCAR parser tests (M13): the fixed-cell and NpT per-frame-cell forms, the
Direct→Cartesian boundary conversion, ``timestep = None`` honesty, the streaming path's
agreement with the whole-file one, the error contract, and sniffing (Part 3 §3, §5, §6.1)."""

from __future__ import annotations

import io

import numpy as np
import pytest

from tests._format_helpers import assert_scientifically_equal, parse_bytes
from xtalate.parsers.xdatcar import make_xdatcar_parser
from xtalate.sdk import ParseError, ParseResult
from xtalate.sdk.streaming import materialize

FIXED_CELL = b"""NaCl MD run
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     2
  0.1 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     3
  0.2 0.0 0.0
  0.5 0.5 0.5
"""

# The NpT form: VASP restates the whole 7-line header before each configuration, so the cell
# varies frame to frame — the format's distinctive canonical feature (M13 deliverable 1).
NPT = b"""NaCl NpT run
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
NaCl NpT run
   1.0
     5.8 0.0 0.0
     0.0 5.8 0.0
     0.0 0.0 5.8
   Na Cl
   1 1
Direct configuration=     2
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

SINGLE_FRAME = b"""one configuration
   1.0
     4.0 0.0 0.0
     0.0 4.0 0.0
     0.0 0.0 4.0
   Si
   2
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

CARTESIAN = b"""cartesian configurations
   1.0
     4.0 0.0 0.0
     0.0 4.0 0.0
     0.0 0.0 4.0
   Si
   2
Cartesian configuration=     1
  0.0 0.0 0.0
  2.0 2.0 2.0
"""

CARTESIAN_SCALED = b"""cartesian with a scaling factor
   2.0
     4.0 0.0 0.0
     0.0 4.0 0.0
     0.0 0.0 4.0
   Si
   2
Cartesian configuration=     1
  0.0 0.0 0.0
  2.0 2.0 2.0
"""

CARTESIAN_NEGATIVE_SCALE = b"""cartesian under a target volume
-8.0
  1.0 0.0 0.0
  0.0 1.0 0.0
  0.0 0.0 1.0
Si
1
Cartesian configuration=     1
  1.0 1.0 1.0
"""

TRUNCATED = b"""killed mid-write
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     2
  0.1 0.0 0.0
"""

COUNT_MISMATCH = b"""counts do not match species
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

BAD_SYMBOL = b"""unknown element
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Xx
   1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

NEGATIVE_SCALE = b"""negative scale is a target volume
-8.0
  1.0 0.0 0.0
  0.0 1.0 0.0
  0.0 0.0 1.0
Si
1
Direct configuration=     1
  0.0 0.0 0.0
"""


def parse(data: bytes) -> ParseResult:
    return parse_bytes(make_xdatcar_parser(), data, filename="XDATCAR")


# --- the fixed-cell form ------------------------------------------------------------------


def test_fixed_cell_reads_every_configuration_under_the_header_lattice() -> None:
    obj = parse(FIXED_CELL).canonical
    assert len(obj.frames) == 3
    assert [f.index for f in obj.frames] == [0, 1, 2]  # source ordering preserved
    for frame in obj.frames:
        assert frame.cell is not None
        np.testing.assert_allclose(frame.cell.lattice_vectors, np.eye(3) * 5.6)


def test_direct_coordinates_are_converted_to_cartesian_at_the_boundary() -> None:
    obj = parse(FIXED_CELL).canonical
    # 0.5 fractional along each axis of a 5.6 Å cubic cell -> 2.8 Å Cartesian (§4).
    np.testing.assert_allclose(obj.frames[0].atoms.positions[1], [2.8, 2.8, 2.8])
    np.testing.assert_allclose(obj.frames[1].atoms.positions[0], [0.56, 0.0, 0.0])
    assert obj.provenance.original_coordinate_system == "fractional"
    assert obj.provenance.source_units["positions"] == "fractional"


def test_symbols_are_expanded_from_the_header_species_and_counts() -> None:
    obj = parse(FIXED_CELL).canonical
    assert obj.frames[0].atoms.symbols == ["Na", "Cl"]


def test_timestep_is_absent_not_zero() -> None:
    """XDATCAR numbers configurations but declares no time axis (§3 n.5). Absence is
    information (P3): a fabricated POTIM default would be a silent invention (P1)."""
    obj = parse(FIXED_CELL).canonical
    assert obj.trajectory is not None
    assert obj.trajectory.timestep is None


def test_pbc_is_recorded_as_format_defined_not_guessed() -> None:
    obj = parse(FIXED_CELL).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[0].cell.pbc == (True, True, True)
    assert any("format-defined, not assumed" in n for n in obj.provenance.parse_notes)


def test_title_line_is_carried_into_custom_global() -> None:
    obj = parse(FIXED_CELL).canonical
    assert obj.user_metadata.custom_global["xdatcar:comment"] == "NaCl MD run"


def test_scaling_factor_is_recorded_as_a_provenance_note_not_a_field() -> None:
    """Folded into the lattice (§4), so it is not independent information the target must carry
    — the routing POSCAR settled on in DECISIONS.md D34."""
    obj = parse(FIXED_CELL).canonical
    assert any("scaling factor folded" in n for n in obj.provenance.parse_notes)
    assert obj.simulation is None


def test_negative_scale_is_read_as_a_target_volume() -> None:
    obj = parse(NEGATIVE_SCALE).canonical
    assert obj.frames[0].cell is not None
    volume = abs(float(np.linalg.det(obj.frames[0].cell.lattice_vectors)))
    assert volume == pytest.approx(8.0)


# --- the NpT (per-frame-cell) form --------------------------------------------------------


def test_npt_form_reads_a_distinct_cell_per_frame() -> None:
    obj = parse(NPT).canonical
    assert len(obj.frames) == 2
    assert obj.frames[0].cell is not None
    assert obj.frames[1].cell is not None
    np.testing.assert_allclose(obj.frames[0].cell.lattice_vectors, np.eye(3) * 5.6)
    np.testing.assert_allclose(obj.frames[1].cell.lattice_vectors, np.eye(3) * 5.8)


def test_npt_positions_convert_under_each_frames_own_lattice() -> None:
    """The reason per-frame cells must be parsed, not approximated by the header's: identical
    fractional coordinates mean *different* Cartesian positions under a changed cell."""
    obj = parse(NPT).canonical
    np.testing.assert_allclose(obj.frames[0].atoms.positions[1], [2.8, 2.8, 2.8])
    np.testing.assert_allclose(obj.frames[1].atoms.positions[1], [2.9, 2.9, 2.9])


def test_npt_header_restating_a_different_atom_count_is_refused() -> None:
    bad = NPT.replace(
        b"   1 1\nDirect configuration=     2", b"   1 2\nDirect configuration=     2"
    )
    with pytest.raises(ParseError) as exc:
        parse(bad)
    assert exc.value.issues[0].code == "XDATCAR_VARIABLE_ATOM_COUNT"


# --- degenerate + Cartesian forms ---------------------------------------------------------


def test_single_configuration_is_a_structure_not_a_trajectory() -> None:
    """A lone frame carries no trajectory container (Part 2 §3.2)."""
    obj = parse(SINGLE_FRAME).canonical
    assert len(obj.frames) == 1
    assert obj.trajectory is None


def test_cartesian_configuration_marker_is_not_converted() -> None:
    obj = parse(CARTESIAN).canonical
    np.testing.assert_allclose(obj.frames[0].atoms.positions[1], [2.0, 2.0, 2.0])
    assert obj.provenance.original_coordinate_system == "cartesian"


def test_cartesian_positions_are_scaled_by_the_scaling_factor() -> None:
    """Cartesian rows are in scaled units (§4), exactly as in POSCAR: with scale 2.0 a raw
    (2, 2, 2) row is at 4 Å along each axis. Regression for the v0.3 defect where the
    multiplier was folded into the lattice but never applied to Cartesian rows, so the
    positions came back unscaled while the parse note claimed otherwise (P1)."""
    obj = parse(CARTESIAN_SCALED).canonical
    np.testing.assert_allclose(obj.frames[0].atoms.positions[1], [4.0, 4.0, 4.0])
    assert obj.frames[0].cell is not None
    np.testing.assert_allclose(obj.frames[0].cell.lattice_vectors, np.eye(3) * 8.0)
    # The note must describe what the parser actually did (P1).
    assert any("Cartesian coordinates scaled" in n for n in obj.provenance.parse_notes)


def test_cartesian_positions_are_scaled_under_a_negative_target_volume() -> None:
    """A negative scale sets the cell *volume* (§4); the derived multiplier applies to Cartesian
    rows too. Unit lattice, target volume 8 -> multiplier 2, so raw (1, 1, 1) sits at 2 Å."""
    obj = parse(CARTESIAN_NEGATIVE_SCALE).canonical
    np.testing.assert_allclose(obj.frames[0].atoms.positions[0], [2.0, 2.0, 2.0])
    assert obj.frames[0].cell is not None
    assert abs(float(np.linalg.det(obj.frames[0].cell.lattice_vectors))) == pytest.approx(8.0)


# --- the error contract (Part 3 §5; M13 deliverable 3) ------------------------------------


def test_truncated_configuration_is_a_recoverable_error() -> None:
    """The characteristic XDATCAR corruption — an MD run killed mid-write. Recoverable because
    the frames already read are good science; whether to keep them is the user's explicit
    choice (P4), not the parser's."""
    with pytest.raises(ParseError) as exc:
        parse(TRUNCATED)
    issue = exc.value.issues[0]
    assert issue.code == "XDATCAR_TRUNCATED_CONFIGURATION"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"
    assert issue.location == "frame 1"


def test_count_symbol_mismatch_in_header_is_a_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse(COUNT_MISMATCH)
    assert exc.value.issues[0].code == "XDATCAR_MALFORMED"
    assert exc.value.issues[0].recovery_hint is None


def test_unknown_element_symbol_is_refused() -> None:
    with pytest.raises(ParseError) as exc:
        parse(BAD_SYMBOL)
    assert exc.value.issues[0].code == "XDATCAR_INVALID_SYMBOL"


def test_vasp4_shaped_header_is_refused_rather_than_filled() -> None:
    """XDATCAR states its species in the header (§3 n.1). A file without them is malformed for
    *this* format; placeholder elements are never invented (P4)."""
    vasp4 = FIXED_CELL.replace(b"   Na Cl\n", b"")
    with pytest.raises(ParseError) as exc:
        parse(vasp4)
    assert exc.value.issues[0].code == "XDATCAR_MALFORMED"


def test_non_utf8_bytes_raise_the_structured_error_contract() -> None:
    with pytest.raises(ParseError) as exc:
        parse(FIXED_CELL.replace(b"NaCl MD run", b"NaCl \xff MD"))
    assert exc.value.issues[0].code == "XDATCAR_ENCODING_ERROR"


# --- streaming (M12 surface; the reason XDATCAR is streaming-first) ------------------------


def test_parser_declares_streaming_support() -> None:
    assert make_xdatcar_parser().supports_streaming() is True


def test_streamed_and_whole_file_readings_agree() -> None:
    """``parse`` *is* ``materialize(parse_stream(...))``, so this pins the property that makes
    that definition safe: the two readings are one code path and cannot diverge (D56)."""
    parser = make_xdatcar_parser()
    whole = parser.parse(io.BytesIO(NPT), filename="XDATCAR").canonical
    streamed, _ = materialize(parser.parse_stream(io.BytesIO(NPT), filename="XDATCAR"))
    assert_scientifically_equal(whole, streamed)


def test_stream_yields_frames_lazily() -> None:
    """The header is available before any configuration is read — the property that bounds peak
    memory by one frame rather than the trajectory (Part 4 §6)."""
    parser = make_xdatcar_parser()
    stream = parser.parse_stream(io.BytesIO(FIXED_CELL), filename="XDATCAR")
    assert stream.header.trajectory is not None
    assert stream.header.custom_global["xdatcar:comment"] == "NaCl MD run"
    frames = stream.frames()
    assert next(frames).frame.index == 0
    assert next(frames).frame.index == 1


def test_mid_stream_truncation_raises_at_the_offending_frame() -> None:
    """Frames before the corruption are yielded normally; the error arrives at frame k, honoring
    the Part 3 §5 contract mid-stream."""
    parser = make_xdatcar_parser()
    frames = parser.parse_stream(io.BytesIO(TRUNCATED), filename="XDATCAR").frames()
    assert next(frames).frame.index == 0
    with pytest.raises(ParseError) as exc:
        next(frames)
    assert exc.value.issues[0].recovery_hint == "truncate_at_last_valid_frame"


# --- sniffing (Part 3 §6.1) ---------------------------------------------------------------


def test_conventional_filename_is_unambiguous() -> None:
    assert make_xdatcar_parser().sniff(FIXED_CELL, "XDATCAR") == 1.0


def test_configuration_marker_distinguishes_a_nameless_xdatcar_from_a_poscar() -> None:
    parser = make_xdatcar_parser()
    assert parser.sniff(FIXED_CELL, None) > 0.9
    poscar = b"""a poscar
1.0
  4.0 0.0 0.0
  0.0 4.0 0.0
  0.0 0.0 4.0
Si
2
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
"""
    assert parser.sniff(poscar, None) == 0.0


def test_sniff_never_raises_on_garbage() -> None:
    parser = make_xdatcar_parser()
    assert parser.sniff(b"", None) == 0.0
    assert parser.sniff(b"\xff\xfe nonsense", None) == 0.0


# --- block-boundary disambiguation (regression) -------------------------------------------


def test_restated_header_with_a_blank_title_is_read_correctly() -> None:
    """Regression: a blank line at a block boundary is ambiguous — trailing whitespace, a
    separator, or the *empty title* of a restated header. An XDATCAR exported from a source
    that carried no title has exactly that, so skipping blanks here read the scale line as the
    title and the first lattice row as the scale. Found by the M10 hypothesis property test on a
    mixed-cell source, where recovery fabricates a lattice for one frame only and the exporter
    therefore emits the NpT form."""
    blank_title = NPT.replace(b"NaCl NpT run\n   1.0\n     5.8", b"\n   1.0\n     5.8")
    obj = parse(blank_title).canonical
    assert len(obj.frames) == 2
    assert obj.frames[1].cell is not None
    np.testing.assert_allclose(obj.frames[1].cell.lattice_vectors, np.eye(3) * 5.8)


def test_trailing_blank_lines_end_the_file_cleanly() -> None:
    obj = parse(FIXED_CELL + b"\n\n").canonical
    assert len(obj.frames) == 3


def test_blank_separator_before_a_configuration_is_tolerated() -> None:
    """The other reading of a blank line: padding before the next configuration, not a title."""
    padded = FIXED_CELL.replace(b"Direct configuration=     2", b"\nDirect configuration=     2")
    obj = parse(padded).canonical
    assert len(obj.frames) == 3
