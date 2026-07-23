"""Report retention — the daily sweep that ages out conversion records (Revision 1.5; M24 slice 4).

Xtalate keeps **two** retention windows, and this is the longer of them (Part 6 §5, Part 9 §5.2):

* The **byte** window (``upload_retention_hours`` / ``output_retention_hours``) is the storage
  platform's job — a bucket lifecycle rule sweeps the objects, never an app cron. The service only
  *observes* that expiry lazily (a download past the horizon is a ``410``); it never deletes bytes
  on a schedule itself.
* The **record** window (``report_retention_days``) is this sweep. A conversion record and its
  reports outlive the bytes so a client can still read *what happened* after the file is gone — but
  not forever: after ``report_retention_days`` the record and its reports are deleted too. ``None``
  means indefinite retention (the self-hosted default), and the sweep is then a no-op.

Deleting the conversion cascades to its Conversion/Validation reports; the originating job and any
upload row survive (account deletion, a separate and immediate cascade, is what removes those). This
is a plain callable, like :func:`~backend.jobs.expiry.sweep_expired`: Tier 0 runs no scheduler, so
the function exists to be driven by a hosted instance's daily cron (or a test's injected clock)
without a background process being part of the no-services tier.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from backend.db import utcnow
from backend.jobs.logging import log_event

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository


def sweep_reports(
    repository: Repository, settings: Settings, *, now: datetime | None = None
) -> list[str]:
    """Delete every conversion record past ``report_retention_days``, returning the ids deleted.

    A ``None`` ``report_retention_days`` is indefinite retention — the sweep does nothing. ``now``
    is injectable so a test drives the cutoff deterministically; it defaults to :func:`utcnow`.
    """
    if settings.report_retention_days is None:
        return []
    when = now or utcnow()
    cutoff = when - timedelta(days=settings.report_retention_days)
    deleted = repository.delete_conversions_created_before(cutoff)
    if deleted:
        # A batch sweep, not a single job: job_id="-" marks the log line as not job-scoped. Only the
        # count is logged — never a conversion id, filename, or any content (Part 9 §6.1).
        log_event("reports.swept", job_id="-", count=len(deleted))
    return deleted
