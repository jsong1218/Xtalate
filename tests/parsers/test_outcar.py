"""OUTCAR parser unit tests (v1.2 M43-S1).

The error contract (Part 3 §5; the base ``OUTCAR_*`` code set of D164), the streaming/materialized
identity (D56), the unmapped-line carries (P1), the parser-only capability seam (D159), and the
shared-core mapping choices (D160/D161) — pinned here with inline synthetic files, on top of the
governed goldens in ``tests/golden/``.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from xtalate import __version__ as xtalate_version
from xtalate.capabilities import Registry
from xtalate.cli.main import main
from xtalate.conversion import ConversionEngine
from xtalate.parsers import builtin_parsers
from xtalate.parsers.outcar import FORMAT_ID, make_outcar_parser
from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel, ParseError, ParseResult
from xtalate.sdk.streaming import materialize

_GOLDEN = Path(__file__).parent.parent / "golden" / "outcar" / "relax-h2o" / "OUTCAR"

PARSER = make_outcar_parser()

_K_BAR = 1602.1766208  # the exact kBar per eV/Å³ factor, shared with the core

_HEAD = """ vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex

  POTCAR:    PAW_PBE H 15Jun2001
    VRHFIN =H: 1s1
  POTCAR:    PAW_PBE O 15Jun2001
    VRHFIN =O: 2s2p4

  ions per type =               2   1

  NIONS =       3

  direct lattice vectors                 reciprocal lattice vectors
     10.000000000  0.000000000  0.000000000     0.100000000  0.000000000  0.000000000
      0.000000000 10.000000000  0.000000000     0.000000000  0.100000000  0.000000000
      0.000000000  0.000000000 10.000000000     0.000000000  0.000000000  0.100000000

