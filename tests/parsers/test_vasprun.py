"""vasprun.xml parser unit tests (v1.2 M42-S2).

The error contract (Part 3 §5; the ``VASPRUN_*`` code set of D160), the streaming/materialized
identity (D56), the unmapped-tag carries (P1), the parser-only capability seam (D159), and
the shared-core mapping choices (D160) — pinned here with inline synthetic files, on top of
the governed goldens in ``tests/golden/``.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from xtalate import __version__ as xtalate_version
from xtalate.capabilities import Registry
from xtalate.cli import render
from xtalate.cli.main import main
from xtalate.conversion import ConversionEngine
from xtalate.parsers import builtin_parsers
from xtalate.parsers.vasprun import FORMAT_ID, make_vasprun_parser
from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel, ParseError, ParseResult
from xtalate.sdk.streaming import materialize

_GOLDEN = Path(__file__).parent.parent / "golden" / "vasprun" / "scf-h2o" / "vasprun.xml"

PARSER = make_vasprun_parser()

_HEAD = """<?xml version="1.0" encoding="ISO-8859-1"?>
<vasprun>
<generator>
  <i name="program" type="string" >vasp.5.4.4</i>
</generator>
<incar>
  <i type="string" name="SYSTEM" >test system</i>
</incar>
<atominfo>
  <array name="atomtypes">
    <dimension>2</dimension>
    <field> mass </field>
    <field> Z </field>
    <field> psp </field>
    <v> 1.008 1.0 8 </v>
    <set>
      <rcmax> 3.0 </rcmax>
    </set>
  </array>
  <array name="atoms">
    <dimension>2</dimension>
    <field> vasp_x </field>
    <field> vasp_y </field>
    <field> vasp_z </field>
    <field> atom_type </field>
    <set>
      <rcmax> 3.0 </rcmax>
      <c> 0.0 0.0 0.0 1 </c>
      <c> 0.5 0.5 0.5 1 </c>
    </set>
  </array>
</atominfo>
<structure name="initialpos" >
  <crystal>
    <varray name="basis" >
      <v> 4.0 0.0 0.0 </v>
      <v> 0.0 4.0 0.0 </v>
      <v> 0.0 0.0 4.0 </v>
    </varray>
  </crystal>
  <varray name="positions" >
    <v> 0.0 0.0 0.0 </v>
    <v> 0.5 0.5 0.5 </v>
  </varray>
</structure>
"""

_TAIL = """
</vasprun>
"""


def _calculation(
    *,
    energy: float = -12.5,
    inner_structure: bool = False,
    mode: str | None = None,
    stress: str | None = None,
) -> str:
    struct = ""
    if inner_structure:
        mode_attr = f' mode="{mode}"' if mode else ""
        struct = f"""
  <structure>
    <crystal>
      <varray name="basis" >
        <v> 4.0 0.0 0.0 </v>
        <v> 0.0 4.0 0.0 </v>
        <v> 0.0 0.0 4.0 </v>
      </varray>
    </crystal>
    <varray name="positions"{mode_attr} >
      <v> 0.25 0.25 0.25 </v>
      <v> 0.75 0.75 0.75 </v>
    </varray>
  </structure>"""
    stress_block = (
        f"""
  <varray name="stress" >{stress}
  </varray>"""
        if stress is not None
        else ""
    )
    return f"""
<calculation>
  <energy>
    <i name="e_0_energy" type="float" > {energy} </i>
    <i name="e_fr_energy" type="float" > {energy - 0.001} </i>
    <i name="efermi" type="float" > 5.0 </i>
  </energy>
  <varray name="forces" >
    <v> 0.1 0.0 0.0 </v>
    <v> -0.1 0.0 0.0 </v>
  </varray>{stress_block}{struct}
