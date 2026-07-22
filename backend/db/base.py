"""The declarative base and the one shared JSON column type (v0.5 M21 slice 3).

All ORM models inherit :class:`Base`; its ``metadata`` is what Alembic autogenerate and the initial
migration target, so there is a single source of truth for the schema. ``JSONType`` is defined once
here and used by *both* the models and the migration, so the two never drift on how report bodies
are stored: **JSONB on PostgreSQL** (the spec's choice — indexable, typed) and plain JSON on SQLite
(Tier 0), selected automatically by dialect.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware current UTC instant — the Python-side default for ``created_at`` columns."""
    return datetime.now(UTC)


#: Report/request/error bodies are stored verbatim as JSON (Part 6 preamble — the pydantic report
#: models *are* the wire format, no parallel DTO). JSONB on PostgreSQL, JSON on SQLite. Imported by
#: the initial migration too, so model and migration agree on the column type by construction.
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base for every service ORM model; carries the shared ``metadata``."""
