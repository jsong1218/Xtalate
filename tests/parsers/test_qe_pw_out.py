"""qe_pw_out parser unit tests (v1.4 M52-S1/S2).

The error contract (Part 3 §5; the base ``QEOUT_*`` code set of D195 plus S2's
``QEOUT_UNRECOGNIZED_LAYOUT`` / ``QEOUT_INCONSISTENT_STEP`` / ``QEOUT_UNCONVERGED`` of D196),
the streaming/materialized identity (D56), the unmapped-block carries (P1), the parser-only
capability seam (D159), and the shared-core mapping choices (D195) — pinned here with inline
synthetic files, on top of the governed goldens in ``tests/golden/``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests.parsers._qe_run import render_pw_out
from xtalate.capabilities import Registry
from xtalate.cli import render
from xtalate.cli.main import main
from xtalate.parsers import builtin_parsers
from xtalate.parsers.qe_pw_out import FORMAT_ID, QePwOutParser, make_qe_pw_out_parser
from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel, ParseError
from xtalate.sdk.streaming import materialize

PARSER = make_qe_pw_out_parser()

#: A minimal clean 7.x run: header + one ionic step (energy, forces, stress, positions).
_MINIMAL = render_pw_out("7x")


# --- sniff ----------------------------------------------------------------------------


def test_sniff_prefers_the_pwscf_banner() -> None:
    assert PARSER.sniff(_MINIMAL.encode(), None) == 1.0
    assert PARSER.sniff(_MINIMAL.encode(), "pw.out") == 1.0  # the name adds nothing


def test_sniff_beats_the_input_parser_on_a_pw_x_output() -> None:
    """A pw.x output carries ATOMIC_POSITIONS cards, which the *input* parser's sniff would
    claim at 1.0 — the banner is the discriminator: the input parser defers to it, so a
    pw.out auto-sniffs as the output parser (D195), never as a broken input parse."""
    from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser

    out = PARSER.sniff(_MINIMAL.encode(), "pw.out")
    inp = make_qe_pw_in_parser().sniff(_MINIMAL.encode(), "pw.out")
    assert out == 1.0
    assert inp == 0.0


def test_sniff_zero_on_unrelated_text() -> None:
    assert PARSER.sniff(b"hello world\nsome other file\n", "pw.out") == 0.0


def test_sniff_zero_on_empty() -> None:
    assert PARSER.sniff(b"", "pw.out") == 0.0


# --- the error contract (S1 base codes) -----------------------------------------------


def test_empty_file_raises_qeout_empty() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(b"   \n  \n"), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_EMPTY"


def test_unrecognizable_file_raises_qeout_unrecognized_layout() -> None:
    """No version banner and no energy line — not a recognizable pw.x run. S2's
    QEOUT_UNRECOGNIZED_LAYOUT refusal: never a silent partial parse (P1), with the
    corpus-contribution call (D196)."""
    text = "some random text\nwithout any pw.x anchors\n"
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    issue = exc.value.issues[0]
    assert issue.code == "QEOUT_UNRECOGNIZED_LAYOUT"
    assert "corpus" in issue.message


def test_banner_but_unrecognizable_header_raises_unrecognized_layout() -> None:
    """A real banner with a header that cannot be recognized (no species / counts / cell /
    positions) is QEOUT_UNRECOGNIZED_LAYOUT — a QE layout beyond 6.x/7.x is refused, never
    partial-parsed (P1), and this is the S2 reclassification of S1's missing-block raises."""
    text = "     Program PWSCF v.7.2 (enter)\nstarting calculation\ngarbage that is not a layout\n"
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_UNRECOGNIZED_LAYOUT"