"""

_DEFAULT_POSITIONS = [(5.0, 7.5, 5.0), (7.5, 5.0, 5.0), (5.0, 5.0, 5.0)]
_DEFAULT_FORCES = [(0.2, -0.1, 0.0), (-0.1, 0.05, 0.0), (-0.1, 0.0, 0.05)]


def _step(
    *,
    energy: float = -76.4,
    stress: list[float] | None = None,
    positions: list[tuple[float, float, float]] | None = None,
    forces: list[tuple[float, float, float]] | None = None,
    lattice: list[tuple[float, float, float]] | None = None,
) -> str:
    pos = positions if positions is not None else _DEFAULT_POSITIONS
    frc = forces if forces is not None else _DEFAULT_FORCES
    lines: list[str] = []
    lines.append("  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)")
    lines.append(
        f"    energy  without entropy=       {energy:.8f}  energy(sigma->0) =       {energy:.8f}"
    )
    lines.append("")
    if stress is not None:
        lines.append("  FORCE on cell =-STRESS in cart. coord.  units (eV):")
        lines.append("    in kB         " + " ".join(f"{v:.10f}" for v in stress))
        lines.append("")
    if lattice is not None:
        lines.append("  direct lattice vectors                 reciprocal lattice vectors")
        for i, row in enumerate(lattice):
            lines.append(
                f"     {row[0]:.10f}  {row[1]:.10f}  {row[2]:.10f}     "
                f"{1.0 / row[i]:.10f}  {0.0:.10f}  {0.0:.10f}"
            )
        lines.append("")
    lines.append("  -----------------------------------------------------------------------------")
    lines.append("    POSITION                                       TOTAL-FORCE (eV/Angst)")
    lines.append("  -----------------------------------------------------------------------------")
    for (x, y, z), (fx, fy, fz) in zip(pos, frc, strict=True):
        lines.append(f"      {x:.8f}   {y:.8f}   {z:.8f}   {fx:.8f}  {fy:.8f}  {fz:.8f}")
    lines.append("  -----------------------------------------------------------------------------")
    lines.append(
        "     total drift:                                0.00000000   0.00000000   0.00000000"
    )
    lines.append("")
    return "\n".join(lines)


def _file(*steps: str, head: str = _HEAD) -> bytes:
    return (head + "".join(steps)).encode()


def _parse(data: bytes) -> ParseResult:
    return PARSER.parse(io.BytesIO(data), filename="OUTCAR")


# --- sniffing ---------------------------------------------------------------------


def test_sniff_by_conventional_name() -> None:
    assert PARSER.sniff(b"", "OUTCAR") == 1.0
    assert PARSER.sniff(b"", "OUTCAR.relax") == 0.9  # OUTCAR-prefixed name is lenient-but-strong
    assert PARSER.sniff(b"", "outcar") == 0.0  # case-sensitive, as VASP writes it


def test_sniff_by_content_anchors() -> None:
    assert PARSER.sniff(_HEAD.encode(), None) == 0.9  # the vasp.<major>.<minor> banner
    body = b"direct lattice vectors\n1 0 0\n0 1 0\n0 0 1\nTOTAL-FORCE\n"
    assert PARSER.sniff(body, None) == 0.8
    assert PARSER.sniff(b"not a vasp file at all", None) == 0.0


# --- mapping choices (shared core, D160/D161) -------------------------------------


def test_total_energy_is_energy_sigma0() -> None:
    obj = _parse(_file(_step(energy=-12.5))).canonical
    assert obj.frames[0].electronic.total_energy == -12.5


def test_positions_read_cartesian_as_is_not_fractional_times_lattice() -> None:
    # OUTCAR positions are Cartesian; the lattice must NOT multiply them (the M43 positions-mode
    # trap). A parser that re-ran the fractional->Cartesian multiply would read (50, 75, 50).
    obj = _parse(_file(_step())).canonical
    assert obj.frames[0].atoms.positions.tolist() == [
        [5.0, 7.5, 5.0],
        [7.5, 5.0, 5.0],
        [5.0, 5.0, 5.0],
    ]


def test_symbols_derive_from_vrhfin_and_counts() -> None:
    obj = _parse(_file(_step())).canonical
    assert obj.frames[0].atoms.symbols == ["H", "H", "O"]


def test_source_code_carries_the_version_banner_verbatim() -> None:
    obj = _parse(_file(_step())).canonical
    assert obj.simulation is not None
    assert obj.simulation.source_code == "vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex"


def test_parser_version_follows_the_package_version() -> None:
    obj = _parse(_file(_step())).canonical
    recorded = obj.provenance.history[0].parser_version
    assert recorded is not None
    assert recorded.startswith(f"{FORMAT_ID}-parser {xtalate_version}")


def test_energy_without_entropy_carries_verbatim_with_a_warning() -> None:
    result = _parse(_file(_step(energy=-12.5)))
    obj = result.canonical
    assert obj.user_metadata.custom_per_frame["outcar:energy_without_entropy"] == [-12.5]
    assert "OUTCAR_UNMAPPED_LINE_CARRIED" in {i.code for i in result.issues}


# --- the VASP stress mapping (D161) -------------------------------------------------


def test_stress_maps_kbar_compression_positive_to_tension_positive_ev_a3() -> None:
    obj = _parse(_file(_step(stress=[_K_BAR, _K_BAR, _K_BAR, 0.0, 0.0, 0.0]))).canonical
    stress = obj.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]


def test_stress_off_diagonals_use_vasp_voigt_ordering() -> None:
    # in kB = K_BAR × [XX, YY, ZZ, XY, YZ, ZX]: XY at [0][1], YZ at [1][2], ZX at [0][2].
    obj = _parse(
        _file(_step(stress=[_K_BAR, 2 * _K_BAR, _K_BAR / 2, _K_BAR / 4, _K_BAR / 8, _K_BAR / 16]))
    ).canonical
    stress = obj.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == [
        [-1.0, -0.25, -0.0625],
        [-0.25, -2.0, -0.125],
        [-0.0625, -0.125, -0.5],
    ]


def test_stressless_step_reads_none_not_zero() -> None:
    obj = _parse(_file(_step())).canonical
    assert obj.frames[0].electronic.stress is None


def test_stress_is_per_step_and_maps_only_where_present() -> None:
    data = _file(_step(stress=[_K_BAR] * 6), _step(energy=-13.0))
    obj = _parse(data).canonical
    assert obj.frames[0].electronic.stress is not None
    assert obj.frames[1].electronic.stress is None


def test_stress_mapping_is_recorded_in_parse_notes_and_source_units() -> None:
    obj = _parse(_file(_step(stress=[_K_BAR] * 6))).canonical
    notes = obj.provenance.parse_notes
    assert any("'in kB'" in n and "tension-positive" in n for n in notes)
    assert obj.provenance.source_units.get("stress") == "kbar"


# --- per-step cells (NpT) ----------------------------------------------------------


def test_per_step_lattice_overrides_the_running_cell() -> None:
    data = _file(
        _step(),
        _step(energy=-13.0, lattice=[(10.1, 0, 0), (0, 10.1, 0), (0, 0, 10.1)]),
    )
    obj = _parse(data).canonical
    assert obj.frames[0].cell is not None
    assert obj.frames[1].cell is not None
    assert obj.frames[0].cell.lattice_vectors[0][0] == 10.0
    assert obj.frames[1].cell.lattice_vectors[0][0] == 10.1


# --- streaming identity (D56) -------------------------------------------------------


def test_streamed_and_materialized_readings_are_identical() -> None:
    data = _file(_step(energy=-12.5), _step(energy=-13.0))
    whole = _parse(data).canonical
    stream = PARSER.parse_stream(io.BytesIO(data), filename="OUTCAR")
    streamed, _ = materialize(stream)
    assert streamed.model_dump(mode="json") == whole.model_dump(mode="json")


def test_frame_stream_is_single_pass() -> None:
    data = _file(_step())
    stream = PARSER.parse_stream(io.BytesIO(data), filename="OUTCAR")
    list(stream.frames())
    with pytest.raises(RuntimeError, match="single-pass"):
        list(stream.frames())


# --- the parser-only seam (D159) ----------------------------------------------------


def test_outcar_registers_parser_only() -> None:
    reg = default_registry()
    assert "outcar" in {p.format_id for p in reg.parsers()}
    assert "outcar" not in {e.format_id for e in reg.exporters()}


def test_capabilities_matrix_is_read_only() -> None:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    matrix = reg.capability_matrix()
    assert matrix.get("outcar", "read").format_id == "outcar"
    with pytest.raises(KeyError, match="no 'write' capabilities registered"):
        matrix.get("outcar", "write")


def test_cli_refuses_outcar_as_a_conversion_target() -> None:
    # Done-means #2: OUTCAR is refused as a `--to` target with the established
    # unknown/unavailable-target error (D159 — no special-casing).
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        main(["convert", str(_GOLDEN), "--to", "outcar"])


def test_stress_row_is_first_class() -> None:
    caps = PARSER.capabilities()
    assert caps.fields["electronic.stress"].level is CapabilityLevel.FULL
    matrix = default_registry().capability_matrix()
    assert matrix.field_capability("outcar", "read", "electronic.stress").level is (
        CapabilityLevel.FULL
    )


def test_ambiguous_stress_convention_does_not_fire_for_vasp() -> None:
    # VASP declares its convention, so the conversion completes with no unresolved scenario — the
    # convention is mapped at the parser boundary, never asked (the extXYZ contrast, D151).
    obj = _parse(_file(_step(stress=[_K_BAR] * 6))).canonical
    res = ConversionEngine(default_registry()).convert(
        obj, source_format_id="outcar", target_format_id="extxyz"
    )
    assert res.report.status == "completed"
    assert res.report.refusal is None


# --- the OUTCAR_* error contract (D164) --------------------------------------------


def test_empty_file_is_outcar_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(b"")
    assert excinfo.value.issues[0].code == "OUTCAR_EMPTY"


def test_whitespace_only_file_is_outcar_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(b"   \n  \n")
    assert excinfo.value.issues[0].code == "OUTCAR_EMPTY"


def test_no_step_table_is_outcar_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(_HEAD.encode())
    assert excinfo.value.issues[0].code == "OUTCAR_EMPTY"


def test_vasp5_banner_reads_as_a_recognized_layout() -> None:
    # The 5.x banner is a recognized major layout (S2): it parses, and the declared program is
    # carried verbatim — the version-drift discipline recognizes both majors, never re-derives.
    head = _HEAD.replace(
        "vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex",
        "vasp.5.4.4 18May18 (build May 18 2018 12:00:00) complex",
    )
    obj = _parse(_file(_step(), head=head)).canonical
    assert obj.simulation is not None
    assert obj.simulation.source_code == "vasp.5.4.4 18May18 (build May 18 2018 12:00:00) complex"
    assert obj.frames[0].atoms.symbols == ["H", "H", "O"]


def test_missing_version_banner_is_an_unrecognized_layout() -> None:
    # A header with no parseable vasp.<major>.<minor> banner is refused as an unrecognized layout
    # (S2, D165) — never a best-effort partial parse (P1). This refines S1's assignment, where a
    # mangled banner was OUTCAR_MISSING_BLOCK.
    head = _HEAD.replace(
        "vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex", "some other program"
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    issue = excinfo.value.issues[0]
    assert issue.code == "OUTCAR_UNRECOGNIZED_LAYOUT"
    assert "version banner" in issue.message


def test_foreign_file_is_unrecognized_layout_not_empty() -> None:
    # A non-OUTCAR file with content is not 'empty' — it is a layout the reader does not
    # recognize, refused rather than misread.
    with pytest.raises(ParseError) as excinfo:
        _parse(b"this is not an OUTCAR log at all\n")
    assert excinfo.value.issues[0].code == "OUTCAR_UNRECOGNIZED_LAYOUT"


def test_unrecognized_major_version_is_refused_not_misread() -> None:
    # VASP-version breadth beyond 5.x/6.x refuses with a contribution call (S2 cut line) — never
    # read as if it were a known layout.
    head = _HEAD.replace("vasp.6.3.2", "vasp.7.0.0")
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    issue = excinfo.value.issues[0]
    assert issue.code == "OUTCAR_UNRECOGNIZED_LAYOUT"
    assert "7.x" in issue.message


def test_step_with_more_atoms_than_declared_is_inconsistent_step() -> None:
    # NIONS = 3, but one step's POSITION/TOTAL-FORCE table carries a 4th data row — the table
    # disagrees with the header, a structural inconsistency refused, never silently truncated (P3).
    extra_row = "      5.00000000   7.30000000   5.00000000   0.10000000  -0.05000000  0.00000000\n"
    step = _step().replace(
        "  -----------------------------------------------------------------------------\n"
        "     total drift:",
        extra_row
        + "  -----------------------------------------------------------------------------\n"
        "     total drift:",
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(step))
    issue = excinfo.value.issues[0]
    assert issue.code == "OUTCAR_INCONSISTENT_STEP"
    assert "more than the declared 3 atoms" in issue.message


def test_missing_species_is_a_parse_error() -> None:
    head = _HEAD.replace("    VRHFIN =H: 1s1\n", "").replace("    VRHFIN =O: 2s2p4\n", "")
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    assert excinfo.value.issues[0].code == "OUTCAR_MISSING_BLOCK"


def test_missing_lattice_is_a_parse_error() -> None:
    head = _HEAD.split("  direct lattice vectors")[0]
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    assert excinfo.value.issues[0].code == "OUTCAR_MISSING_BLOCK"


def test_missing_energy_line_is_a_parse_error_not_a_defaulted_energy() -> None:
    # A recognized step (a POSITION/TOTAL-FORCE table) with no energy(sigma->0) line before it.
    step = _step().replace(
        "    energy  without entropy=       -76.40000000  energy(sigma->0) =       -76.40000000\n",
        "",
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(step))
    issue = excinfo.value.issues[0]
    assert issue.code == "OUTCAR_MISSING_BLOCK"
    assert "energy(sigma->0)" in issue.message


def test_missing_force_table_is_a_parse_error_not_a_partial_frame() -> None:
    # An energy line with no following POSITION/TOTAL-FORCE table: a torn step, never a partial
    # frame.
    torn = (
        _HEAD
        + "    energy  without entropy=       -76.40000000  energy(sigma->0) =       -76.40000000\n"
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(torn.encode())
    assert excinfo.value.issues[0].code == "OUTCAR_MISSING_BLOCK"


def test_nions_mismatch_is_a_parse_error() -> None:
    head = _HEAD.replace("  NIONS =       3", "  NIONS =       4")
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    assert excinfo.value.issues[0].code == "OUTCAR_MISSING_BLOCK"


def test_unknown_species_symbol_is_a_parse_error() -> None:
    head = _HEAD.replace("VRHFIN =H: 1s1", "VRHFIN =Xx: 1s1")
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_step(), head=head))
    assert excinfo.value.issues[0].code == "OUTCAR_MISSING_BLOCK"
