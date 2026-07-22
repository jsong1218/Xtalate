"""The readiness-probe registry (MASTER_SPEC Part 6, ``/v1/health?ready=true``).

A *readiness* probe answers "can this process serve dependent traffic right now?" — distinct from
*liveness* ("is the process up?"). Each dependency (database, object storage) registers one async
probe under a name; ``GET /v1/health?ready=true`` runs them all and is green only when every probe
is. M21 ships the registry **empty** — there are no stateful dependencies yet — so readiness is
trivially green; M24 registers the real database and object-storage probes here without touching
the health endpoint. Keeping the seam explicit now is why the endpoint needs no rewrite then.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from backend.models import ReadinessCheck

#: A named dependency's readiness probe: called with no arguments, resolves to a
#: :class:`~backend.models.ReadinessCheck`. Probes must not raise — a failed dependency is a
#: ``ReadinessCheck(ok=False, ...)``, not an exception (the health endpoint reports, never crashes).
ReadinessProbe = Callable[[], Awaitable[ReadinessCheck]]
