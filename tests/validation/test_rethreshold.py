"""Re-thresholding tests (M6, MASTER_SPEC Part 5 §4.5).

Re-thresholding re-judges a stored report's measurements under a new profile *without re-parsing*:
measurements are copied verbatim; only statuses and the aggregate change. These pin that a looser
profile can rescue a warn/fail and a stricter one can demote a pass, while discrete checks and the
raw measured values are untouched.
"""

from __future__ import annotations

from chembridge.validation import ToleranceProfile, rethreshold
from chembridge.validation.report import CheckResult, ValidationReport


def _report(rmsd: float) -> ValidationReport:
    return ValidationReport(
        report_id="v1",
        conversion_report_id="c1",
        created_at="2026-01-01T00:00:00Z",
        status="passed",
        checks=[
            CheckResult(
                check_id="atom_count",
                status="pass",
                measured={"expected": 3, "found": 3},
                message="exact",
            ),
            CheckResult(
                check_id="positions_rmsd",
                status="pass",
                measured={"rmsd_ang": rmsd},
                tolerance_applied={
                    "warn_ang": 1e-5,
                    "fail_ang": 1e-3,
                    "representational_bound_ang": 0.0,
                },
                message="ok",
            ),
        ],
        tolerance_profile={"name": "default"},
        schema_version="0.1.0",
    )


def _status(report: ValidationReport, check_id: str) -> str:
    return next(c.status for c in report.checks if c.check_id == check_id)


def test_measurements_are_preserved_only_status_changes() -> None:
    original = _report(rmsd=5e-4)  # between default warn (1e-5) and fail (1e-3) -> warn.
    out = rethreshold(original, ToleranceProfile.named("default"))
    assert _status(out, "positions_rmsd") == "warn"
    assert out.status == "passed_with_warnings"
    # The raw measurement is untouched — re-thresholding never re-measures.
    assert (
        next(c for c in out.checks if c.check_id == "positions_rmsd").measured["rmsd_ang"] == 5e-4
    )


def test_loose_profile_rescues_a_warn() -> None:
    original = _report(rmsd=5e-4)
    out = rethreshold(original, ToleranceProfile.named("loose"))  # warn now 1e-3.
    assert _status(out, "positions_rmsd") == "pass"
    assert out.status == "passed"


def test_strict_profile_demotes_a_pass_to_fail() -> None:
    original = _report(rmsd=5e-4)
    out = rethreshold(original, ToleranceProfile.named("strict"))  # fail now 1e-5.
    assert _status(out, "positions_rmsd") == "fail"
    assert out.status == "failed"


def test_discrete_checks_are_untouched() -> None:
    out = rethreshold(_report(rmsd=0.0), ToleranceProfile.named("strict"))
    assert _status(out, "atom_count") == "pass"
    assert out.tolerance_profile["name"] == "strict"
