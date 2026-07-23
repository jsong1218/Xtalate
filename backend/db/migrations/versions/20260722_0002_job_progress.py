"""job progress + upload filename (v0.5 M22)

Two additive, nullable columns the job core needs. ``jobs.progress`` is the JSON the worker stamps
with the Part 6 §3.2 envelope ``progress`` ({phase, frames_processed, frames_total}) at each
pipeline-stage boundary; before the job starts it is simply null, which the envelope projects as an
empty :class:`~backend.jobs.envelope.JobProgress`. ``uploads.filename`` keeps the client-supplied
name so the worker's sniffer can use the extension and ``UploadResponse.filename`` (Part 6 §2.2)
echoes it. Both nullable with no server default; JSONType is the shared column type, so this
migration and the ORM models agree on JSONB-vs-JSON by construction (as 0001).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.base import JSONType

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("progress", JSONType, nullable=True))
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("filename", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.drop_column("filename")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("progress")
