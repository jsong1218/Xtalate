"""batch_convert parent↔child link (v1.5 M58)

One additive, nullable column, ``jobs.parent_job_id`` — a self-referential foreign key naming the
``batch_convert`` parent job a child convert job was fanned out from (Part 6 §3, M58). ``SET
NULL`` on parent delete so an account sweep that removes the parent never cascades into the
children: each child is an ordinary, independently-navigable ``convert`` job whose records must
survive the parent. Nullable with no server default, so before M58's fan-out ever runs the column
is simply null on every existing row — the envelope never projects it, exactly like ``recovery``
before M23. Mirrors the 0003 pattern (additive nullable column, batch alter for SQLite parity).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "parent_job_id",
                sa.String(64),
                sa.ForeignKey("jobs.job_id", ondelete="SET NULL", name="fk_jobs_parent_job_id"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_jobs_parent_job_id", ["parent_job_id"])


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_parent_job_id")
        batch_op.drop_column("parent_job_id")
