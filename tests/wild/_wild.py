"""The real-world corpus: expectation schema and the file's-own-chemistry oracle (D70).

``tests/golden/`` proves the parser against expectations a human wrote down. This corpus proves
it against files a human never saw before — Crystallography Open Database entries, vendored
verbatim — and the difference forces a different kind of expectation.

**Why not a canonical JSON per case.** A hand-verified ``expected.canonical.json`` for a real
COD entry is not hand-verifiable: nobody can eyeball 192 symmetry-expanded coordinates and
attest to them. Writing one anyway would mean transcribing whatever the parser printed on the
day it was added, which records the implementation rather than the truth and turns the strongest
kind of test into the weakest. So a wild case declares two things instead:

* **The exact set of issue codes the file must produce.** Not a minimum — the *exact* set. This
  is the mechanized form of M20's "zero silent anomalies": an anomaly the parser starts emitting
  that the manifest does not name fails the suite, and so does one it silently stops emitting.
  Every real-file surprise therefore ends as M20 requires — a fix, or a named, reviewed
  ``ParseIssue`` written into a manifest by a human who looked at it.

* **Nothing about stoichiometry**, because the file already knows. A CIF carries
  ``_chemical_formula_sum`` and ``_cell_formula_units_Z``, and their product is the unit cell's
  own account of what it contains. That is an oracle the parser never sees and the fixture author
  never types: :func:`declared_cell_composition` reads it straight from the source text, and the
  suite checks the expansion against it. A symmetry bug that produces the wrong atom count now
  contradicts the very file that produced it — which is the cardinal sin (v0.4 standing rule 4)
  caught by the file itself rather than by a number someone hoped was right.

The oracle does not always apply: partial occupancy makes the count non-integral, and older
entries omit ``Z`` or the formula. Those cases name a reason from :data:`SKIP_REASONS` *and*
write it out in prose, so a skipped check is a recorded judgement and never a silent pass.

The oracle is CIF-specific. A VASP output file (OUTCAR / vasprun.xml) carries no
``_chemical_formula_sum``/``Z`` equivalent, so there is nothing for it to read — the
stoichiometry check is **format-gated** to ``format_id: cif`` and structurally absent for
``vasprun``/``outcar`` (D172). In its place a VASP case may declare an ``expectation.pair:``
naming the sibling case of the *other* VASP format for the same run, and the suite asserts the
two readers agree on energy/forces/stress/cell/positions — with ``electronic.magnetic_moments``
excluded, because it is an OUTCAR-only field (vasprun.xml carries no per-ion magnetization
block), so the pair oracle asserts the honest **asymmetry**, never agreement.

The LAMMPS formats (``lammps_dump`` / ``lammps_data``, v1.3 M46–M48) have **neither** oracle:
a dump/data file declares no composition and has no sibling second-reader of the same run. But
both are **full read+write** (unlike the parser-only VASP formats), so the format-native ground
truth is a **scientific round-trip within tolerance** — the ``roundtrip`` oracle (M49-S1,
D184): a wild file that parses cleanly (under the manifest's declared ``parse_recover``
preset) is re-exported through its **own** exporter, re-parsed, and the two canonical objects
asserted equal (``assert_scientifically_equal``, the M47/M48 identity-round-trip logic — for
``lammps_data`` the non-self-describing re-parse rides the exporter's ``reparse_recovery``
hook, D182). It is a **self-consistency** oracle (the parser and exporter agree on meaning),
not a correctness oracle against an external truth — which is exactly what the exact
issue-code + frame-count expectations cover alongside it. And it is **scientific**, not
byte-identity: a wild file's arbitrary formatting is not preserved byte-for-byte (the dump
identity is itself gainy, D178), so byte-identity would be a false-red.

``roundtrip`` is format-gated exactly like ``stoichiometry``: ``ROUNDTRIP_FORMATS`` declares
which formats the oracle applies to, and a non-LAMMPS manifest declaring it is rejected. A
refused case (``parse_error: true``) produces no object to round-trip, so it sets neither
oracle. A LAMMPS case whose export is deliberately lossy (e.g. the dump exporter does not write
``ITEM: TIME`` carries) declares ``roundtrip: skipped`` with a stated reason — never a silent
pass.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from tests.golden import _governance as gov

WILD_ROOT = gov.WILD_ROOT

# "Na2 Cl2", "Ca0.5 Al Si O4", "H2O" — element symbol followed by an optional count, which CIF
# allows to be fractional (a partially occupied site contributes a fraction of an atom).
_FORMULA_TERM = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")

# The two tags the oracle reads. Both are pair values, never loop columns.
_FORMULA_TAG = "_chemical_formula_sum"
_Z_TAG = "_cell_formula_units_z"

# Why a stoichiometry check may be skipped. Each value is a *reason shape*, and the manifest
# must still spell out the specific reason in prose — the vocabulary keeps the reasons
# comparable across cases without flattening them into a checkbox.
SKIP_REASONS = ("partial_occupancy", "formula_absent", "z_absent", "formula_disagrees_with_source")

#: The formats the file's-own-chemistry oracle applies to. CIF is the only corpus format that
#: carries ``_chemical_formula_sum``/``Z``; VASP output has no self-declared composition tag, so
#: the stoichiometry check is format-gated (D172). For a non-CIF format it is structurally
#: absent — not a skip reason, which is a recorded judgement about a check that *could* have
#: run. The pair-agreement oracle (``expectation.pair``) takes its place for VASP.
STOICH_FORMATS = frozenset({"cif"})
STOICH_NOT_APPLICABLE = "not_applicable"

#: The formats the round-trip self-consistency oracle applies to (M49-S1, D184): the two full
#: read+write LAMMPS formats. They carry no self-declared composition (no stoichiometry) and have
#: no sibling second-reader of one run (no pair-agreement) — but being full read+write, the
#: format-native ground truth is a scientific round-trip through each format's own exporter,
#: canonical ≈ canonical within tolerance. For a non-LAMMPS format the oracle is structurally
#: absent, exactly like stoichiometry is for a non-CIF format.
ROUNDTRIP_FORMATS = frozenset({"lammps_dump", "lammps_data"})
ROUNDTRIP_NOT_APPLICABLE = "not_applicable"

#: The parse-time recovery scenarios a LAMMPS wild manifest may declare via ``parse_recover`` /
#: ``roundtrip_recover`` (the M46/M48 parse-time scenarios — units, species, atom style). The
#: spelling is the engine/CLI scenario name, not the parser's recovery *hint* (which differs for
#: species: ``supply_species``).
_PARSE_TIME_SCENARIOS = frozenset({"ambiguous_units", "missing_species", "ambiguous_atom_style"})


class WildExpectationError(ValueError):
    """A wild-corpus manifest's ``expectation`` block is malformed."""


