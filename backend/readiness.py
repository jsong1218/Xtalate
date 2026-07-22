"""The readiness-probe registry and the concrete dependency probes (``/v1/health?ready=true``).

A *readiness* probe answers "can this process serve dependent traffic right now?" — distinct from
*liveness* ("is the process up?"). Each dependency (database, object storage) registers one async
probe under a name; ``GET /v1/health?ready=true`` runs them all and is green only when every probe
is. :func:`backend.app.create_app` registers the two below so the M21 done-means holds — ``docker
compose up`` then ``curl /v1/health?ready=true`` shows every dependency green (Part 6 §4;
IMPLEMENTATION_PLAN_v0.5 M21 deliverable 4). (An earlier draft deferred these probes to M24; the
M21 done-means requires them here, so they land with the persistence adapters they check.)

A probe **must not raise** — a failed dependency is a :class:`~backend.models.ReadinessCheck` with
``ok=False``, never an exception, because the health endpoint reports on dependencies, it does not
crash with them. The blocking backend I/O (a SQL round-trip, a bucket HEAD) runs in a worker thread
via :func:`anyio.to_thread.run_sync` so a slow dependency never stalls the event loop. The
``detail`` string carries only the backend kind and an exception *type* name — never a connection
string, credential, or file content (see :class:`~backend.models.ReadinessCheck`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import anyio
from sqlalchemy import Engine, text

from backend.models import ReadinessCheck
from backend.storage import ObjectStore

#: A named dependency's readiness probe: called with no arguments, resolves to a
#: :class:`~backend.models.ReadinessCheck`. Probes must not raise — a failed dependency is a
#: ``ReadinessCheck(ok=False, ...)``, not an exception (the health endpoint reports, never crashes).
ReadinessProbe = Callable[[], Awaitable[ReadinessCheck]]

#: A server-minted, never-written key the object-store probe reads to prove reachability. ``exists``
#: on an absent key is a cheap, side-effect-free round-trip (a HEAD on S3, a ``stat`` on the
#: filesystem); the *answer* (present/absent) is irrelevant — only that the backend answered at all.
_OBJECT_STORE_PROBE_KEY = "healthcheck/readiness-probe"


def database_probe(engine: Engine) -> ReadinessProbe:
    """A readiness probe that proves the relational store answers a trivial ``SELECT 1``.

    Shares the application's :class:`~sqlalchemy.Engine` (and its connection pool) rather than
    opening a throwaway one, so the probe checks the very path requests use. The query touches no
    table, so it is green the moment the server is reachable — schema readiness is a migration
    concern, not a liveness one.
    """
    kind = engine.dialect.name

    async def _probe() -> ReadinessCheck:
        def _check() -> None:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

        try:
            await anyio.to_thread.run_sync(_check)
        except Exception as exc:  # a failed dependency is a report, not a crash
            return ReadinessCheck(ok=False, detail=f"{kind}: {type(exc).__name__}")
        return ReadinessCheck(ok=True, detail=kind)

    return _probe


def object_store_probe(store: ObjectStore, kind: str) -> ReadinessProbe:
    """A readiness probe that proves the object store is reachable via a single ``exists`` call.

    ``kind`` is the configured backend name (``"filesystem"`` / ``"s3"``) reported in ``detail``.
    The probe neither writes nor deletes: a lone ``exists`` on a never-written key is the smallest
    round-trip that distinguishes "backend reachable" from "backend down", and it can never mutate
    stored bytes.
    """

    async def _probe() -> ReadinessCheck:
        def _check() -> None:
            store.exists(_OBJECT_STORE_PROBE_KEY)

        try:
            await anyio.to_thread.run_sync(_check)
        except Exception as exc:  # a failed dependency is a report, not a crash
            return ReadinessCheck(ok=False, detail=f"{kind}: {type(exc).__name__}")
        return ReadinessCheck(ok=True, detail=kind)

    return _probe
