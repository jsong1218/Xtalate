"""Re-thresholding tests (M6, MASTER_SPEC Part 5 §4.5).

Re-thresholding re-judges a stored report's measurements under a new profile *without re-parsing*:
measurements are copied verbatim; only statuses and the aggregate change. These pin that a looser
profile can rescue a warn/fail and a stricter one can demote a pass, while discrete checks and the
raw measured values are untouched.
"""

from __future__ import annotations

from xtalate.validation import ToleranceProfile, rethreshold
from xtalate.validation.report import CheckResult, ValidationReport


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


def _numeric_report(bound: float) -> ValidationReport:
    """A stored report whose ``numeric_field_fidelity`` carries a per-path
    representational bound."""
    return ValidationReport(
        report_id="v2",
        conversion_report_id="c2",
        created_at="2026-01-01T00:00:00Z",
        status="passed",
        checks=[
            CheckResult(
                check_id="numeric_field_fidelity",
                status="pass",
                paths=["dynamics.forces"],
                measured={
                    "dynamics.forces": {
                        "max_abs_diff": 5e-4,
                        "warn": 1e-6,
                        "fail": 1e-4,
                        "missing": False,
                        "representational_bound": bound,
                    }
                },
                message="ok",
            )
        ],
        tolerance_profile={"name": "default"},
        reparse_issues=[],
        schema_version="0.1.0",
    )


def test_numeric_rethreshold_reapplies_the_stored_representational_bound() -> None:
    """The representational floor is a property of the *format's* declared precision, not of the
    profile, so re-judging must re-apply it exactly as the live engine did.

    ``_rejudge_scalar`` always did; ``_rejudge_numeric`` called ``effective(quantity)`` with no
    bound, silently tightening ``numeric_field_fidelity`` on every offline re-threshold. It was
    inert only because no exporter declares ``numeric_precision``, so every stored bound was 0.0 —
    a latent mis-judgement waiting for the first format that declares one. The bound could not be
    re-applied even in principle before this, because the engine never recorded it per path.
    """
    strict = ToleranceProfile.named("strict")
    without = rethreshold(_numeric_report(0.0), strict)
    with_bound = rethreshold(_numeric_report(1e-2), strict)

    sub_without = without.checks[0].measured["dynamics.forces"]
    sub_with = with_bound.checks[0].measured["dynamics.forces"]
    assert isinstance(sub_without, dict) and isinstance(sub_with, dict)
    # A generous representational bound must *loosen* the effective thresholds, and the 5e-4
    # measurement that fails without it must pass with it.
    assert float(str(sub_with["fail"])) > float(str(sub_without["fail"]))
    assert without.checks[0].status == "fail"
    assert with_bound.checks[0].status == "pass"
