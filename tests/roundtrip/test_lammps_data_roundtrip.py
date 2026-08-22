"""LAMMPS data identity round-trips (v1.3 M48-S3; Part 3 §3): ``data → Canonical → data' →
Canonical'``. This is the end-to-end proof that M48-S2's exporter and M48-S1's parser agree — the
checkpoint that closes the staging state and makes ``lammps_data`` a full read+write format.

Unlike the LAMMPS *dump* identity (deliberately *gainy* — a dump gains a reported numeric ``type``
column, D178) and unlike CIF (deliberately *lossy*, D68), a data round-trip is a **clean scientific
identity**: a data file already carries its own id / molecule-id / type / image-flag / charge
columns, so a faithful re-export reproduces every one of them and nothing is added or dropped. The
round-trip therefore uses bare ``assert_scientifically_equal`` — the strong claim that the data
parser and exporter are true inverses.

Two things about this identity are unique to a data file, and both are tested here:

* **The write needs the recovery the read needed.** A data file states no unit system, so *writing*
  one requires a declared style just as *reading* one did. The round-trip supplies
  ``ambiguous_units=<style>`` (matching the source's own style) as a ``recovery_choice`` on the
  ``convert`` — and re-reads the output through the exporter's ``reparse_recovery`` hook (D181), the
  same context the Validation Engine primes the re-parse with, because the written bytes cannot
  self-describe either.
* **Topology is carried, not modelled — so it must survive byte-for-byte.** Bonds / Bond Coeffs and
  their header counts live in ``custom_global['lammps_data:topology']`` verbatim (M48-S1); the
  ``full-triclinic-topology`` fixture proves they re-emit character-for-character, the write-back
  faithfulness M48-S2 promised.

Routes through the materialized ``ConversionEngine.convert`` (not ``convert_stream``): a data file
is a single configuration and the round-trip needs the whole output object to re-parse and diff.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_scientifically_equal
from xtalate.conversion import ConversionEngine
from xtalate.exporters.lammps_data import make_lammps_data_exporter
from xtalate.parsers.lammps_data import make_lammps_data_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_data"

# Each fixture's declared style + the type→symbol map its source needed (Part 3 §3; mirrors the
# parser suite's ``_CASES``). The style is threaded both ways: as the parse-time ``ambiguous_units``
# recovery *and* as the write-time ``ambiguous_units`` choice the data target requires.
_CASES: dict[str, tuple[str, str]] = {
    "atomic-metal-ortho": ("metal", "1:Ar 2:Ne"),
    "charge-real-velocities": ("real", "1:O 2:H"),
    "full-triclinic-topology": ("metal", "1:C 2:H"),
}


def _parse_source(case: str, style: str, species: str) -> CanonicalObject:
    parser = make_lammps_data_parser()
    ctx = {
        "ambiguous_units": {"choice": style, "parameters": {}},
        "missing_species": {"choice": "species_map", "parameters": {"species": species}},
    }
    return parser.parse_recover(
        io.BytesIO((GOLDEN / case / "structure.data").read_bytes()),
        filename="structure.data",
        hint="ambiguous_units",
        choice=style,
        parameters={},
        recovery_context=ctx,
    ).canonical


def _section_body(text: str, name: str) -> list[str]:
    """The non-blank data rows under a named section header (``Bonds``, ``Bond Coeffs``, …), up to
    the next section header. Used to assert topology re-emits byte-for-byte."""
    lines = text.splitlines()
    body: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == name:
            inside = True
            continue
        if inside:
            # A new section header is a single capitalised word-ish token line with no numbers; the
            # simplest robust boundary is "a non-empty line whose first token is not an integer".
            if stripped and not stripped.split()[0].lstrip("-").isdigit():
                break
            if stripped:
                body.append(stripped)
    return body


@pytest.mark.parametrize(
    ("case", "style", "species"), [(c, s, sp) for c, (s, sp) in _CASES.items()]
)
def test_lammps_data_identity_round_trip(case: str, style: str, species: str) -> None:
    """``data → Canonical → data' → Canonical'`` is an exact scientific identity for every golden:
    the atomic-style orthogonal cell, the charge+velocity real-units case, and the full-style
    triclinic case with a molecule-id, image flags, and carried topology all round-trip with no gain
    and no loss. The write requires the same declared unit style the read did — supplied as the
    ``ambiguous_units`` recovery choice — and the output is re-read through ``reparse_recovery``
    because the written bytes cannot self-describe."""
    source = _parse_source(case, style, species)
    engine = ConversionEngine(default_registry())

    result = engine.convert(
        source,
        source_format_id="lammps_data",
        target_format_id="lammps_data",
        recovery_choices={"ambiguous_units": {"choice": style, "parameters": {}}},
    )
    assert result.report.status == "completed"
    assert result.output is not None
    # Validation re-reads the non-self-describing output for us and diffs it — it must pass, and it
    # is the same recovery-aware re-parse we then repeat by hand to compare objects (D181).
    assert result.validation is not None
    expected_validation_status = (
        "passed_with_warnings" if case == "full-triclinic-topology" else "passed"
    )
    assert result.validation.status == expected_validation_status

    parser = make_lammps_data_parser()
    exporter = make_lammps_data_exporter()
    recovery = exporter.reparse_recovery(result.canonical_out)
    assert recovery is not None
    roundtrip = parser.parse_recover(
        io.BytesIO(result.output),
        filename=None,
        hint="",
        choice="",
        parameters={},
        recovery_context=recovery,
    ).canonical

    assert_scientifically_equal(source, roundtrip)


def test_lammps_data_round_trip_writes_topology_back_byte_for_byte() -> None:
    """The topology carry is *bytes*, not a model, so faithfulness is a byte claim (M48-S2): the
    ``full-triclinic-topology`` fixture's Bonds and Bond Coeffs rows — and the ``N bonds`` /
    ``N bond types`` header counts — re-emit character-for-character. A data file carries topology
    in ``custom_global['lammps_data:topology']`` verbatim (P1: never re-derived, never dropped), so
    this proves the write-back reproduces it exactly rather than paraphrasing it."""
    style, species = _CASES["full-triclinic-topology"]
    source_text = (GOLDEN / "full-triclinic-topology" / "structure.data").read_text()
    source = _parse_source("full-triclinic-topology", style, species)
    engine = ConversionEngine(default_registry())

    result = engine.convert(
        source,
        source_format_id="lammps_data",
        target_format_id="lammps_data",
        recovery_choices={"ambiguous_units": {"choice": style, "parameters": {}}},
    )
    assert result.output is not None
    output_text = result.output.decode("utf-8")

    # The fixture really carries topology, or the check proves nothing.
    assert _section_body(source_text, "Bonds"), "fixture has no Bonds section"
    for section in ("Bonds", "Bond Coeffs"):
        assert _section_body(output_text, section) == _section_body(source_text, section), (
            f"{section} did not re-emit byte-for-byte"
        )
    # The header counts survive too — a data file states its own bond totals.
    for count_line in ("7 bonds", "1 bond types"):
        assert count_line in output_text
