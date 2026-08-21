"""The real-world corpus suite (v0.4 M20, D70; VASP cases added in v1.2 M45-S2, D172; LAMMPS
cases added in v1.3 M49-S1, D184).

Runs each case's parser over its vendored file and asserts the two things M20 asks for:
**zero silent anomalies** (the issue set a file produces is exactly the set its manifest names)
and the format's own oracle — **right stoichiometry** for CIF (the expansion agrees with the
cell composition the file itself declares — see ``_wild.declared_cell_composition``), the
**OUTCAR↔vasprun pair-agreement** for VASP output (two readers of one run must agree on
energy/forces/stress/cell/positions, the mechanized form of v1.2 §4 rule 4), or the
**round-trip self-consistency** for the two full read+write LAMMPS formats (a wild file that
parses cleanly under its declared preset is re-exported through its own exporter, re-parsed,
and the two canonical objects asserted scientifically equal — the parser and exporter agreeing
on meaning, the format-native ground truth for formats with no composition tag and no sibling
reader, D184).

Both assertions are deliberately unforgiving in the same direction: they fail when the parser
changes behaviour on a committed file, whether the change looks like an improvement or not. A
new warning on a corpus file is information a human should see and write down, not something a
suite should absorb.

The stoichiometry oracle is CIF-only — a VASP file carries no ``_chemical_formula_sum``/``Z``
tag, so for ``format_id`` in ``{vasprun, outcar}`` it is structurally absent (not a skip).
``electronic.magnetic_moments`` is **excluded** from the pair agreement: it is an OUTCAR-only
field (vasprun.xml has no per-ion magnetization block, D171), so the pair oracle asserts the
honest asymmetry (OUTCAR populates, vasprun leaves ``None``), never agreement — agreement would
be a fake green. The round-trip oracle is LAMMPS-only, and it is a **scientific** round-trip
(canonical ≈ canonical), never byte-identity: a wild file's formatting is not preserved
byte-for-byte (the dump identity is gainy, D178), and a refused case produces no object to
round-trip at all.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pytest

from tests._format_helpers import assert_scientifically_equal, scientific_dump
from tests.golden import _governance as gov
from tests.wild import _wild
from xtalate.conversion import ConversionEngine
from xtalate.exporters.lammps_data import make_lammps_data_exporter
from xtalate.exporters.lammps_dump import make_lammps_dump_exporter
from xtalate.parsers.cif import make_cif_parser
from xtalate.parsers.lammps_data import make_lammps_data_parser
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.parsers.vasprun import make_vasprun_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.sdk import IMAGE_FLAGS_CARRY_KEY, ParseError, ParseResult

_CASES = _wild.wild_cases()
_IDS = [c.rel_manifest for c in _CASES]

#: The stoichiometry oracle applies only to CIF (the one corpus format that declares its own
#: composition). VASP cases are parametrized out of it structurally — not skipped in prose.
_CIF_CASES = [c for c in _CASES if c.data["format_id"] == "cif"]
_CIF_IDS = [c.rel_manifest for c in _CIF_CASES]

#: The round-trip self-consistency oracle applies only to the two full read+write LAMMPS formats
#: (M49-S1, D184) — the only wild formats with an exporter to round-trip through.
_LAMMPS_CASES = [c for c in _CASES if c.data["format_id"] in _wild.ROUNDTRIP_FORMATS]
_LAMMPS_IDS = [c.rel_manifest for c in _LAMMPS_CASES]

#: The parser's recovery hint for each parse-time scenario (the scenario name is the manifest /
#: engine spelling; the dump parser's species hint is ``supply_species``, not ``missing_species``).
_DUMP_HINT_BY_SCENARIO = {
    "ambiguous_units": "ambiguous_units",
    "missing_species": "supply_species",
}


#: The per-atom type carry the dump exporter *gains* on a round-trip — assigned deterministically
#: by first appearance and reported as ``LAMMPSDUMP_TYPES_ASSIGNED`` (D178). The scientific
#: round-trip allows exactly this one audited gain (see :func:`_dump_scientific_dump`).
_DUMP_TYPE_KEY = "lammps_dump:type"


def _parse(case: gov.GoldenCase) -> ParseResult:
    """Parse the case exactly as its manifest says: plain ``parse`` when the file
    self-describes, ``parse_recover`` under the manifest's declared presets when it does not.
    A manifest that declares no preset but a file that needs one refuses — the exact-set test
    then requires the manifest to name the refusal."""
    fmt = case.data["format_id"]
    expectation = _wild.load_expectation(case)
    with case.source_path.open("rb") as fh:
        if fmt == "cif":
            return make_cif_parser().parse(fh, filename=case.source_path.name)
        if fmt == "outcar":
            return make_outcar_parser().parse(fh, filename=case.source_path.name)
        if fmt == "vasprun":
            return make_vasprun_parser().parse(fh, filename=case.source_path.name)
        if fmt == "lammps_dump":
            dump_parser = make_lammps_dump_parser()
            if expectation.parse_recover:
                context = _wild.parse_recovery_specs(expectation.parse_recover)
                scenario, entry = next(iter(context.items()))
                return dump_parser.parse_recover(
                    fh,
                    filename=case.source_path.name,
                    hint=_DUMP_HINT_BY_SCENARIO[scenario],
                    choice=entry["choice"],
                    parameters=entry["parameters"],
                )
            return dump_parser.parse(fh, filename=case.source_path.name)
        if fmt == "lammps_data":
            data_parser = make_lammps_data_parser()
            if expectation.parse_recover:
                context = _wild.parse_recovery_specs(expectation.parse_recover)
                scenario, entry = next(iter(context.items()))
                return data_parser.parse_recover(
                    fh,
                    filename=case.source_path.name,
                    hint=_DUMP_HINT_BY_SCENARIO.get(scenario, scenario),
                    choice=entry["choice"],
                    parameters=entry["parameters"],
                    recovery_context=context,
                )
            return data_parser.parse(fh, filename=case.source_path.name)
    raise AssertionError(f"unknown wild-corpus format_id {fmt!r} in {case.rel_manifest}")


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
    something in a committed file that no human has triaged — the anomaly M20 exists to
    surface. A *missing* declared code means the parser quietly stopped reporting a known
    limitation, which is the more dangerous of the two: the file still isn't fully modelled,
    but nothing says so any more.
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
        "  Every committed-file anomaly must be either fixed or named in the manifest by a "
        "human who looked at it (M20 item 1)."
    )
    assert result.canonical.frame_count == expectation.frame_count, (
        f"{case.rel_manifest}: expected {expectation.frame_count} frame(s), "
        f"parsed {result.canonical.frame_count} — the frame count is part of the expectation, "
        "so a parser that drops or fabricates a step fails here"
    )


@pytest.mark.parametrize("case", _CIF_CASES, ids=_CIF_IDS)
def test_expansion_matches_the_files_own_declared_composition(case: gov.GoldenCase) -> None:
    """Wrong stoichiometry is the cardinal sin — and the file itself is the witness.

    CIF-only: a VASP output file declares no composition, so this oracle is structurally
    absent for ``format_id`` in ``{vasprun, outcar}`` (those cases never reach this test).
    """
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
        f"file declares for its own unit cell.\n"
        f"  file says (_chemical_formula_sum x _cell_formula_units_Z): {declared}\n"
        f"  parser produced:                                          {produced}\n"
        "  This is the cardinal sin (v0.4 standing rule 4): stop the line."
    )


# --- the LAMMPS round-trip self-consistency oracle (M49-S1, D184) -------------------


def _exporter_for(case: gov.GoldenCase) -> Any:
    fmt = case.data["format_id"]
    if fmt == "lammps_dump":
        return make_lammps_dump_exporter()
    if fmt == "lammps_data":
        return make_lammps_data_exporter()
    raise AssertionError(f"no wild-corpus exporter for format_id {fmt!r}")


def _reparse_export(
    case: gov.GoldenCase, exporter: Any, first: CanonicalObject, output: bytes
) -> CanonicalObject:
    """Re-parse this exporter's own output. A dump export always writes a declared ``ITEM:
    UNITS`` header, so it re-parses bare; a data export cannot self-describe (no units, no
    symbols), so its re-parse rides the exporter's ``reparse_recovery`` hook (D182) — the same
    context the Validation Engine primes the re-parse with, derived from the object just
    written."""
    if case.data["format_id"] == "lammps_dump":
        return make_lammps_dump_parser().parse(io.BytesIO(output), filename=None).canonical
    recovery = exporter.reparse_recovery(first)
    assert recovery is not None, (
        f"{case.rel_manifest}: the data exporter produced no re-parse context"
    )
    return (
        make_lammps_data_parser()
        .parse_recover(
            io.BytesIO(output),
            filename=None,
            hint="",
            choice="",
            parameters={},
            recovery_context=recovery,
        )
        .canonical
    )


def _dump_scientific_dump(obj: CanonicalObject) -> dict[str, Any]:
    """The scientific dump with the derived type carry normalised away.

    A dump round-trip deliberately *gains* ``lammps_dump:type`` (numeric types are assigned by
    first appearance on export and reported as ``LAMMPSDUMP_TYPES_ASSIGNED``, D178) — and a
    typed source's own numbering may be renumbered the same reported way. The type numbers are
    format bookkeeping derived from the element symbols, so the self-consistency oracle compares
    everything else exactly and pins the type carry as the one audited difference.
    """
    dumped = scientific_dump(obj)
    per_atom = dumped.get("user_metadata", {}).get("custom_per_atom")
    if isinstance(per_atom, dict):
        per_atom.pop(_DUMP_TYPE_KEY, None)
    return dumped


@pytest.mark.parametrize("case", _LAMMPS_CASES, ids=_LAMMPS_IDS)
def test_lammps_cases_round_trip_self_consistently(case: gov.GoldenCase) -> None:
    """The parser and the exporter agree on meaning for a real file.

    ``dump → Canonical → dump' → Canonical'`` (and the data twin) must be a scientific
    identity: the file parses cleanly under its declared preset, its own exporter re-writes it,
    the output re-parses (bare for a dump — the export declares its units; via ``reparse_recovery``
    for a data file), and the two objects are equal within the strict tolerance profile — the
    M47/M48 identity-round-trip logic, reused. A file whose export is deliberately lossy declares
    ``roundtrip: skipped`` with the reason; a refused file produces no object at all.
    """
    expectation = _wild.load_expectation(case)
    if expectation.parse_error is not None:
        pytest.skip("the file is refused; there is no object to round-trip")
    if expectation.roundtrip != "checked":
        pytest.skip(f"round-trip not applicable: {expectation.roundtrip_note}")

    first = _parse(case).canonical
    exporter = _exporter_for(case)
    out = io.BytesIO()
    exporter.export(first, out)
    second = _reparse_export(case, exporter, first, out.getvalue())

    if case.data["format_id"] == "lammps_data":
        assert_scientifically_equal(first, second)
        return
    # lammps_dump: the type carry is the one audited gain (D178) — nothing else may appear or
    # disappear, and everything else must be scientifically identical.
    gained = set(second.user_metadata.custom_per_atom) - set(first.user_metadata.custom_per_atom)
    lost = set(first.user_metadata.custom_per_atom) - set(second.user_metadata.custom_per_atom)
    assert gained <= {_DUMP_TYPE_KEY}, (
        f"{case.rel_manifest}: the dump round-trip gained unexpected carries {sorted(gained)} "
        f"(only the reported {_DUMP_TYPE_KEY!r} type column may appear)"
    )
    assert not lost, (
        f"{case.rel_manifest}: the dump round-trip dropped carries {sorted(lost)} — a drop is a "
        "silent loss, never acceptable in a round-trip"
    )
    assert _dump_scientific_dump(first) == _dump_scientific_dump(second), (
        f"{case.rel_manifest}: the dump did not round-trip scientifically equal (type carry "
        f"{_DUMP_TYPE_KEY!r} normalised away)"
    )


def _case_by_name(name: str) -> gov.GoldenCase:
    for case in _CASES:
        if case.data["case"] == name:
            return case
    raise AssertionError(f"no wild-corpus case named {name!r}")


def test_variable_n_refusal_measures_per_frame_counts() -> None:
    """The genuine variable-N wild case refuses with the per-frame atom counts in the error
    detail — the accumulating, user-visible v2.0 evidence file the release notes cite (roadmap
    §4/§10). Measured, never anecdotal: the assertion pins the exact counts the file really
    holds, so a fixture that stopped being variable-N (or a parser that stopped measuring)
    fails here."""
    case = _case_by_name("dump-variable-n-deposition")
    expectation = _wild.load_expectation(case)
    assert expectation.parse_error == "LAMMPSDUMP_VARIABLE_ATOM_COUNT"
    with pytest.raises(ParseError) as excinfo:
        _parse(case)
    codes = sorted(i.code for i in excinfo.value.issues if i.severity == "error")
    assert codes == ["LAMMPSDUMP_VARIABLE_ATOM_COUNT"]
    message = excinfo.value.issues[0].message
    # Frame 0 declares 3 atoms, the first diverging frame declares 4 — the refusal lists the
    # per-frame counts seen so far, never padding or truncation.
    assert "Per-frame counts seen: [3, 4]" in message, message


def test_image_flags_case_predicts_unwrapping_loss_on_export() -> None:
    """The realistic wrapped + image-flags dump confirms the M46 correctness obligation on a
    wild file: targeting a format that cannot hold the flags predicts the unwrapping loss via
    the ordinary pre-flight ``custom_global``-independent capability diff (M46-S3, D176) — the
    output looks correct but can no longer be unwrapped, and the Conversion Report says so."""
    case = _case_by_name("dump-declared-metal-image-flags")
    canonical = _parse(case).canonical
    assert IMAGE_FLAGS_CARRY_KEY in canonical.user_metadata.custom_per_atom
    engine = ConversionEngine(default_registry())
    result = engine.convert(
        canonical,
        source_format_id="lammps_dump",
        target_format_id="extxyz",
    )
    assert result.report.status == "completed"
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" in {w.code for w in result.report.warnings}, (
        "the conversion did not predict the unwrapping loss for a wrapped wild dump"
    )


# --- the OUTCAR↔vasprun pair-agreement oracle (D172) -----------------------------


def _resolve_pairs() -> list[tuple[gov.GoldenCase, gov.GoldenCase]]:
    """Every declared ``expectation.pair``, resolved to its sibling case, in manifest order.

    A pair is a VASP case (OUTCAR) naming the sibling case of the *other* format (vasprun)
    for the same run. Resolution is eager so a dangling or same-format pair fails loudly
    rather than silently leaving the oracle unexercised.
    """
    by_name = {c.data["case"]: c for c in _CASES}
    pairs: list[tuple[gov.GoldenCase, gov.GoldenCase]] = []
    for case in _CASES:
        pair_name = _wild.load_expectation(case).pair
        if pair_name is None:
            continue
        sibling = by_name.get(pair_name)
        assert sibling is not None, f"{case.rel_manifest}: pair {pair_name!r} not found"
        formats = {case.data["format_id"], sibling.data["format_id"]}
        assert formats == {"outcar", "vasprun"}, (
            f"{case.rel_manifest}: pair {pair_name!r} must be the *other* VASP format, "
            f"got {sorted(formats)}"
        )
        pairs.append((case, sibling))
    return pairs


_PAIRS = _resolve_pairs()


def _assert_close(a: np.ndarray | None, b: np.ndarray | None) -> None:
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12)


def _assert_vasp_agreement(outcar: CanonicalObject, vasprun: CanonicalObject) -> None:
    """Two readers of one run must agree on what both carry (v1.2 §4 rule 4).

    Mirrors ``tests/parsers/test_outcar_crosscheck.py`` — energy/forces/stress/cell/positions,
    the exact field set the two spellings map back to the same canonical values.
    ``electronic.magnetic_moments`` is deliberately **not** compared here (OUTCAR-only).
    """
    assert len(outcar.frames) == len(vasprun.frames)
    for fa, fb in zip(outcar.frames, vasprun.frames, strict=True):
        assert fa.index == fb.index
        assert fa.atoms.symbols == fb.atoms.symbols
        assert fa.electronic.total_energy == fb.electronic.total_energy
        _assert_close(fa.atoms.positions, fb.atoms.positions)
        _assert_close(fa.dynamics.forces, fb.dynamics.forces)
        _assert_close(fa.electronic.stress, fb.electronic.stress)
        assert fa.cell is not None and fb.cell is not None
        _assert_close(fa.cell.lattice_vectors, fb.cell.lattice_vectors)


def test_the_corpus_has_at_least_one_vasp_pair() -> None:
    assert _PAIRS, (
        "no OUTCAR↔vasprun pair declared in the wild corpus — the pair-agreement oracle "
        "(v1.2 §4 rule 4) would be unexercised"
    )


@pytest.mark.parametrize("pair", _PAIRS, ids=lambda p: f"{p[0].data['case']}↔{p[1].data['case']}")
def test_paired_vasp_cases_agree(pair: tuple[gov.GoldenCase, gov.GoldenCase]) -> None:
    a_case, b_case = pair
    a = _parse(a_case).canonical
    b = _parse(b_case).canonical

    outcar = a if a_case.data["format_id"] == "outcar" else b
    vasprun = b if a_case.data["format_id"] == "outcar" else a
    _assert_vasp_agreement(outcar, vasprun)

    # The honest asymmetry (D171): magnetic moments are an OUTCAR-only artifact, so the
    # vasprun side must leave them None — asserting agreement would be a fake green. If the
    # run is spin-polarized the OUTCAR side populates every frame; if not, it is all None too.
    assert all(f.electronic.magnetic_moments is None for f in vasprun.frames)
    outcar_moments = [f.electronic.magnetic_moments for f in outcar.frames]
    if any(m is not None for m in outcar_moments):
        assert all(m is not None for m in outcar_moments), (
            "a spin-polarized OUTCAR maps the moments on every frame — a partial mapping "
            "would be a silent per-frame loss"
        )
