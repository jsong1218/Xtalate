"""The relational model — uploads, jobs, conversions, reports (MASTER_SPEC Part 1 §4.4).

Four tables, and the foreign-key *directions* are the design:

* A **conversion** references its **upload** with ``ON DELETE SET NULL`` — so sweeping expired input
  bytes (deleting the upload row) leaves the conversion and its reports intact. This is
  **reports-outlive-bytes** expressed in the schema, not enforced by application care: the report
  rows carry no dependency on any stored file bytes, only on the conversion metadata row.
* A **conversion** references its **job**, and a **report** references its **job** (and, when it is
  a conversion/validation report, its conversion) with ``ON DELETE CASCADE`` — so the M24 report-
  retention sweep (delete the conversion) and account deletion (delete the job) cascade to reports
  correctly, while byte expiry (a different, shorter window) never does.

The row *state* semantics — the job state machine, idempotency, output-expiry bookkeeping — belong
to M22–M24; this slice defines the tables, their relationships, and the columns those milestones
fill. JSON columns hold the report/request/error bodies **verbatim** (no DTO reshaping).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JSONType, utcnow

# --- controlled vocabularies (kept as strings, not DB enums, for SQLite/PostgreSQL parity) --------

#: Job kinds — the three long-running operations (Part 6 §3).
JOB_KINDS = ("inspect", "convert", "validate")

#: Job states (Part 6 §3.2). The transitions between them are M22's tested state machine; here they
#: are just the allowed column values.
JOB_STATES = (
    "queued",
    "running",
    "awaiting_recovery",
    "completed",
    "failed",
    "cancelled",
    "expired",
)

#: Report kinds — the three report schemas persisted verbatim.
REPORT_KINDS = ("discovery", "conversion", "validation")


class Upload(Base):
    """An uploaded input file: its content hash, size, and the object-storage key for its bytes.

    The bytes live in object storage (:mod:`backend.storage`), not here; this row is the metadata
    and the pointer. When the byte-lifecycle sweep removes the object (Part 9 §5.2), this row is
    deleted — and because conversions reference it ``ON DELETE SET NULL``, that removal never
    cascades into conversions or reports.
    """

    __tablename__ = "uploads"

    file_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(sa.String(255))
    storage_key: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    format_override: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    #: Set true when the byte-lifecycle sweep removed the object but the row is briefly retained.
    bytes_deleted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)


class Job(Base):
    """A long-running operation (inspect/convert/validate) and its lifecycle state.

    The envelope columns (state, timestamps, ``expires_at``, request/error bodies) are here from
    M21; M22 owns the state machine that drives ``state`` and the idempotency key that dedupes
    ``inspect`` submissions.
    """

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    state: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    #: Same file + override + registry version returns the existing job (Part 6 idempotency, M22).
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128), unique=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    conversions: Mapped[list[Conversion]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Conversion(Base):
    """A convert job's result record — the durable metadata that **outlives** the output bytes.

    ``output_storage_key`` points at the converted bytes in object storage; when those expire the
    key is cleared and ``output_available`` goes false, but this row and its reports remain
    retrievable (the ``GET /v1/conversions/{id}`` with ``download.available=false`` promise, M24).
    ``source_file_id`` is ``ON DELETE SET NULL`` so input-byte expiry cannot delete this record.
    """

    __tablename__ = "conversions"

    conversion_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_file_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("uploads.file_id", ondelete="SET NULL"), index=True
    )
    source_format: Mapped[str | None] = mapped_column(sa.String(64))
    target_format: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    output_storage_key: Mapped[str | None] = mapped_column(sa.String(512))
    output_available: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    output_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    #: The Conversion Report's ``status`` (``completed``/``refused``) and the Validation Report's
    #: pass/fail, denormalized for cheap history chips (Part 6 §4.4 ``HistoryItem``, M24).
    conversion_status: Mapped[str | None] = mapped_column(sa.String(32))
    validation_status: Mapped[str | None] = mapped_column(sa.String(32))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )

    job: Mapped[Job] = relationship(back_populates="conversions")
    reports: Mapped[list[Report]] = relationship(
        back_populates="conversion", cascade="all, delete-orphan"
    )


class Report(Base):
    """A Discovery/Conversion/Validation report, stored **verbatim** as JSON.

    Every report belongs to a job; conversion and validation reports also belong to a conversion
    (a discovery report, from an inspect job, does not). The body is the pydantic report model
    dumped with ``mode="json"`` — no reshaping, so a read serves back exactly what the library
    produced (Part 6 preamble). Reports depend only on these metadata rows, never on file bytes,
    which is what lets them outlive both the input and the output.
    """

    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversion_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("conversions.conversion_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )

    job: Mapped[Job] = relationship(back_populates="reports")
    conversion: Mapped[Conversion | None] = relationship(back_populates="reports")
