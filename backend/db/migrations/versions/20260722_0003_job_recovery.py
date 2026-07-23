"""job awaiting_recovery block (v0.5 M23)

One additive, nullable JSON column, ``jobs.recovery``, that a convert job paused in
``awaiting_recovery`` carries (Part 6 §3.2): the pre-flight draft report plus the **computed**
option lists (with ``parameters_schema`` hints) the interactive recovery prompt renders from. It is
set only while the job is paused and cleared on resume/expiry/cancel, so before M23's pause path is
ever taken it is simply null — which the envelope projects as no ``awaiting_recovery`` block.
Nullable with no server default; JSONType is the shared column type, so this migration and the ORM
model agree on JSONB-vs-JSON by construction (as 0001/0002).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.base import JSONType

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("recovery", JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("recovery")