@dataclass(frozen=True)
class WildExpectation:
    """What a real file is expected to do, as declared in its manifest."""

    issue_codes: tuple[str, ...]
    """The **exact** multiset of ``ParseIssue.code`` values, sorted. Not a subset."""

    parse_error: str | None
    """If set, the file must be *refused* with a ``ParseError`` carrying this code, and
    ``issue_codes`` must be empty. A refusal is a legitimate outcome for a real file — D66's
    symbol-without-operations case is precisely one — and is far better than a partial
    structure, so the corpus must be able to assert one."""

    stoichiometry: str
    """``"checked"``, or one of :data:`SKIP_REASONS`."""

    stoichiometry_note: str
    """Prose reason, required whenever ``stoichiometry`` is not ``"checked"``."""

    frame_count: int
    """A CIF block is one structure; this is 1 for every case so far, but declaring it keeps
    the assertion honest if a future format enters this corpus."""

    pair: str | None
    """The ``case`` name of the sibling VASP file of the *other* format for the same run, or
    ``None``. Drives the OUTCAR↔vasprun pair-agreement oracle (D172): the suite parses both
    and asserts agreement on energy/forces/stress/cell/positions, with
    ``electronic.magnetic_moments`` excluded (an OUTCAR-only field — vasprun.xml carries no
    per-ion magnetization block)."""

    parse_recover: tuple[str, ...]
    """CLI-style recovery preset strings (``SCENARIO=CHOICE[,param=value…]``) the manifest
    declares this file needs to parse at all — e.g. ``ambiguous_units=metal`` for an
    undeclared-units dump, or ``missing_species=species_map,species=1:Si 2:O`` for a typed
    one. Empty when the file self-describes (a declared ``ITEM: UNITS`` dump, an
    element-labeled dump). A LAMMPS file that needs a preset refuses a bare parse, so a
    manifest that names a preset here commits the suite to driving ``parse_recover`` (M49-S1);
    the recovery's own note warnings (``LAMMPSDUMP_UNITS_INTERPRETED`` /
    ``LAMMPSDUMP_SPECIES_SUPPLIED`` / ``LAMMPSDATA_ATOM_STYLE_INTERPRETED`` …) then appear in
    the exact issue-code multiset, because a recovery is never silent (P1)."""

    roundtrip: str
    """``"checked"``, one of :data:`SKIP_REASONS`-style stated judgements via
    ``roundtrip_note``, or ``not_applicable`` for a non-LAMMPS format. The round-trip
    self-consistency oracle (M49-S1, D184): the file is parsed (with its declared
    ``parse_recover``), re-exported through its own exporter, re-parsed, and the two canonical
    objects asserted scientifically equal — the parser and exporter agreeing on meaning."""

    roundtrip_note: str
    """Prose reason, required whenever ``roundtrip`` is not ``"checked"`` — a skipped
    round-trip is a recorded judgement (the export is deliberately lossy for this file, or the
    file is refused), never a silent pass."""

    roundtrip_recover: tuple[str, ...]
    """CLI-style recovery preset strings the re-parse of the *exported output* needs, when it
    does not self-describe (the plan's ``roundtrip_recover: "ambiguous_units=metal"`` case).
    Empty for the ordinary cases: a dump export always writes a declared ``ITEM: UNITS``
    header, and a data export is re-read through the exporter's own ``reparse_recovery`` hook
    (D182) — so batch 1 leaves it empty, but the slot is validated for the case that needs
    it."""