</calculation>"""


def _file(*calculations: str, head: str = _HEAD, tail: str = _TAIL) -> bytes:
    return (head + "".join(calculations) + tail).encode()


def _parse(data: bytes) -> ParseResult:
    return PARSER.parse(io.BytesIO(data), filename="vasprun.xml")


# --- sniffing ---------------------------------------------------------------------


def test_sniff_by_conventional_name() -> None:
    assert PARSER.sniff(b"", "vasprun.xml") == 1.0
    assert PARSER.sniff(b"", "VASPRUN.XML") == 1.0


def test_sniff_by_root_element() -> None:
    for head in (b"<vasprun>\n", b"<modeling.vasprun>\n", b'<?xml version="1.0"?>\n<vasprun>'):
        assert PARSER.sniff(head, None) == 0.95, head
    # A bare .xml name is too weak; a non-vasprun root is not a match.
    assert PARSER.sniff(b"<html>", "anything.xml") == 0.0
    assert PARSER.sniff(b"not xml at all", None) == 0.0


# --- mapping choices (shared core, D160) ------------------------------------------


def test_total_energy_is_e_0_energy_not_free_energy() -> None:
    obj = _parse(_file(_calculation(energy=-12.5))).canonical
    # e_0_energy = -12.5 is mapped; the free energy (-12.501) is carried, never substituted.
    assert obj.frames[0].electronic.total_energy == -12.5
    assert obj.user_metadata.custom_per_frame["vasprun:e_fr_energy"] == [-12.501]


def test_positions_converted_direct_to_cartesian() -> None:
    obj = _parse(_file(_calculation())).canonical
    # (0.5, 0.5, 0.5) direct × the 4 A cubic lattice = (2, 2, 2).
    assert obj.frames[0].atoms.positions[1].tolist() == [2.0, 2.0, 2.0]
    assert obj.frames[0].atoms.symbols == ["H", "H"]  # Z = 1 from the atomtypes table


def test_source_code_carries_the_declared_program_verbatim() -> None:
    obj = _parse(_file(_calculation())).canonical
    assert obj.simulation is not None
    assert obj.simulation.source_code == "vasp.5.4.4"
    assert obj.simulation.extra["system"] == "test system"


def test_parser_version_follows_the_package_version() -> None:
    obj = _parse(_file(_calculation())).canonical
    recorded = obj.provenance.history[0].parser_version
    assert recorded is not None
    assert recorded.startswith(f"{FORMAT_ID}-parser {xtalate_version}")


# --- streaming identity (D56) -------------------------------------------------------


def test_streamed_and_materialized_readings_are_identical() -> None:
    data = _file(_calculation(energy=-12.5), _calculation(energy=-13.0))
    whole = _parse(data).canonical
    stream = PARSER.parse_stream(io.BytesIO(data), filename="vasprun.xml")
    streamed, _ = materialize(stream)
    assert streamed.model_dump(mode="json") == whole.model_dump(mode="json")


def test_frame_stream_is_single_pass() -> None:
    data = _file(_calculation())
    stream = PARSER.parse_stream(io.BytesIO(data), filename="vasprun.xml")
    list(stream.frames())
    with pytest.raises(RuntimeError, match="single-pass"):
        list(stream.frames())


# --- the parser-only seam (D159) ----------------------------------------------------


def test_vasprun_registers_parser_only() -> None:
    reg = default_registry()
    assert "vasprun" in {p.format_id for p in reg.parsers()}
    assert "vasprun" not in {e.format_id for e in reg.exporters()}


def test_capabilities_matrix_is_read_only() -> None:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    matrix = reg.capability_matrix()
    assert matrix.get("vasprun", "read").format_id == "vasprun"
    with pytest.raises(KeyError, match="no 'write' capabilities registered"):
        matrix.get("vasprun", "write")


def test_capabilities_render_names_vasprun_read_only() -> None:
    reg = default_registry()
    matrix = reg.capability_matrix()
    declarations = {"vasprun": {"read": matrix.get("vasprun", "read")}}
    out = render.render_capabilities(declarations)
    assert "VASP vasprun.xml [vasprun]" in out
    assert "read-only/parser-only format" in out
    assert "never a conversion target" in out


def test_cli_refuses_vasprun_as_a_conversion_target() -> None:
    # Done-means #2: the real format, not just the S1 dummy, is refused as a `--to` target
    # with the established unknown/unavailable-target error (D159 — no special-casing).
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        main(["convert", str(_GOLDEN), "--to", "vasprun"])


def test_stress_row_is_first_class_since_s3() -> None:
    # S3 promotes electronic.stress to FULL: the mapping is deterministic (VASP declares its
    # convention — D161), and an absent stress block reads None, never a zero tensor (P3).
    caps = PARSER.capabilities()
    assert caps.fields["electronic.stress"].level is CapabilityLevel.FULL
    matrix = default_registry().capability_matrix()
    assert matrix.field_capability("vasprun", "read", "electronic.stress").level is (
        CapabilityLevel.FULL
    )


# --- the VASP stress mapping (D161) --------------------------------------------------


_K_BAR = 1602.1766208  # the exact kBar per eV/Å³ factor, shared with the core


def test_stress_maps_kbar_compression_positive_to_tension_positive_ev_a3() -> None:
    # A known *compressive* state (positive diagonal in kBar) must read *negative* tension
    # in canonical eV/Å³ — the sign flip pinned, not assumed (D161).
    rows = f"""
    <v> {_K_BAR} 0.0 0.0 </v>
    <v> 0.0 {_K_BAR} 0.0 </v>
    <v> 0.0 0.0 {_K_BAR} </v>"""
    obj = _parse(_file(_calculation(stress=rows))).canonical
    stress = obj.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]


def test_stress_exact_factor_and_off_diagonal_sign() -> None:
    rows = f"""
    <v> {_K_BAR} {_K_BAR / 2} 0.0 </v>
    <v> {_K_BAR / 2} {2 * _K_BAR} 0.0 </v>
    <v> 0.0 0.0 {_K_BAR / 10} </v>"""
    obj = _parse(_file(_calculation(stress=rows))).canonical
    stress = obj.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == [
        [-1.0, -0.5, 0.0],
        [-0.5, -2.0, 0.0],
        [0.0, 0.0, -0.1],
    ]


def test_stressless_calculation_reads_none_not_zero() -> None:
    # P3: absence is information — an SCF run without a stress block reads None, never a
    # fabricated zero tensor (D161).
    obj = _parse(_file(_calculation())).canonical
    assert obj.frames[0].electronic.stress is None


def test_stress_per_step_is_independent() -> None:
    rows = f"""
    <v> {_K_BAR} 0.0 0.0 </v>
    <v> 0.0 {_K_BAR} 0.0 </v>
    <v> 0.0 0.0 {_K_BAR} </v>"""
    data = _file(_calculation(stress=rows), _calculation(energy=-13.0))
    obj = _parse(data).canonical
    assert obj.frames[0].electronic.stress is not None
    assert obj.frames[1].electronic.stress is None  # the second step carries no stress block


def test_stress_mapping_is_recorded_in_parse_notes_and_source_units() -> None:
    rows = f"""
    <v> {_K_BAR} 0.0 0.0 </v>
    <v> 0.0 {_K_BAR} 0.0 </v>
    <v> 0.0 0.0 {_K_BAR} </v>"""
    obj = _parse(_file(_calculation(stress=rows))).canonical
    notes = obj.provenance.parse_notes
    assert any("kBar" in n and "tension-positive" in n for n in notes)
    assert obj.provenance.source_units.get("stress") == "kbar"


def test_malformed_stress_block_is_a_parse_error() -> None:
    # A stress varray with the wrong shape is a ParseError under the §5 contract, never a
    # partial or defaulted tensor.
    data = _file(_calculation(stress="\n    <v> 1.0 0.0 </v>\n    <v> 0.0 1.0 </v>\n"))
    with pytest.raises(ParseError) as excinfo:
        _parse(data)
    assert excinfo.value.issues[0].code == "VASPRUN_MALFORMED_XML"


def test_ambiguous_stress_convention_does_not_fire_for_vasp() -> None:
    # Done-means #4: VASP declares its convention, so the conversion completes with **no**
    # unresolved scenario — the convention is mapped at the parser boundary, never asked
    # (v1.1's ambiguous_stress_convention exists for *undeclared* conventions like extXYZ's).
    rows = f"""
    <v> {_K_BAR} 0.0 0.0 </v>
    <v> 0.0 {_K_BAR} 0.0 </v>
    <v> 0.0 0.0 {_K_BAR} </v>"""
    obj = _parse(_file(_calculation(stress=rows))).canonical
    res = ConversionEngine(default_registry()).convert(
        obj, source_format_id="vasprun", target_format_id="extxyz"
    )
    assert res.report.status == "completed"
    assert res.report.refusal is None  # no ambiguous_stress_convention, no other refusal


# --- the VASPRUN_* error contract (D160) --------------------------------------------


def test_empty_file_is_vasprun_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(b"")
    assert excinfo.value.issues[0].code == "VASPRUN_EMPTY"


def test_whitespace_only_file_is_vasprun_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(b"   \n  \n")
    assert excinfo.value.issues[0].code == "VASPRUN_EMPTY"


def test_no_calculation_steps_is_vasprun_empty() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(_file())
    assert excinfo.value.issues[0].code == "VASPRUN_EMPTY"


def test_non_xml_is_vasprun_malformed() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parse(b"this is not XML at all <unclosed")
    assert excinfo.value.issues[0].code == "VASPRUN_MALFORMED_XML"


def test_vasp65_flat_layout_is_refused_not_misread() -> None:
    # VASP 6.5's flat <modeling> layout has no <calculation> blocks; reading it as the
    # classical layout would silently misparse every ionic step (P1) — so it is refused.
    data = (
        b'<modeling><generator><i name="program" >vasp.6.5.0</i></generator><structure/></modeling>'
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(data)
    assert excinfo.value.issues[0].code == "VASPRUN_UNSUPPORTED_LAYOUT"


def test_truncated_file_is_vasprun_truncated() -> None:
    data = _file(_calculation(energy=-12.5), _calculation(energy=-13.0))
    # Cut mid-way through the second <calculation>: one complete step was already yielded.
    truncated = data[: data.rfind(b"</energy>")]
    with pytest.raises(ParseError) as excinfo:
        _parse(truncated)
    issue = excinfo.value.issues[0]
    assert issue.code == "VASPRUN_TRUNCATED"
    assert "complete ionic step(s)" in issue.message


def test_missing_energy_block_is_a_parse_error_not_a_default() -> None:
    calc = """
