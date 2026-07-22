"""The relational persistence half of the M21 adapters — one repository, two backends.

SQLite (Tier 0, no services) and PostgreSQL (Tier 1) sit behind one :class:`Repository`; the schema
(:mod:`backend.db.models`) encodes **reports-outlive-bytes** through its foreign-key directions, and
the Alembic chain under ``backend/db/migrations`` builds it from empty. Two backends behind one
interface, verified by a parity suite — Part 9 §1.1.
"""

from __future__ import annotations

from backend.db.base import Base, utcnow
from backend.db.engine import build_engine, build_sessionmaker
from backend.db.models import Conversion, Job, Report, Upload
from backend.db.repository import Repository

__all__ = [
    "Base",
    "Conversion",
    "Job",
    "Report",
    "Repository",
    "Upload",
    "build_engine",
    "build_sessionmaker",
    "utcnow",
]