def load_expectation(case: gov.GoldenCase) -> WildExpectation:
    """Parse and validate the ``expectation`` block of a wild manifest."""

    raw = case.data.get("expectation")
    where = case.rel_manifest
    format_id = case.data.get("format_id")
    if not isinstance(raw, dict):
        raise WildExpectationError(f"{where}: 'expectation' must be a mapping")

    parse_error = raw.get("parse_error")
    codes = raw.get("issue_codes", [])
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise WildExpectationError(f"{where}: 'expectation.issue_codes' must be a list of strings")
    if parse_error is not None:
        if not isinstance(parse_error, str) or not parse_error.strip():
            raise WildExpectationError(
                f"{where}: 'expectation.parse_error' must be a non-empty str"
            )
        if codes:
            raise WildExpectationError(
                f"{where}: a refused file produces no ParseIssues — declare 'parse_error' or "
                "'issue_codes', not both"
            )
        # A refused file yields no structure, so there is nothing to weigh against its declared
        # formula. The skip follows from the refusal and is not something a manifest restates —
        # asking for it again would invite the two declarations to contradict each other.
        if "stoichiometry" in raw:
            raise WildExpectationError(
                f"{where}: a refused file has no structure to check, so 'stoichiometry' must be "
                "omitted — the refusal already implies it"
            )
        if "parse_recover" in raw:
            raise WildExpectationError(
                f"{where}: a refused file must be refused on a bare parse, so 'parse_recover' "
                "must be omitted — a declared preset would parse it successfully and contradict "
                "the refusal"
            )
        roundtrip = raw.get("roundtrip")
        if roundtrip not in (None, "skipped"):
            raise WildExpectationError(
                f"{where}: a refused file produces no object to round-trip, so 'roundtrip' "
                "must be omitted or 'skipped' — not {roundtrip!r}"
            )
        note = str(raw.get("roundtrip_note", "")).strip()
        if roundtrip == "skipped" and not note:
            raise WildExpectationError(
                f"{where}: 'roundtrip_note' is required when the round-trip is skipped — the "
                "refusal is the reason, stated in prose"
            )
        return WildExpectation(
            issue_codes=(),
            parse_error=parse_error,
            stoichiometry="refused",
            stoichiometry_note="the file is refused; no structure is produced",
            frame_count=0,
            pair=None,
            parse_recover=(),
            roundtrip="refused",
            roundtrip_note=(
                note or "the file is refused; no object is produced to re-export and re-parse"
            ),
            roundtrip_recover=(),
        )

    if format_id in STOICH_FORMATS:
        stoichiometry = raw.get("stoichiometry", "checked")
        if stoichiometry != "checked" and stoichiometry not in SKIP_REASONS:
            raise WildExpectationError(
                f"{where}: 'expectation.stoichiometry' must be 'checked' or one of "
                f"{SKIP_REASONS}, got {stoichiometry!r}"
            )
        note = str(raw.get("stoichiometry_note", "")).strip()
        if stoichiometry != "checked" and not note:
            # A skipped oracle with no stated reason is indistinguishable from a skipped oracle
            # that hides a bug, so the reason is mandatory rather than encouraged.
            raise WildExpectationError(
                f"{where}: 'expectation.stoichiometry_note' is required when the stoichiometry "
                "check is skipped — a skipped check must be a recorded judgement"
            )
    else:
        # The file's-own-chemistry oracle is CIF-only: VASP output carries no composition tag,
        # so the check is structurally absent — not a skip reason (which justifies a check that
        # could have run but was declined). Declaring one here would be a category error.
        if "stoichiometry" in raw or "stoichiometry_note" in raw:
            raise WildExpectationError(
                f"{where}: 'stoichiometry' does not apply to format_id {format_id!r} — the "
                "oracle is CIF-only; a VASP case is checked by the pair-agreement oracle instead"
            )
        stoichiometry = STOICH_NOT_APPLICABLE
        note = (
            "the file's-own-chemistry oracle is CIF-only; VASP output has no self-declared "
            "composition (the pair-agreement oracle applies instead)"
        )

    pair = raw.get("pair")
    if pair is not None and (not isinstance(pair, str) or not pair.strip()):
        raise WildExpectationError(f"{where}: 'expectation.pair' must be a non-empty case name")

    # The parse-time recovery presets (M49-S1): how this file parses at all, if it does not
    # self-describe. Only the LAMMPS formats have parse-time scenarios in this corpus.
    parse_recover = _recovery_specs(raw.get("parse_recover"), where=where, field="parse_recover")
    if parse_recover and format_id not in ROUNDTRIP_FORMATS:
        raise WildExpectationError(
            f"{where}: 'parse_recover' applies only to the LAMMPS formats "
            f"{sorted(ROUNDTRIP_FORMATS)} — no other wild format has a parse-time recovery"
        )

    # The round-trip self-consistency oracle (M49-S1, D184): format-gated to the two full
    # read+write LAMMPS formats, exactly like stoichiometry is CIF-only and pair VASP-only.
    # A LAMMPS manifest must declare it; a non-LAMMPS manifest must not (structurally absent,
    # not a skip — the same discipline as stoichiometry on a VASP file).
    if format_id in ROUNDTRIP_FORMATS:
        roundtrip = raw.get("roundtrip", "checked")
        if roundtrip not in ("checked", "skipped"):
            raise WildExpectationError(
                f"{where}: 'expectation.roundtrip' must be 'checked' or 'skipped', got "
                f"{roundtrip!r}"
            )
        r_note = str(raw.get("roundtrip_note", "")).strip()
        if roundtrip == "skipped" and not r_note:
            raise WildExpectationError(
                f"{where}: 'expectation.roundtrip_note' is required when the round-trip is "
                "skipped — a skipped oracle must be a recorded judgement"
            )
        roundtrip_recover = _recovery_specs(
            raw.get("roundtrip_recover"), where=where, field="roundtrip_recover"
        )
        if roundtrip_recover and roundtrip != "checked":
            raise WildExpectationError(
                f"{where}: 'roundtrip_recover' names a preset for the re-parse, so it only "
                "makes sense with 'roundtrip: checked'"
            )
    else:
        for field in ("roundtrip", "roundtrip_note", "roundtrip_recover"):
            if field in raw:
                raise WildExpectationError(
                    f"{where}: '{field}' does not apply to format_id {format_id!r} — the "
                    "round-trip oracle is LAMMPS-only (the two full read+write formats); a "
                    "non-LAMMPS case is checked by its own oracle instead"
                )
        roundtrip = ROUNDTRIP_NOT_APPLICABLE
        r_note = (
            "the round-trip self-consistency oracle applies only to the full read+write "
            "LAMMPS formats; this format has no exporter round-trip in the wild corpus"
        )
        roundtrip_recover = ()

    frame_count = raw.get("frame_count", 1)
    if not isinstance(frame_count, int) or frame_count < 1:
        raise WildExpectationError(f"{where}: 'expectation.frame_count' must be a positive int")

    return WildExpectation(
        issue_codes=tuple(sorted(codes)),
        parse_error=parse_error,
        stoichiometry=stoichiometry,
        stoichiometry_note=note,
        frame_count=frame_count,
        pair=pair,
        parse_recover=parse_recover,
        roundtrip=roundtrip,
        roundtrip_note=r_note,
        roundtrip_recover=roundtrip_recover,
    )


