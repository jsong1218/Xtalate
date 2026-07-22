"""The real-world corpus suite (v0.4 M20, D70).

Runs the CIF parser over Crystallography Open Database entries vendored verbatim and asserts
the two things M20 asks for: **zero silent anomalies** (the issue set a file produces is exactly
the set its manifest names) and **right stoichiometry** (the expansion agrees with the cell
composition the file itself declares — see ``_wild.declared_cell_composition``).

Both assertions are deliberately unforgiving in the same direction: they fail when the parser
changes behaviour on a real file, whether the change looks like an improvement or not. A new
warning on a COD entry is information a human should see and write down, not something a suite
should absorb.
"""

from __future__ import annotations

import pytest

from tests.golden import _governance as gov
from tests.wild import _wild
from xtalate.parsers.cif import make_cif_parser
from xtalate.sdk import ParseError, ParseResult

_CASES = _wild.wild_cases()
_IDS = [c.rel_manifest for c in _CASES]


def _parse(case: gov.GoldenCase) -> ParseResult:
    parser = make_cif_parser()
    with case.source_path.open("rb") as fh:
        return parser.parse(fh, filename=case.source_path.name)


def test_wild_corpus_is_non_empty() -> None:
    # Same reasoning as the golden corpus's own non-emptiness test: a real-world suite that
    # discovers nothing would advertise a confrontation with real files that never happened.
    assert _CASES, "no manifests discovered under tests/wild/ — the real-world corpus is empty"


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_expectation_block_is_well_formed(case: gov.GoldenCase) -> None:
    _wild.load_expectation(case)
    _wild.validate_findings(case)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_issue_codes_are_exactly_as_declared(case: gov.GoldenCase) -> None:
    """The zero-silent-anomalies rule, mechanized.

    Exact-set equality in both directions. An *undeclared* code means the parser found
    something in a real file that no human has triaged — the anomaly M20 exists to surface. A
    *missing* declared code means the parser quietly stopped reporting a known limitation,
    which is the more dangerous of the two: the file still isn't fully modelled, but nothing
    says so any more.
    """
    expectation = _wild.load_expectation(case)

    if expectation.parse_error is not None:
        with pytest.raises(ParseError) as excinfo:
            _parse(case)
        # A ParseError carries the whole issue list; the refusal is identified by its
        # error-severity code, which is what the manifest names.
        codes = sorted(i.code for i in excinfo.value.issues if i.severity == "error")
        assert expectation.parse_error in codes, (
            f"{case.rel_manifest}: expected refusal with code {expectation.parse_error!r}, "
            f"got error codes {codes}"
        )
        return

    result = _parse(case)
    produced = tuple(sorted(issue.code for issue in result.issues))
    assert produced == expectation.issue_codes, (
        f"{case.rel_manifest}: issue codes differ from the manifest.\n"
        f"  declared: {list(expectation.issue_codes)}\n"
        f"  produced: {list(produced)}\n"
        f"  undeclared (new, untriaged): {sorted(set(produced) - set(expectation.issue_codes))}\n"
        f"  declared but absent:         {sorted(set(expectation.issue_codes) - set(produced))}\n"
        "  Every real-file anomaly must be either fixed or named in the manifest by a human "
        "who looked at it (M20 item 1)."
    )


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_expansion_matches_the_files_own_declared_composition(case: gov.GoldenCase) -> None:
    """Wrong stoichiometry is the cardinal sin — and the file itself is the witness."""
    expectation = _wild.load_expectation(case)
    if expectation.parse_error is not None:
        pytest.skip("file is expected to be refused; there is no structure to check")

    text = _wild.source_text_of(case)
    declared = _wild.declared_cell_composition(text)

    if expectation.stoichiometry != "checked":
        # A declared skip must be *justified by the file*, not merely asserted: if the oracle
        # would in fact have worked, the skip is hiding something and the manifest is wrong.
        if expectation.stoichiometry in ("formula_absent", "z_absent"):
            assert isinstance(declared, tuple), (
                f"{case.rel_manifest}: manifest skips the stoichiometry check as "
                f"{expectation.stoichiometry!r}, but the file carries both a formula sum and Z. "
                "Remove the skip."
            )
        pytest.skip(f"stoichiometry not applicable: {expectation.stoichiometry_note}")

    assert not isinstance(declared, tuple), (
        f"{case.rel_manifest}: the stoichiometry check is declared 'checked', but the file is "
        f"missing the tag the oracle needs ({declared[1] if isinstance(declared, tuple) else ''})"
    )

    result = _parse(case)
    frames = result.canonical.frames
    assert len(frames) == expectation.frame_count
    produced = _wild.composition_of(list(frames[0].atoms.symbols))

    assert _wild.compositions_agree(declared, produced), (
        f"{case.rel_manifest}: the expanded structure contradicts the composition the source "
        "file declares for its own unit cell.\n"
        f"  file says (_chemical_formula_sum x _cell_formula_units_Z): {declared}\n"
        f"  parser produced:                                          {produced}\n"
        "  This is the cardinal sin (v0.4 standing rule 4): stop the line."
    )
