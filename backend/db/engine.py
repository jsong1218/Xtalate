"""Engine and session construction for the two database backends (v0.5 M21 slice 3).

One builder serves both backends: SQLite (Tier 0) and PostgreSQL (Tier 1). The only backend-
specific care is SQLite's — it needs ``check_same_thread=False`` (the API touches a connection
across threads) and an explicit ``PRAGMA foreign_keys=ON`` per connection, because SQLite does not
enforce foreign keys by default. Without that pragma the ``ON DELETE SET NULL`` / ``CASCADE`` rules
that *are* the reports-outlive-bytes design would silently not fire on Tier 0, and the parity suite
would pass for the wrong reason. ``expire_on_commit=False`` lets the repository return ORM objects
that stay readable after their session closes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.db.base import utcnow

__all__ = ["build_engine", "build_sessionmaker", "utcnow"]


def build_engine(settings: Settings) -> Engine:
    """Create the SQLAlchemy :class:`Engine` for the configured ``database_url`` (both backends)."""
    connect_args: dict[str, Any] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        settings.database_url,
        echo=settings.database_echo,
        connect_args=connect_args,
        future=True,
    )

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    """A session factory whose objects remain readable after commit (``expire_on_commit=False``)."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
