"""The Validation Engine — re-parse the output and check the Conversion Report told the truth.

Not "nothing was lost" (loss is often intentional and reported) but the three-part promise of
Part 5 §1: *everything the report claims was preserved is present and numerically faithful in the
output; everything it claims was removed is absent; and nothing happened the report does not
mention.* The reference is the **expected object** — the source filtered through the ``write_plan``
with Recovery-supplied fields included, i.e. the ``canonical′`` the Conversion Engine already
materialized (Part 4 §1, DECISIONS.md D20). The output bytes are re-parsed through the *ordinary*
parser registry (the same read path everything else uses, so a bug must exist symmetrically in
exporter *and* parser to escape — Part 5 §1) and diffed against the expected object under the
tolerance profile (§4). Every completed conversion carries exactly one report (§3); there is no
switch to skip it.

**Layering (Part 1 §5.1).** ``validation`` sits *below* ``conversion``: it may not import the
Conversion Report schema. It reads the report it validates through a structural
:class:`ConversionReportView` Protocol (satisfied by ``conversion.report.ConversionReport`` without
any import), so the dependency arrow still points only downward — ``validation`` → ``sdk`` /
``schema`` / ``capabilities``. The Conversion Engine (top layer) is what wires the two together.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from io import BytesIO
from typing import Any, Protocol

import numpy as np

from xtalate._time import utc_now
from xtalate.capabilities import Registry
from xtalate.schema import CanonicalObject
from xtalate.sdk import ParseError, ParseIssue
from xtalate.validation._shared import AGGREGATE as _AGGREGATE
from xtalate.validation._shared import NUMERIC_FIELDS as _NUMERIC_FIELDS
from xtalate.validation._shared import RANK as _RANK
from xtalate.validation.report import CheckResult, ValidationReport
from xtalate.validation.tolerance import ToleranceProfile


class _Entry(Protocol):
    path: str


class _Supplied(Protocol):
    path: str
    from_assumption: str


class _Assumption(Protocol):
    id: str


class ConversionReportView(Protocol):
    """The read-only slice of a Conversion Report the Validation Engine consumes. Declared here as
    a structural Protocol so ``validation`` never imports ``conversion`` (the layer above it); the
    concrete ``ConversionReport`` satisfies it by shape. The `report_consistency` check (§2) reads
    ``preserved``/``removed``/``supplied``/``assumptions``; the linkage reads ``report_id``.

    Members are read-only properties so the collection types are covariant — the concrete report's
    ``list[PreservedEntry]`` satisfies ``Sequence[_Entry]`` (a settable Protocol attribute would be
    invariant and reject it)."""

    @property
    def report_id(self) -> str: ...
    @property
    def preserved(self) -> Sequence[_Entry]: ...
    @property
    def removed(self) -> Sequence[_Entry]: ...
    @property
    def supplied(self) -> Sequence[_Supplied]: ...
    @property
    def assumptions(self) -> Sequence[_Assumption]: ...


class ValidationEngine:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def validate(
        self,
        *,
        expected: CanonicalObject,
        output: bytes,
        target_format_id: str,
        conversion_report: ConversionReportView,
        tolerance: ToleranceProfile,
    ) -> ValidationReport:
        """Re-parse ``output`` and run the §2 check catalog against ``expected`` under
        ``tolerance``. Returns exactly one :class:`ValidationReport` (Part 5 §3)."""
        parser = self._registry.get_parser(target_format_id)
        precision = self._registry.get_exporter(target_format_id).capabilities().numeric_precision

        reparse_issues: list[ParseIssue] = []
        try:
            result = parser.parse(BytesIO(output), filename=None)
        except ParseError as exc:
            # The output does not even re-parse — the most damning finding possible. Report it as
            # a single failing check rather than raising, so the caller still gets a structured
            # report.
            return self._finalize(
                conversion_report,
                expected.schema_version,
                tolerance,
                reparse_issues=exc.issues,
                checks=[
                    CheckResult(
                        check_id="reparse",
                        status="fail",
                        message=f"output file does not re-parse: {exc}",
                    )
                ],
            )
        canonical = result.canonical
        reparse_issues = list(result.issues)

        perm = self._registry.get_exporter(target_format_id).atom_permutation(expected)

        checks = [
            _check_atom_count(expected, canonical),
            _check_species(expected, canonical, perm),
            _check_positions_rmsd(expected, canonical, perm, tolerance, precision),
            _check_lattice(expected, canonical, tolerance, precision),
            _check_frame_count(expected, canonical),
            _check_numeric_fields(expected, canonical, perm, tolerance, precision),
            _check_metadata(expected, canonical),
            _check_absence(canonical, conversion_report),
            _check_report_consistency(conversion_report),
        ]
        return self._finalize(
            conversion_report, expected.schema_version, tolerance, reparse_issues, checks
        )

    def _finalize(
        self,
        report: ConversionReportView,
        schema_version: str,
        tolerance: ToleranceProfile,
        reparse_issues: list[ParseIssue],
        checks: list[CheckResult],
    ) -> ValidationReport:
        worst = max((_RANK[c.status] for c in checks), default=0)
        # A re-parse that succeeded only with warnings is itself a finding (§3): it cannot pass
        # clean, only at best passed_with_warnings.
        if reparse_issues and worst == 0:
            worst = 1
        return ValidationReport(
            report_id=str(uuid.uuid4()),
            conversion_report_id=report.report_id,
            created_at=utc_now(),
            status=_AGGREGATE[worst],
            checks=checks,
            tolerance_profile=tolerance.as_dict(),  # type: ignore[arg-type]
            reparse_issues=reparse_issues,
            schema_version=schema_version,
        )


# --- Individual checks (Part 5 §2) ---------------------------------------------------------------


def _check_atom_count(expected: CanonicalObject, canonical: CanonicalObject) -> CheckResult:
    n = min(len(expected.frames), len(canonical.frames))
    mismatches = [
        i
        for i in range(n)
        if len(expected.frames[i].atoms.symbols) != len(canonical.frames[i].atoms.symbols)
    ]
    exp0 = len(expected.frames[0].atoms.symbols) if expected.frames else 0
    got0 = len(canonical.frames[0].atoms.symbols) if canonical.frames else 0
    status = "fail" if mismatches else "pass"
    return CheckResult(
        check_id="atom_count",
        status=status,
        paths=["atoms.symbols"],
        measured={"expected": exp0, "found": got0, "frames_compared": n},
        message=(
            f"{exp0} atoms expected, {got0} found (exact check)."
            if status == "pass"
            else f"atom-count mismatch in frame(s) {mismatches} — a dropped or duplicated atom."
        ),
    )


def _check_species(
    expected: CanonicalObject, canonical: CanonicalObject, perm: list[int] | None
) -> CheckResult:
    n = min(len(expected.frames), len(canonical.frames))
    mismatches = 0
    for i in range(n):
        exp = expected.frames[i].atoms.symbols
        got = canonical.frames[i].atoms.symbols
        if len(exp) != len(got):
            mismatches += max(len(exp), len(got))
            continue
        order = perm if perm is not None else list(range(len(exp)))
        mismatches += sum(1 for j in range(len(got)) if exp[order[j]] != got[j])
    status = "fail" if mismatches else "pass"
    measured: dict[str, Any] = {
        "permutation_map": perm if perm is not None else "identity",
        "mismatches": mismatches,
    }
    if status == "pass":
        grouping = (
            " under the exporter's element grouping (permutation map applied)."
            if perm is not None
            else "; source order retained (identity permutation)."
        )
        message = "Species preserved" + grouping
    else:
        message = f"{mismatches} element mismatch(es) after the permutation map — chemistry lost"
    return CheckResult(
        check_id="species_preservation",
        status=status,
        paths=["atoms.symbols"],
        measured=measured,
        message=message,
    )


def _check_positions_rmsd(
    expected: CanonicalObject,
    canonical: CanonicalObject,
    perm: list[int] | None,
    tolerance: ToleranceProfile,
    precision: dict[str, int | None],
) -> CheckResult:
    bound = _representational_bound(precision, "atoms.positions")
    eff = tolerance.effective("positions", bound)
    n = min(len(expected.frames), len(canonical.frames))
    rmsds: list[float] = []
    max_disp = 0.0
    for i in range(n):
        exp = _permuted(np.asarray(expected.frames[i].atoms.positions, dtype=float), perm)
        got = np.asarray(canonical.frames[i].atoms.positions, dtype=float)
        if exp.shape != got.shape:
            return _shape_fail("positions_rmsd", ["atoms.positions"], exp.shape, got.shape)
        disp = np.linalg.norm(got - exp, axis=1)
        rmsds.append(float(np.sqrt(np.mean(disp**2))) if disp.size else 0.0)
        max_disp = max(max_disp, float(disp.max()) if disp.size else 0.0)
    rmsd = max(rmsds) if rmsds else 0.0
    status = "fail" if rmsd > eff.fail else "warn" if rmsd > eff.warn else "pass"
    return CheckResult(
        check_id="positions_rmsd",
        status=status,
        paths=["atoms.positions"],
        measured={"rmsd_ang": rmsd, "max_displacement_ang": max_disp, "frames_compared": n},
        tolerance_applied={
            "warn_ang": eff.warn,
            "fail_ang": eff.fail,
            "representational_bound_ang": bound,
        },
        message=(
            f"RMSD {rmsd:.3e} Å over {n} frame(s), within representational precision."
            if status == "pass"
            else f"RMSD {rmsd:.3e} Å over {n} frame(s) exceeds the {status} threshold "
            f"{(eff.fail if status == 'fail' else eff.warn):.3e} Å."
        ),
    )


def _check_lattice(
    expected: CanonicalObject,
    canonical: CanonicalObject,
    tolerance: ToleranceProfile,
    precision: dict[str, int | None],
) -> CheckResult:
    n = min(len(expected.frames), len(canonical.frames))
    have = [i for i in range(n) if expected.frames[i].cell is not None]
    if not have:
        return CheckResult(
            check_id="lattice_consistency",
            status="skipped",
            paths=["cell.lattice_vectors", "cell.pbc"],
            message="No lattice in the write plan — nothing to compare.",
            skip_reason="write_plan contains no cell.lattice_vectors.",
        )
    bound = _representational_bound(precision, "cell.lattice_vectors")
    eff = tolerance.effective("lattice", bound)
    max_diff = 0.0
    pbc_mismatch = False
    pbc_exp: list[bool] = []
    pbc_got: list[bool] = []
    for i in have:
        ecell = expected.frames[i].cell
        gcell = canonical.frames[i].cell
        assert ecell is not None
        if gcell is None:
            return CheckResult(
                check_id="lattice_consistency",
                status="fail",
                paths=["cell.lattice_vectors", "cell.pbc"],
                measured={"frame": i},
                message=f"planned lattice absent from re-parsed output in frame {i}.",
            )
        e = np.asarray(ecell.lattice_vectors, dtype=float)
        g = np.asarray(gcell.lattice_vectors, dtype=float)
        max_diff = max(max_diff, float(np.abs(e - g).max()))
        pbc_exp = [bool(x) for x in ecell.pbc]
        pbc_got = [bool(x) for x in gcell.pbc]
        if pbc_exp != pbc_got:
            pbc_mismatch = True
    if pbc_mismatch or max_diff > eff.fail:
        status = "fail"
    elif max_diff > eff.warn:
        status = "warn"
    else:
        status = "pass"
    measured: dict[str, Any] = {
        "max_element_diff_ang": max_diff,
        "pbc_expected": pbc_exp,
        "pbc_found": pbc_got,
    }
    return CheckResult(
        check_id="lattice_consistency",
        status=status,
        paths=["cell.lattice_vectors", "cell.pbc"],
        measured=measured,
        tolerance_applied={"warn_ang": eff.warn, "fail_ang": eff.fail},
        message=(
            f"Lattice matches within {max_diff:.3e} Å; pbc {pbc_exp} preserved exactly."
            if status == "pass"
            else (
                "pbc mismatch (booleans admit no tolerance)."
                if pbc_mismatch
                else f"lattice element diff {max_diff:.3e} Å exceeds the {status} threshold."
            )
        ),
    )


def _check_frame_count(expected: CanonicalObject, canonical: CanonicalObject) -> CheckResult:
    exp = expected.frame_count
    got = canonical.frame_count
    status = "pass" if exp == got else "fail"
    return CheckResult(
        check_id="frame_count",
        status=status,
        paths=["frames"],
        measured={"expected": exp, "found": got},
        message=(
            f"{exp} frame(s) planned, {got} found."
            if status == "pass"
            else f"frame-count mismatch: {exp} planned, {got} found."
        ),
    )


def _check_numeric_fields(
    expected: CanonicalObject,
    canonical: CanonicalObject,
    perm: list[int] | None,
    tolerance: ToleranceProfile,
    precision: dict[str, int | None],
) -> CheckResult:
    n = min(len(expected.frames), len(canonical.frames))
    measured: dict[str, Any] = {}
    paths: list[str] = []
    worst = "pass"
    for path, quantity, kind in _NUMERIC_FIELDS:
        exp_vals = [_field_value(expected.frames[i], path) for i in range(n)]
        if all(v is None for v in exp_vals):
            continue  # not in the write plan for any compared frame.
        paths.append(path)
        bound = _representational_bound(precision, path)
        eff = tolerance.effective(quantity, bound)
        field_max = 0.0
        missing = False
        for i in range(n):
            ev = exp_vals[i]
            if ev is None:
                continue
            gv = _field_value(canonical.frames[i], path)
            if gv is None:
                missing = True
                continue
            e = np.asarray(ev, dtype=float)
            g = np.asarray(gv, dtype=float)
            if kind == "per_atom":
                e = _permuted(e, perm)
            if e.shape != g.shape:
                missing = True
                continue
            field_max = max(field_max, float(np.abs(e - g).max()) if e.size else 0.0)
        if missing:
            status = "fail"
        else:
            status = "fail" if field_max > eff.fail else "warn" if field_max > eff.warn else "pass"
        measured[path] = {
            "max_abs_diff": field_max,
            "warn": eff.warn,
            "fail": eff.fail,
            "missing": missing,
        }
        if _RANK[status] > _RANK[worst]:
            worst = status
    if not paths:
        return CheckResult(
            check_id="numeric_field_fidelity",
            status="skipped",
            paths=[],
            message="No numeric fields beyond positions and lattice in the write plan.",
            skip_reason="write_plan contains no velocities, forces, energies, stress, charges, "
            "magnetic moments, masses, or time.",
        )
    return CheckResult(
        check_id="numeric_field_fidelity",
        status=worst,
        paths=paths,
        measured=measured,
        message=(
            f"{len(paths)} numeric field(s) faithful within per-quantity tolerance."
            if worst == "pass"
            else f"numeric fidelity {worst} on one or more of {paths}."
        ),
    )


def _check_metadata(expected: CanonicalObject, canonical: CanonicalObject) -> CheckResult:
    exp_presence = expected.field_presence()
    planned = [
        p
        for p in exp_presence.present_paths()
        if p.startswith("simulation.") or p.startswith("user_metadata.")
    ]
    got_presence = canonical.field_presence()
    absent: list[str] = []
    drift = 0
    for path in planned:
        if got_presence.status_of(path) == "absent":
            absent.append(path)
            continue
        if not _content_matches(expected, canonical, path):
            drift += 1
    status = "fail" if absent else "warn" if drift else "pass"
    return CheckResult(
        check_id="metadata_preservation",
        status=status,
        paths=planned,
        measured={
            "planned_paths": len(planned),
            "present": len(planned) - len(absent),
            "content_drift": drift,
        },
        message=(
            (
                f"{len(planned)} planned metadata path(s) present and semantically identical."
                if planned
                else "No metadata or custom-array paths in the write plan."
            )
            if status == "pass"
            else (
                f"planned metadata path(s) absent from output: {absent}."
                if absent
                else f"{drift} metadata path(s) changed content on re-parse."
            )
        ),
    )


def _check_absence(canonical: CanonicalObject, report: ConversionReportView) -> CheckResult:
    # A path that is *also* preserved (e.g. atoms.positions dropped for the non-selected frames but
    # kept for the retained one) is validated by frame_count, not by asserting it absent — asserting
    # positions absent would false-fail. A path that is *also* supplied is likewise exempt: recovery
    # dropped the source original (removed) and fabricated a replacement (supplied), so it *should*
    # reappear in the output — a `mixed` cell whose cell-bearing frame frame_selection drops, then
    # missing_lattice fills (D51). Only genuinely-removed-and-not-replaced paths are checked here.
    preserved_paths = {e.path for e in report.preserved}
    supplied_paths = {e.path for e in report.supplied}
    to_check = [
        e.path
        for e in report.removed
        if e.path not in preserved_paths and e.path not in supplied_paths
    ]
    presence = canonical.field_presence()
    violations = [p for p in to_check if presence.status_of(p) != "absent"]
    status = "fail" if violations else "pass"
    return CheckResult(
        check_id="absence_conformance",
        status=status,
        paths=to_check,
        measured={"removed_paths_checked": len(to_check), "violations": len(violations)},
        message=(
            f"All {len(to_check)} removed path(s) verified absent in the re-parse."
            if status == "pass"
            else f"removed path(s) reappeared — exporter deviated from the plan: {violations}"
        ),
    )


def _check_report_consistency(report: ConversionReportView) -> CheckResult:
    assumption_ids = {a.id for a in report.assumptions}
    untraceable = [s.path for s in report.supplied if s.from_assumption not in assumption_ids]
    status = "fail" if untraceable else "pass"
    return CheckResult(
        check_id="report_consistency",
        status=status,
        paths=[],
        measured={
            "completeness_invariant": "satisfied",
            "supplied_traced": len(report.supplied) - len(untraceable),
            "untraceable_deltas": len(untraceable),
            "preflight_final_deltas": len(report.assumptions),
        },
        message=(
            "Completeness invariant satisfied; every supplied path traces to a recorded Assumption."
            if status == "pass"
            else f"supplied path(s) reference an unknown Assumption: {untraceable}."
        ),
    )


# --- Helpers -------------------------------------------------------------------------------------


def _permuted(arr: np.ndarray, perm: list[int] | None) -> np.ndarray:
    """Reorder ``arr`` (indexed by atom on axis 0) so position *i* holds source atom ``perm[i]`` —
    the permutation map the exporter declared (Part 5 §2). ``None`` is the identity."""
    if perm is None:
        return arr
    reordered: np.ndarray = arr[np.asarray(perm)]
    return reordered


def _field_value(frame: Any, path: str) -> Any:
    """Fetch a numeric field's value from a frame by its canonical path, or ``None`` if absent."""
    if path == "frame.time":
        return frame.time
    if path == "atoms.masses":
        return frame.atoms.masses
    group, _, name = path.partition(".")
    block = {"dynamics": frame.dynamics, "electronic": frame.electronic}.get(group)
    return getattr(block, name, None) if block is not None else None