def _recovery_specs(raw: Any, *, where: str, field: str) -> tuple[str, ...]:
    """Normalize a manifest recovery-preset declaration to a tuple of spec strings.

    Accepts a single ``"SCENARIO=CHOICE[,param=value…]"`` string or a list of them (the CLI
    ``--recover`` grammar). Empty when the field is absent. The grammar itself is validated by
    :func:`parse_recovery_specs`, so a malformed preset fails the manifest, not the suite.
    """
    if raw is None:
        return ()
    specs = [raw] if isinstance(raw, str) else raw
    if not isinstance(specs, list) or not all(isinstance(s, str) and s.strip() for s in specs):
        raise WildExpectationError(
            f"{where}: '{field}' must be a preset string or a list of preset strings "
            "(SCENARIO=CHOICE[,param=value…])"
        )
    return tuple(spec.strip() for spec in specs)


def parse_recovery_specs(specs: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Parse CLI-style recovery preset strings into the ``{scenario: {choice, parameters}}`` map
    the parse-time recovery hooks consume — the same grammar as the CLI's ``--recover``
    (``SCENARIO=CHOICE[,param=value…]``), so a manifest preset reads exactly like the command
    line that reproduces it. Validates the scenario name against the known parse-time set and
    rejects a duplicate scenario (a file needs each fact resolved once)."""
    choices: dict[str, dict[str, Any]] = {}
    for spec in specs:
        scenario, sep, rest = spec.partition("=")
        if not scenario or not sep or not rest:
            raise WildExpectationError(
                f"recovery preset {spec!r} must be SCENARIO=CHOICE[,param=value…]"
            )
        scenario = scenario.strip()
        if scenario not in _PARSE_TIME_SCENARIOS:
            raise WildExpectationError(
                f"recovery preset {spec!r} names unknown parse-time scenario {scenario!r}; "
                f"the LAMMPS parse-time scenarios are {sorted(_PARSE_TIME_SCENARIOS)}"
            )
        if scenario in choices:
            raise WildExpectationError(
                f"recovery preset {spec!r} names {scenario!r} twice; a file needs each parse-time "
                "fact resolved once"
            )
        parts = rest.split(",")
        choice = parts[0].strip()
        if not choice:
            raise WildExpectationError(f"recovery preset {spec!r} names an empty choice")
        params: dict[str, Any] = {}
        for param in parts[1:]:
            name, eq, value = param.partition("=")
            if not eq or not name.strip():
                raise WildExpectationError(
                    f"recovery preset {spec!r}: parameter {param!r} must be name=value"
                )
            params[name.strip()] = _coerce_preset_value(value)
        choices[scenario] = {"choice": choice, "parameters": params}
    return choices


def _coerce_preset_value(value: str) -> Any:
    """Coerce a preset parameter value to int, then float, else leave it a string — the CLI's
    ``--recover`` coercion, so ``species=1:Si 2:O`` stays a string while a numeric parameter
    reads as a number."""
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def validate_findings(case: gov.GoldenCase) -> list[str]:
    """The optional ``findings`` list: what this real file taught the project.

    M20's rule is that every real-file surprise becomes a fix *or* a named issue with a tracked
    reason. ``issue_codes`` records the machine half — which codes fire — but a code alone does
    not say whether the behaviour behind it is *correct*. A declared code can equally mean "this
    limitation is honestly reported" or "this warning is wrong and we haven't fixed it yet", and
    conflating the two would let the corpus quietly ratify a bug the moment someone wrote its
    code into a manifest.

    So a case that revealed a defect says so here, in prose, next to the file that revealed it.
    The list is the corpus's own triage record: it travels with the fixture, survives the commit
    message that would otherwise be its only home, and is what a reader consults when a declared
    issue code looks surprising.
    """
    raw = case.data.get("findings", [])
    where = case.rel_manifest
    if not isinstance(raw, list) or not all(isinstance(f, str) and f.strip() for f in raw):
        raise WildExpectationError(f"{where}: 'findings' must be a list of non-empty strings")
    return list(raw)


def parse_formula(formula: str) -> dict[str, float]:
    """``"Cl4 Na4"`` → ``{"Cl": 4.0, "Na": 4.0}``. An elided count means 1, as in CIF and in
    chemistry generally (``"H2 O"`` is two hydrogens and one oxygen)."""

    counts: dict[str, float] = {}
    for symbol, count in _FORMULA_TERM.findall(formula):
        if not symbol:
            continue
        counts[symbol] = counts.get(symbol, 0.0) + (float(count) if count else 1.0)
    return counts


def declared_cell_composition(source_text: str) -> dict[str, float] | tuple[None, str]:
    """The unit cell's composition according to the file itself: formula sum × Z.

    Reads the *source text*, deliberately not the parsed document — the oracle must not be
    contaminated by the code under test. Both tags are simple ``_tag value`` pairs in every
    real CIF, so a small regex over the text is the right amount of machinery here; using the
    parser's own tokenizer would make a lexer bug invisible to the check it is meant to police.

    Returns the per-element counts, or ``(None, reason)`` naming which tag was missing so the
    manifest can declare the matching skip.
    """

    formula = _find_pair_value(source_text, _FORMULA_TAG)
    if formula is None:
        return None, "formula_absent"
    z_raw = _find_pair_value(source_text, _Z_TAG)
    if z_raw is None:
        return None, "z_absent"
    try:
        z = float(z_raw)
    except ValueError:
        return None, "z_absent"

    per_formula_unit = parse_formula(formula)
    if not per_formula_unit:
        return None, "formula_absent"
    return {symbol: count * z for symbol, count in per_formula_unit.items()}


def _find_pair_value(text: str, tag: str) -> str | None:
    """The value of a ``_tag value`` pair in raw CIF text, or ``None``.

    Tag matching is case-insensitive (CIF tags are), the bare absence markers ``?`` and ``.``
    read as absent, and single/double quotes are stripped — a formula sum is nearly always
    quoted, since it contains spaces.
    """
    pattern = re.compile(
        rf"^\s*{re.escape(tag)}\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    value = next(g for g in match.groups() if g is not None)
    return None if value in ("?", ".") else value


def composition_of(symbols: list[str]) -> dict[str, float]:
    """The parsed structure's composition, as element → count."""
    return {symbol: float(count) for symbol, count in Counter(symbols).items()}


def compositions_agree(
    declared: dict[str, float], produced: dict[str, float], *, tolerance: float = 1e-6
) -> bool:
    """Whether the file's declared cell composition and the expansion's actual one match.

    Exact on element identity — a missing or extra element is never a rounding artefact — and
    tolerant only on the counts, where CIF's own fractional formulas (``Ca0.5``) make float
    comparison unavoidable.
    """
    if set(declared) != set(produced):
        return False
    return all(math.isclose(declared[s], produced[s], abs_tol=tolerance) for s in declared)


def wild_cases() -> list[gov.GoldenCase]:
    """Every real-world case, sorted by manifest path."""
    return gov.discover_cases(WILD_ROOT)


def source_text_of(case: gov.GoldenCase) -> str:
    return case.source_path.read_text(encoding="utf-8", errors="replace")


def manifest_data(case: gov.GoldenCase) -> dict[str, Any]:
    return case.data
