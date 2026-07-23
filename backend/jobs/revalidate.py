"""Re-threshold a stored conversion's validation under a new tolerance profile (Part 5 §4.5; §2).

``POST /v1/validate`` is **not** a re-parse: it re-evaluates a conversion's already-*measured*
values against a different :class:`~xtalate.validation.ToleranceProfile`, needing only the stored
``ValidationReport`` and works long after the source/output bytes have expired (reports outlive
bytes). The worker loads the conversion's stored validation report, re-thresholds it with the
library's ``rethreshold`` (the exact function the CLI's offline re-threshold path uses), and
**appends** a new validation report — prior reports are retained, re-validation never replaces (§2).

A conversion that has no stored validation report (e.g. a refused conversion, which produced no
output and therefore nothing to validate) has nothing to re-threshold; that is a ``failed`` job with
a clear code, distinct from the unknown-conversion ``404`` the submit endpoint returns fast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.jobs.runner import _new_id

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db.models import Job
    from backend.db.repository import Repository


class RevalidateError(Exception):
    """A re-threshold that cannot proceed (no stored validation report) — a ``failed`` outcome."""


def _resolve_profile(value: str | dict[str, Any]) -> Any:
    """A named profile (``default``/``strict``/``loose``) or a custom tolerance table (§4.4)."""
    from xtalate.validation import ToleranceProfile

    if isinstance(value, str):
        return ToleranceProfile.named(value)
    return ToleranceProfile.from_mapping("custom", value)


def run_revalidate(job: Job, repository: Repository, settings: Settings) -> None:
    """Load the stored validation report, re-threshold it, and append the new one."""
    from backend.db.models import Report
    from xtalate.validation import ValidationReport, rethreshold

    conversion_id = job.request["conversion_id"]
    stored = next(
        (r for r in repository.get_reports_for_conversion(conversion_id) if r.kind == "validation"),
        None,
    )
    if stored is None:
        raise RevalidateError(
            f"conversion {conversion_id!r} has no stored validation report to re-threshold"
        )

    profile = _resolve_profile(job.request.get("tolerance_profile", "default"))
    rethresholded = rethreshold(ValidationReport.model_validate(stored.body), profile)
    repository.add_report(
        Report(
            report_id=_new_id("rep"),
            job_id=job.job_id,
            conversion_id=conversion_id,
            kind="validation",
            body=rethresholded.model_dump(mode="json"),
        )
    )