<calculation>
  <varray name="forces" >
    <v> 0.1 0.0 0.0 </v>
    <v> -0.1 0.0 0.0 </v>
  </varray>
</calculation>"""
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(calc))
    assert excinfo.value.issues[0].code == "VASPRUN_MISSING_BLOCK"


def test_missing_forces_block_is_a_parse_error_not_a_default() -> None:
    calc = """
<calculation>
  <energy>
    <i name="e_0_energy" type="float" > -12.5 </i>
  </energy>
</calculation>"""
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(calc))
    assert excinfo.value.issues[0].code == "VASPRUN_MISSING_BLOCK"


def test_missing_energy_value_is_a_parse_error_not_an_invented_zero() -> None:
    calc = """
<calculation>
  <energy>
    <i name="e_fr_energy" type="float" > -12.5 </i>
  </energy>
  <varray name="forces" >
    <v> 0.1 0.0 0.0 </v>
    <v> -0.1 0.0 0.0 </v>
  </varray>
</calculation>"""
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(calc))
    issue = excinfo.value.issues[0]
    assert issue.code == "VASPRUN_MISSING_BLOCK"
    assert "e_0_energy" in issue.message


def test_missing_species_table_is_a_parse_error() -> None:
    head = _HEAD.replace("<atominfo>", "<atominfo>\n  <atoms> 2 </atoms>")
    head = head.split('<array name="atomtypes">')[0]
    head += "</atominfo>\n"
    with pytest.raises(ParseError) as excinfo:
        _parse(_file(_calculation(), head=head))
    assert excinfo.value.issues[0].code == "VASPRUN_MISSING_BLOCK"


# --- unmapped carries (P1) and warnings ----------------------------------------------


def test_unmapped_energy_scalars_carry_verbatim_with_a_warning() -> None:
    result = _parse(_file(_calculation()))
    obj = result.canonical
    assert obj.user_metadata.custom_per_frame["vasprun:efermi"] == [5.0]
    assert obj.user_metadata.custom_per_frame["vasprun:e_fr_energy"] == [-12.501]
    codes = [i.code for i in result.issues]
    assert codes.count("VASPRUN_UNMAPPED_TAG_CARRIED") >= 2  # e_fr_energy and efermi


def test_unmapped_crystal_scalar_carries_to_simulation_extra() -> None:
    head = _HEAD.replace(
        '    <varray name="basis" >',
        '    <i name="volume" > 64.0 </i>\n    <varray name="basis" >',
    )
    obj = _parse(_file(_calculation(), head=head)).canonical
    assert obj.simulation is not None
    assert obj.simulation.extra["vasprun:volume"] == "64.0"


def test_collapse_frame_issues_aggregates_repeated_carries() -> None:
    from xtalate.sdk import collapse_frame_issues

    data = _file(_calculation(), _calculation(), _calculation())
    result = _parse(data)
    collapsed = collapse_frame_issues(result.issues)
    carries = [i for i in collapsed if i.code == "VASPRUN_UNMAPPED_TAG_CARRIED"]
    # The two per-frame carry codes collapse to one issue each, naming the covered frames.
    assert {i.code for i in carries} == {"VASPRUN_UNMAPPED_TAG_CARRIED"}
    assert all("frames" in i.message for i in carries)


def test_mixed_coordinate_mode_warns_and_converts_each_step_under_its_own_mode() -> None:
    calc_cart = _calculation(energy=-13.0, inner_structure=True, mode="cartesian")
    data = _file(_calculation(energy=-12.5, inner_structure=True), calc_cart)
    result = _parse(data)
    assert any(i.code == "VASPRUN_MIXED_COORDINATE_MODE" for i in result.issues)
    # The cartesian step's positions are read as-is: (0.75, 0.75, 0.75) is already Cartesian.
    assert result.canonical.frames[1].atoms.positions[1].tolist() == [0.75, 0.75, 0.75]
    # Frame 0 (direct) converts through the lattice.
    assert result.canonical.frames[0].atoms.positions[1].tolist() == [3.0, 3.0, 3.0]


def test_header_blocks_outside_the_walked_set_are_skipped() -> None:
    # kpoints/parameters are not walked (out of the S2 surface); their presence must not
    # disturb the parse.
    head = _HEAD.replace(
        "<atominfo>",
        "<kpoints>\n"
        '  <varray name="kpointlist" >\n'
        "    <v> 0.0 0.0 0.0 </v>\n"
        "  </varray>\n"
        "</kpoints>\n"
        "<parameters>\n"
        '  <separator name="general" >\n'
        '    <v name="encut" > 400.0 </v>\n'
        "  </separator>\n"
        "</parameters>\n"
        "<atominfo>",
    )
    obj = _parse(_file(_calculation(), head=head)).canonical
    assert len(obj.frames) == 1