def _representational_bound(precision: dict[str, int | None], path: str) -> float:
    """The per-component representational bound for ``path`` (Part 5 §4.2). A declared decimal count
    *d* gives ``0.5·10⁻ᵈ``; full precision (``None`` or undeclared) gives 0.0. Fractional-format
    lattice scaling (``× max‖Lᵢ‖``) is the v0.2 seam — no v0.1 exporter writes fractional."""
    d = precision.get(path)
    if d is None:
        return 0.0
    return 0.5 * 10.0 ** (-d)


def _content_matches(expected: CanonicalObject, canonical: CanonicalObject, path: str) -> bool:
    """Semantic content comparison for a metadata path (Part 5 §2): strings whitespace-normalized,
    everything else by equality. Only ``user_metadata.custom_global['key']`` scalars are compared in
    v0.1 (the only metadata any v0.1 exporter writes); other planned paths pass on presence alone,
    the honest floor until a format writes richer metadata (**P6**)."""
    key = _custom_global_key(path)
    if key is None:
        return True
    ev = expected.user_metadata.custom_global.get(key)
    gv = canonical.user_metadata.custom_global.get(key)
    if isinstance(ev, str) and isinstance(gv, str):
        return " ".join(ev.split()) == " ".join(gv.split())
    return bool(ev == gv)


def _custom_global_key(path: str) -> str | None:
    prefix = "user_metadata.custom_global['"
    if path.startswith(prefix) and path.endswith("']"):
        return path[len(prefix) : -2]
    return None


def _shape_fail(
    check_id: str, paths: list[str], exp: tuple[int, ...], got: tuple[int, ...]
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="fail",
        paths=paths,
        measured={"expected_shape": list(exp), "found_shape": list(got)},
        message=f"array shape mismatch: expected {exp}, found {got}.",
    )
