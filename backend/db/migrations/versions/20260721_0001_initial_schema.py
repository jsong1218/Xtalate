"""initial schema — uploads, jobs, conversions, reports

The FK ``ondelete`` rules are the design, not decoration (see :mod:`backend.db.models`):
``conversions.source_file_id`` is ``SET NULL`` so input-byte expiry never deletes a conversion or
its reports (reports-outlive-bytes); the job/conversion FKs are ``CASCADE`` so account/retention
deletes clean up correctly. JSON columns use the shared :data:`backend.db.base.JSONType` — the same
object the ORM models use — so the migration and the models cannot drift on JSONB-vs-JSON.

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.base import JSONType

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request", JSONType, nullable=False),
        sa.Column("error", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "uploads",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("format_override", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bytes_deleted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("file_id"),
    )
    op.create_table(
        "conversions",
        sa.Column("conversion_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("source_file_id", sa.String(length=64), nullable=True),
        sa.Column("source_format", sa.String(length=64), nullable=True),
        sa.Column("target_format", sa.String(length=64), nullable=False),
        sa.Column("output_storage_key", sa.String(length=512), nullable=True),
        sa.Column("output_available", sa.Boolean(), nullable=False),
        sa.Column("output_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversion_status", sa.String(length=32), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["uploads.file_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("conversion_id"),
    )
    with op.batch_alter_table("conversions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_conversions_job_id"), ["job_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_conversions_source_file_id"),
            ["source_file_id"],
            unique=False,
        )
    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("conversion_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("body", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversion_id"],
            ["conversions.conversion_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_reports_conversion_id"), ["conversion_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_reports_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reports_job_id"))
        batch_op.drop_index(batch_op.f("ix_reports_conversion_id"))
    op.drop_table("reports")
    with op.batch_alter_table("conversions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conversions_source_file_id"))
        batch_op.drop_index(batch_op.f("ix_conversions_job_id"))
    op.drop_table("conversions")
    op.drop_table("uploads")
    op.drop_table("jobs")
