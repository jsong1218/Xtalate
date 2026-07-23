"""The repository — the one door the service has into the relational store (v0.5 M21 slice 3).

A thin, backend-agnostic surface over the ORM: it opens a session per operation, commits, and hands
back detached ORM objects (readable post-commit via ``expire_on_commit=False``). Nothing above this
layer writes SQL or touches a session, so the same code runs unchanged on SQLite and PostgreSQL —
the parity suite proves it. M21 provides the create/read surface plus the two byte-lifecycle
mutations (delete an upload, clear a conversion's output) that the **reports-outlive-bytes** test
exercises; the job-state transitions, idempotent inspect, and history queries are added by
M22–M24 on this same class.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.db.base import as_utc
from backend.db.engine import build_engine, build_sessionmaker, utcnow
from backend.db.models import Conversion, Job, Report, Upload


class Repository:
    """CRUD over uploads, jobs, conversions, and reports, backend-agnostic by construction."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_settings(cls, settings: Settings) -> Repository:
        """Build a repository (and its engine/sessionmaker) from configuration — the usual path."""
        return cls(build_sessionmaker(build_engine(settings)))

    # --- uploads --------------------------------------------------------------------------------

    def add_upload(self, upload: Upload) -> Upload:
        with self._session_factory.begin() as session:
            session.add(upload)
        return upload

    def get_upload(self, file_id: str) -> Upload | None:
        with self._session_factory() as session:
            return session.get(Upload, file_id)

    def live_upload_ids(self, file_ids: Iterable[str]) -> set[str]:
        """The subset of ``file_ids`` whose upload row still holds unexpired, undeleted bytes.

        Drives ``HistoryItem.file_id`` — present only while a re-convert is still possible (Part 6
        §4.4). One query per history page, with the tz-correct expiry test applied in Python (via
        :func:`~backend.db.as_utc`) rather than a tz-sensitive SQL predicate — the same lazy-expiry
        convention the rest of the service uses.
        """
        ids = {f for f in file_ids if f}
        if not ids:
            return set()
        with self._session_factory() as session:
            uploads = session.scalars(select(Upload).where(Upload.file_id.in_(ids)))
            now = utcnow()
            live: set[str] = set()
            for upload in uploads:
                expires_at = as_utc(upload.expires_at)
                if not upload.bytes_deleted and (expires_at is None or expires_at >= now):
                    live.add(upload.file_id)
            return live

    def mark_upload_bytes_deleted(self, file_id: str) -> None:
        """Record that the byte sweep removed the object, without deleting the row."""
        with self._session_factory.begin() as session:
            upload = session.get(Upload, file_id)
            if upload is not None:
                upload.bytes_deleted = True

    def delete_upload(self, file_id: str) -> None:
        """Delete an upload row. ``ON DELETE SET NULL`` nulls any conversion's ``source_file_id`` —
        the reports and conversion records survive (reports-outlive-bytes)."""
        with self._session_factory.begin() as session:
            upload = session.get(Upload, file_id)
            if upload is not None:
                session.delete(upload)

    # --- jobs -----------------------------------------------------------------------------------

    def add_job(self, job: Job) -> Job:
        with self._session_factory.begin() as session:
            session.add(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._session_factory() as session:
            return session.get(Job, job_id)

    def find_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        """The existing job for an idempotency key, or ``None`` (Part 6 §2 idempotent inspect).

        ``POST /v1/inspect`` computes the key from ``(file_id, format_override, registry version)``
        and, on a hit, returns this job's envelope rather than enqueueing duplicate work.
        """
        with self._session_factory() as session:
            stmt = select(Job).where(Job.idempotency_key == idempotency_key)
            return session.scalars(stmt).one_or_none()

    def transition_job(
        self,
        job_id: str,
        target: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: dict[str, object] | None = None,
        progress: dict[str, object] | None = None,
        expires_at: datetime | None = None,
        recovery: dict[str, object] | None = None,
        clear_recovery: bool = False,
    ) -> Job | None:
        """Move a job to ``target`` through the state machine, persisting the edge (Part 6 §3.2).

        The transition is validated by :func:`~backend.jobs.state_machine.assert_transition` before
        anything is written, so an illegal edge raises :class:`InvalidTransition` and the row stays
        exactly as it was — there is no path to a corrupt persisted state. ``updated_at`` is always
        stamped; the optional timestamps/error/progress are set when given. ``expires_at`` and
        ``recovery`` are the M23 pause fields (``running → awaiting_recovery`` stamps a TTL horizon
        and the ``awaiting_recovery`` block); ``clear_recovery`` drops that block when a paused job
        leaves the state (resume/expiry/cancel), so it never lingers on a job no longer paused.
        Returns the updated job, or ``None`` if it does not exist.
        """
        from backend.jobs.state_machine import assert_transition

        with self._session_factory.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            assert_transition(job.state, target)
            job.state = target
            job.updated_at = utcnow()
            if started_at is not None:
                job.started_at = started_at
            if finished_at is not None:
                job.finished_at = finished_at
            if error is not None:
                job.error = error
            if progress is not None:
                job.progress = progress
            if expires_at is not None:
                job.expires_at = expires_at
            if recovery is not None:
                job.recovery = recovery
            if clear_recovery:
                job.recovery = None
            return job

    def set_job_request(self, job_id: str, request: dict[str, object]) -> Job | None:
        """Replace a job's stored ``request`` payload without a state change (Part 6 §3.2 resume).

        The recovery-resume endpoint merges the client's interactive choices into the request and
        marks it ``recovery_resumed`` (so the worker records the applied Assumptions as
        ``origin: "user"``), then re-enqueues; the ``awaiting_recovery → running`` edge itself is
        the worker's. Reassigns the whole dict (not an in-place mutation) so the JSON column change
        is tracked. Always stamps ``updated_at``. Returns the updated job, or ``None`` if absent.
        """
        with self._session_factory.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            job.request = request
            job.updated_at = utcnow()
            return job

    def list_awaiting_recovery(self) -> Sequence[Job]:
        """Every job currently paused in ``awaiting_recovery`` — the expiry sweep's candidate set.

        The sweep (:mod:`backend.jobs.expiry`) applies the ``expires_at <= now`` deadline test in
        Python (via :func:`~backend.db.as_utc`) so the horizon comparison is tz-correct and
        identical on SQLite and PostgreSQL, rather than pushing a timezone-sensitive predicate into
        SQL. Tier 0 holds few paused jobs at once, so returning the whole paused set is cheap; a
        hosted instance's minute-cadence sweeper (Revision 1.4) narrows it the same way.
        """
        with self._session_factory() as session:
            stmt = select(Job).where(Job.state == "awaiting_recovery")
            return list(session.scalars(stmt))

    def set_job_progress(self, job_id: str, progress: dict[str, object]) -> Job | None:
        """Update a running job's ``progress`` without a state change (phase-boundary stamps)."""
        with self._session_factory.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            job.progress = progress
            job.updated_at = utcnow()
            return job

    def set_job_state(
        self,
        job_id: str,
        state: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: dict[str, object] | None = None,
    ) -> Job | None:
        """Minimal state write (the *validated* transition table is M22's job — this just persists).

        Always stamps ``updated_at``; sets the optional timestamps/error when given.
        """
        with self._session_factory.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            job.state = state
            job.updated_at = utcnow()
            if started_at is not None:
                job.started_at = started_at
            if finished_at is not None:
                job.finished_at = finished_at
            if error is not None:
                job.error = error
            return job

    # --- conversions ----------------------------------------------------------------------------

    def add_conversion(self, conversion: Conversion) -> Conversion:
        with self._session_factory.begin() as session:
            session.add(conversion)
        return conversion

    def get_conversion(self, conversion_id: str) -> Conversion | None:
        with self._session_factory() as session:
            return session.get(Conversion, conversion_id)

    def list_conversions(
        self, *, limit: int, before: tuple[datetime, str] | None = None
    ) -> Sequence[Conversion]:
        """A page of conversions, newest first, for ``GET /v1/history`` (Part 6 §4.4).

        Keyset pagination over ``(created_at, conversion_id)`` descending: ``before`` is the last
        item of the previous page, and the predicate is written out as an explicit ``OR`` (rather
        than a row-value tuple comparison) so it runs identically on SQLite and PostgreSQL. A record
        inserted between page fetches cannot shift or duplicate an item — the cursor names a fixed
        point in the ordering, not an offset.
        """
        with self._session_factory() as session:
            stmt = select(Conversion).order_by(
                Conversion.created_at.desc(), Conversion.conversion_id.desc()
            )
            if before is not None:
                created_at, conversion_id = before
                stmt = stmt.where(
                    or_(
                        Conversion.created_at < created_at,
                        and_(
                            Conversion.created_at == created_at,
                            Conversion.conversion_id < conversion_id,
                        ),
                    )
                )
            return list(session.scalars(stmt.limit(limit)))

    def get_conversion_reports(self, conversion_ids: Sequence[str]) -> dict[str, Report]:
        """The ``conversion``-kind Report for each id, keyed by conversion id (history summaries).

        One query for a whole history page (rather than N per-conversion reads); a conversion whose
        report is somehow absent simply does not appear in the map, and the caller falls back to the
        record's denormalized fields.
        """
        ids = list(conversion_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            stmt = select(Report).where(Report.conversion_id.in_(ids), Report.kind == "conversion")
            return {
                r.conversion_id: r for r in session.scalars(stmt) if r.conversion_id is not None
            }

    def clear_output_bytes(self, conversion_id: str) -> Conversion | None:
        """Byte expiry of the *output*: drop the storage key and mark it unavailable, keeping the
        record and its reports (the reports-outlive-bytes promise for the output side)."""
        with self._session_factory.begin() as session:
            conversion = session.get(Conversion, conversion_id)
            if conversion is None:
                return None
            conversion.output_storage_key = None
            conversion.output_available = False
            return conversion

    # --- reports --------------------------------------------------------------------------------

    def add_report(self, report: Report) -> Report:
        with self._session_factory.begin() as session:
            session.add(report)
        return report

    def get_report(self, report_id: str) -> Report | None:
        with self._session_factory() as session:
            return session.get(Report, report_id)

    def get_reports_for_conversion(self, conversion_id: str) -> Sequence[Report]:
        with self._session_factory() as session:
            stmt = (
                select(Report)
                .where(Report.conversion_id == conversion_id)
                .order_by(Report.created_at)
            )
            return list(session.scalars(stmt))

    def get_reports_for_job(self, job_id: str) -> Sequence[Report]:
        with self._session_factory() as session:
            stmt = select(Report).where(Report.job_id == job_id).order_by(Report.created_at)
            return list(session.scalars(stmt))
