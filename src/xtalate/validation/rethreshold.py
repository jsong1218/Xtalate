"""Re-thresholding: re-evaluate a stored Validation Report under a new tolerance profile.

The lighter of the two re-validation operations (MASTER_SPEC Part 5 §4.5 point 1). *A tolerance
profile changes only the pass/fail thresholds applied to already-measured quantities; it never
changes the measurements themselves.* So re-thresholding needs **only the stored report** — no
source file, no output bytes, no re-parse — which is why it stays available after the file bytes
expire. It recomputes each continuous check's status from its stored ``measured`` value against the
new profile; discrete checks (counts, species, ``pbc``, presence, absence, report-consistency) are
exact and profile-independent, so their stored status is carried through unchanged.

This is a pure function over the report; it lives beside the engine but imports none of its
re-parse machinery.
"""

from __future__ import annotations

import uuid

from xtalate._time import utc_now
from xtalate.validation._shared import AGGREGATE as _AGGREGATE
from xtalate.validation._shared import NUMERIC_QUANTITY as _NUMERIC_QUANTITY
from xtalate.validation._shared import RANK as _RANK
from xtalate.validation.report import CheckResult, ValidationReport
from xtalate.validation.tolerance import ToleranceProfile

# Continuous checks and the (quantity, measured-value key) their status is derived from. Any check
# not named here is discrete/exact and keeps its stored status verbatim.
_CONTINUOUS = {
    "positions_rmsd": ("positions", "rmsd_ang"),
    "lattice_consistency": ("lattice", "max_element_diff_ang"),
}


def rethreshold(report: ValidationReport, profile: ToleranceProfile) -> ValidationReport:
    """A new :class:`ValidationReport` re-judging ``report``'s measurements under ``profile``.

    Measurements are copied verbatim; only ``status``/``tolerance_applied`` (and the aggregate)
    change. A re-parse warning in the original still floors the aggregate at
    ``passed_with_warnings`` (an output that parsed only with warnings is a finding regardless of
    tolerance)."""
    checks = [_rejudge(c, profile) for c in report.checks]
    worst = max((_RANK[c.status] for c in checks), default=0)
    if report.reparse_issues and worst == 0:
        worst = 1
    return ValidationReport(
        report_id=str(uuid.uuid4()),
        conversion_report_id=report.conversion_report_id,
        created_at=utc_now(),
        status=_AGGREGATE[worst],
        checks=checks,
        tolerance_profile=profile.as_dict(),  # type: ignore[arg-type]
        reparse_issues=report.reparse_issues,
        schema_version=report.schema_version,
    )


def _rejudge(check: CheckResult, profile: ToleranceProfile) -> CheckResult:
    if check.status == "skipped":
        return check.model_copy()
    if check.check_id in _CONTINUOUS:
        return _rejudge_scalar(check, profile)
    if check.check_id == "numeric_field_fidelity":
        return _rejudge_numeric(check, profile)
    return check.model_copy()  # discrete / exact — profile-independent.


def _bound(check: CheckResult) -> float:
    ta = check.tolerance_applied or {}
    raw = ta.get("representational_bound_ang", 0.0)
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _rejudge_scalar(check: CheckResult, profile: ToleranceProfile) -> CheckResult:
    quantity, key = _CONTINUOUS[check.check_id]
    bound = _bound(check)
    eff = profile.effective(quantity, bound)
    measured = float(_as_number(check.measured.get(key)))
    status = "fail" if measured > eff.fail else "warn" if measured > eff.warn else "pass"
    # A discrete sub-condition (pbc equality) can force fail regardless of the numeric tolerance.
    if check.check_id == "lattice_consistency" and check.measured.get(
        "pbc_expected"
    ) != check.measured.get("pbc_found"):
        status = "fail"
    ta = dict(check.tolerance_applied or {})
    ta["warn_ang"] = eff.warn
    ta["fail_ang"] = eff.fail
    return check.model_copy(update={"status": status, "tolerance_applied": ta})


def _rejudge_numeric(check: CheckResult, profile: ToleranceProfile) -> CheckResult:
    worst = "pass"
    new_measured: dict[str, object] = {}
    for path, sub in check.measured.items():
        quantity = _NUMERIC_QUANTITY.get(path)
        if not isinstance(sub, dict) or quantity is None:
            new_measured[path] = sub
            continue
        # The stored per-path bound, for the same reason `_rejudge_scalar` reads its own: the
        # representational floor is a property of the *format's* declared precision, not of the
        # profile, so re-thresholding must re-apply it rather than drop it. Omitting it silently
        # tightened `numeric_field_fidelity` on re-threshold — inert only while every exporter
        # declares full precision, and a real mis-judgement the moment one does not.
        eff = profile.effective(quantity, _as_number(sub.get("representational_bound")))
        diff = float(_as_number(sub.get("max_abs_diff")))
        missing = bool(sub.get("missing"))
        status = "fail" if (missing or diff > eff.fail) else "warn" if diff > eff.warn else "pass"
        new_measured[path] = {**sub, "warn": eff.warn, "fail": eff.fail}
        if _RANK[status] > _RANK[worst]:
            worst = status
    return check.model_copy(update={"status": worst, "measured": new_measured})


def _as_number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
