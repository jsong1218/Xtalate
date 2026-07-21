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
"""

from __future__ import annotations

import math
import re
from collections import Counter
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


def load_expectation(case: gov.GoldenCase) -> WildExpectation:
    """Parse and validate the ``expectation`` block of a wild manifest."""

    raw = case.data.get("expectation")
    where = case.rel_manifest
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
        return WildExpectation(
            issue_codes=(),
            parse_error=parse_error,
            stoichiometry="refused",
            stoichiometry_note="the file is refused; no structure is produced",
            frame_count=0,
        )

    stoichiometry = raw.get("stoichiometry", "checked")
    if stoichiometry != "checked" and stoichiometry not in SKIP_REASONS:
        raise WildExpectationError(
            f"{where}: 'expectation.stoichiometry' must be 'checked' or one of {SKIP_REASONS}, "
            f"got {stoichiometry!r}"
        )
    note = str(raw.get("stoichiometry_note", "")).strip()
    if stoichiometry != "checked" and not note:
        # A skipped oracle with no stated reason is indistinguishable from a skipped oracle
        # that hides a bug, so the reason is mandatory rather than encouraged.
        raise WildExpectationError(
            f"{where}: 'expectation.stoichiometry_note' is required when the stoichiometry "
            "check is skipped — a skipped check must be a recorded judgement"
        )

    frame_count = raw.get("frame_count", 1)
    if not isinstance(frame_count, int) or frame_count < 1:
        raise WildExpectationError(f"{where}: 'expectation.frame_count' must be a positive int")

    return WildExpectation(
        issue_codes=tuple(sorted(codes)),
        parse_error=parse_error,
        stoichiometry=stoichiometry,
        stoichiometry_note=note,
        frame_count=frame_count,
    )


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