def test_recognized_header_with_zero_steps_raises_qeout_empty() -> None:
    """A banner + complete header but no '!    total energy' line: no ionic step at all."""
    header = _MINIMAL.split("!\n", 1)[0]
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(header.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_EMPTY"


def test_missing_species_table_raises_unrecognized_layout() -> None:
    """A header whose species table is missing cannot be recognized as a 6.x/7.x run — S2
    reclassifies S1's QEOUT_MISSING_BLOCK raises here (D196)."""
    text = _MINIMAL.replace("     Atomic species   valence    mass     pseudopotential\n", "")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_UNRECOGNIZED_LAYOUT"


def test_missing_cell_raises_unrecognized_layout() -> None:
    text = _MINIMAL.replace("     crystal axes: (cart. coord. in units of alat)\n", "")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_UNRECOGNIZED_LAYOUT"


def test_missing_initial_positions_raises_unrecognized_layout() -> None:
    text = _MINIMAL.replace("     site n.     atom                  positions (bohr units)\n", "")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_UNRECOGNIZED_LAYOUT"


def test_non_utf8_bytes_raise_the_encoding_error() -> None:
    with pytest.raises(ParseError) as exc:
        list(PARSER.parse_stream(io.BytesIO(b"\xff\xfe bad"), filename="pw.out").frames())
    assert exc.value.issues[0].code == "QEOUT_ENCODING_ERROR"


# --- M52-S2: the drift refusals + the convergence flag (D196) ---------------------------


def test_force_block_longer_than_the_header_atom_count_refuses() -> None:
    """A step whose force rows exceed the header's atom count is QEOUT_INCONSISTENT_STEP —
    never silently truncated to the shorter (P3)."""
    text = _MINIMAL.replace(
        "     atom 3 type 2   force =     -0.00500000   +0.00900000   -0.00100000\n",
        "     atom 3 type 2   force =     -0.00500000   +0.00900000   -0.00100000\n"
        "     atom 4 type 2   force =     -0.00600000   +0.00800000   -0.00200000\n",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_INCONSISTENT_STEP"


def test_force_block_shorter_than_the_header_atom_count_refuses() -> None:
    """A step whose force rows fall short of the header's atom count (the block ends on a
    blank while the stream continues — not a torn tail) is QEOUT_INCONSISTENT_STEP, never a
    silently accepted shorter block (P3)."""
    text = _MINIMAL.replace(
        "     atom 3 type 2   force =     -0.00500000   +0.00900000   -0.00100000\n",
        "",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_INCONSISTENT_STEP"


def test_positions_card_longer_than_the_header_atom_count_refuses() -> None:
    text = _MINIMAL.replace(
        "     H   2.500000000   3.250000000   2.500000000\n",
        "     H   2.500000000   3.250000000   2.500000000\n"
        "     H   2.500000000   3.300000000   2.500000000\n",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_INCONSISTENT_STEP"


def test_malformed_step_block_raises_unrecognized_layout() -> None:
    """A step block that is present but unparseable — not a torn tail — is the layout
    refusal: a 6.x/7.x force row is the recognized form, and a layout that prints something
    else is refused, never partially read (P1)."""
    text = _MINIMAL.replace(
        "     atom 1 type 1   force =     +0.01000000   -0.02000000   +0.00000000\n",
        "     atom 1 type 1   force =     NaN   NaN   NaN\n",
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_UNRECOGNIZED_LAYOUT"


def test_unconverged_run_warns_and_still_reads_the_energy() -> None:
    """QE's own 'convergence NOT achieved after N iterations' statement fires the
    QEOUT_UNCONVERGED warning carrying it verbatim, while the step's energy is still read
    present-with-value (P3) — the honesty is in surfacing the flag, never withholding the
    value (D196)."""
    text = _MINIMAL.replace(
        "convergence has been achieved in  10 iterations",
        "convergence NOT achieved after  50 iterations",
        1,  # only the first SCF of the three-step run is unconverged
    )
    result = PARSER.parse(io.BytesIO(text.encode()), filename="pw.out")
    warnings = [i for i in result.issues if i.code == "QEOUT_UNCONVERGED"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert "convergence NOT achieved after  50 iterations" in warnings[0].message
    assert result.canonical.frames[0].electronic.total_energy is not None
    assert result.canonical.frames[0].electronic.total_energy == pytest.approx(
        -49.12345678 * 13.605693122994
    )


# --- streamed == materialized (D56) ---------------------------------------------------


def test_streamed_parse_materializes_to_the_whole_file_parse() -> None:
    stream = PARSER.parse_stream(io.BytesIO(_MINIMAL.encode()), filename="pw.out")
    streamed, _issues = materialize(stream)
    whole = PARSER.parse(io.BytesIO(_MINIMAL.encode()), filename="pw.out").canonical
    assert json.loads(streamed.model_dump_json()) == json.loads(whole.model_dump_json())


def test_streaming_yields_one_frame_at_a_time() -> None:
    frames = PARSER.parse_stream(io.BytesIO(_MINIMAL.encode()), filename="pw.out").frames()
    first = next(frames)
    assert first.frame.index == 0
    assert first.frame.electronic.total_energy is not None


# --- provenance -----------------------------------------------------------------------


def test_provenance_records_the_qe_source_units() -> None:
    obj = PARSER.parse(io.BytesIO(_MINIMAL.encode()), filename="pw.out").canonical
    assert obj.provenance.source_format == FORMAT_ID
    assert obj.provenance.source_units == {
        "positions": "bohr",
        "lattice_vectors": "alat",
        "energy": "rydberg",
        "forces": "rydberg/bohr",
        "stress": "rydberg/bohr^3",
    }
    assert obj.provenance.original_coordinate_system == "cartesian"


# --- the parser-only seam (D159/D195) -------------------------------------------------


def test_qe_pw_out_registers_parser_only() -> None:
    reg = default_registry()
    assert "qe_pw_out" in {p.format_id for p in reg.parsers()}
    assert "qe_pw_out" not in {e.format_id for e in reg.exporters()}


def test_capabilities_matrix_is_read_only() -> None:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    matrix = reg.capability_matrix()
    assert matrix.get("qe_pw_out", "read").format_id == "qe_pw_out"
    with pytest.raises(KeyError, match="no 'write' capabilities registered"):
        matrix.get("qe_pw_out", "write")


def test_capabilities_render_names_qe_pw_out_read_only() -> None:
    reg = default_registry()
    matrix = reg.capability_matrix()
    declarations = {"qe_pw_out": {"read": matrix.get("qe_pw_out", "read")}}
    out = render.render_capabilities(declarations)
    assert "Quantum ESPRESSO pw.x output [qe_pw_out]" in out
    assert "read-only/parser-only format" in out
    assert "never a conversion target" in out


def test_cli_refuses_qe_pw_out_as_a_conversion_target() -> None:
    _GOLDEN = str(Path(__file__).parent.parent / "golden" / "qe_pw_out" / "relax" / "pw.out")
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        main(["convert", _GOLDEN, "--to", "qe_pw_out"])


def test_capabilities_declare_the_label_complete_field_set() -> None:
    caps = PARSER.capabilities()
    assert caps.direction == "read"
    assert caps.max_frames is None
    assert caps.required_fields == []
    assert caps.fields["electronic.total_energy"].level is CapabilityLevel.FULL
    assert caps.fields["dynamics.forces"].level is CapabilityLevel.FULL
    assert caps.fields["electronic.stress"].level is CapabilityLevel.FULL
    assert caps.fields["atoms.positions"].level is CapabilityLevel.FULL
    assert caps.fields["atoms.positions"].notes is not None
    assert "declared per-block unit" in caps.fields["atoms.positions"].notes


# --- the mappings are the shared core's (D195) ----------------------------------------


def test_the_label_core_owns_the_output_mappings() -> None:
    """The mapping constants/functions live in the _qe output core, never inlined in the
    reader — two parsers reading one run cannot co-discover divergent mappings."""
    from xtalate.parsers import _qe
    from xtalate.parsers._qe import labels

    assert _qe.labels.RY_TO_EV == 13.605693122994  # QE's RYTOEV
    assert labels.RY_TO_EV == 13.605693122994
    # The core is a mapping layer: it never imports the reader (the P2 boundary), so no
    # module attribute can be the reader module.
    assert not any(
        getattr(v, "__name__", "") == "xtalate.parsers.qe_pw_out" for v in vars(labels).values()
    )


def test_parser_is_a_plugin_instance() -> None:
    assert isinstance(PARSER, QePwOutParser)
    assert PARSER.format_id == "qe_pw_out"
    assert PARSER.version == "0.1.0"
