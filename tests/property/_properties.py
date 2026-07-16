"""The two report-completeness properties (MASTER_SPEC Part 8 §1.2; not a test module).

These are the single most important checks in the repository: mechanically enforcing **P1**
(no silent loss) and **P4** (no misfiled fabrication). The runtime completeness assertion in
``conversion.engine`` (v0.1-M4) checks every conversion that *happens*; the property harness
(``test_report_completeness``) drives conversions that have *not* happened yet and applies these
same invariants to each resulting report.

The logic is **re-derived here in test code**, deliberately *not* imported from
``conversion.engine._assert_completeness`` / ``validation.engine._check_absence``. A property that
merely called the production guard could never catch a bug in that guard, and the M10 done-means
requires the property to catch a deliberately broken finalizer *independently* of the runtime
assertion. Two implementations of one invariant is the point: if they ever disagree, one is wrong.
"""

from __future__ import annotations

from xtalate.conversion.report import ConversionReport
from xtalate.schema import CanonicalObject

# ``atoms.atomic_numbers`` is a *derived* mirror of ``atoms.symbols`` that no format stores on its
# own; the runtime invariant excludes it (``schema.paths.DERIVED_PATHS``), so the property must too,
# or every conversion would false-fail for "losing" a field that is only ever derived. This copy is
# **deliberately kept independent** of ``schema.paths.DERIVED_PATHS`` (not imported), per D50: an
# independent re-derivation of the invariant must not import the value it checks against — if the
# two ever disagree, that disagreement is the property doing its job.
_DERIVED_PATHS = frozenset({"atoms.atomic_numbers"})


def completeness_violations(
    source: CanonicalObject,
    report: ConversionReport,
    *,
    fabricated_at_parse: frozenset[str] = frozenset(),
) -> list[str]:
    """Property 1 — the completeness invariant (Part 4 §2), re-derived over an arbitrary report.

    Every source-``present``/``mixed`` path (bar the derived mirror and any path a parse-time
    recovery fabricated) must appear in ``preserved`` ∪ ``removed`` — a path in neither is silent
    loss (**P1**). Every ``supplied`` path must be absent on the source (fabricating over real data
    is silent fabrication, **P4**) and must trace to a recorded Assumption. Returns the list of
    violations, empty when the report is complete.

    ``fabricated_at_parse`` names paths a parse-time recovery invented (e.g. ``atoms.symbols`` via
    ``missing_species``): present in ``source`` (already recovered) but absent from the original
    file, so excluded from the silent-loss sweep and permitted in ``supplied``.
    """
    violations: list[str] = []
    presence = source.field_presence()
    accounted = {e.path for e in report.preserved} | {e.path for e in report.removed}

    for entry in presence.entries:
        if (
            entry.status in ("present", "mixed")
            and entry.path not in _DERIVED_PATHS
            and entry.path not in fabricated_at_parse
            and entry.path not in accounted
        ):
            violations.append(
                f"source-{entry.status} path {entry.path!r} is in neither preserved nor "
                "removed — silent loss (P1)"
            )

    # A supplied path present on the source is honest fabrication when that source value was itself
    # recorded `removed` (original dropped, replacement fabricated — a `mixed` cell whose cell-frame
    # frame_selection dropped, then re-supplied by missing_lattice). Excluding `removed` paths
    # leaves the P4 check catching only fabrication over *kept* source data.
    removed_paths = {e.path for e in report.removed}
    source_present = set(presence.present_paths()) - set(fabricated_at_parse) - removed_paths
    assumption_ids = {a.id for a in report.assumptions}
    for supplied in report.supplied:
        if supplied.path in source_present:
            violations.append(
                f"supplied path {supplied.path!r} was present on the source and not removed — "
                "silent fabrication over kept data (P4)"
            )
        if supplied.from_assumption not in assumption_ids:
            violations.append(
                f"supplied path {supplied.path!r} references unknown assumption "
                f"{supplied.from_assumption!r}"
            )
    return violations


def absence_violations(report: ConversionReport, reparsed: CanonicalObject) -> list[str]:
    """Property 2 — absence conformance (Part 8 §1.2), re-derived over the re-parsed output.

    Every ``removed`` path must actually be *absent* in the re-parse of the output file — a removed
    path that reappears means the exporter deviated from the plan (a silent write the report never
    promised). A path that is *also* ``preserved`` (e.g. ``atoms.positions`` dropped for the
    non-selected frames but kept for the retained one) is validated by frame count, not asserted
    absent. A path that is *also* ``supplied`` is likewise exempt: recovery dropped the source
    original and fabricated a replacement, so it is *expected* to reappear (a ``mixed`` cell whose
    cell-bearing frame ``frame_selection`` drops, then ``missing_lattice`` fills — D51). This
    re-derives ``validation.engine._check_absence``'s exemptions independently (D50), not by import.
    Returns the list of violations.
    """
    exempt = {e.path for e in report.preserved} | {e.path for e in report.supplied}
    to_check = [e.path for e in report.removed if e.path not in exempt]
    presence = reparsed.field_presence()
    return [
        f"removed path {path!r} reappeared in the re-parsed output — exporter deviated from "
        "the plan (P1)"
        for path in to_check
        if presence.status_of(path) != "absent"
    ]
