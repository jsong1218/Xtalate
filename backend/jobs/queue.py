"""The enqueue seam — one interface, an inline (Tier 0) and an RQ (Tier 1) backend (D82).

A submitted job has to *run somewhere*. Following the same two-backends-behind-one-interface rule as
object storage and the database (Part 9 §1.1): the Tier 0 backend runs the job **inline**, in the
submitting process, so a self-hosted instance needs no Redis and no separate worker (a parser bug
fix must never require Docker); the Tier 1 backend hands the job to **RQ on Redis** (D82) for the
``backend.worker`` process to execute, decoupling the API from CPU-bound work. The API layer depends
only on :class:`JobQueue.enqueue`; which backend is behind it is a configuration fact.

The inline backend closes over the app's already-built adapters (it runs *here*); the RQ backend
enqueues the module-level :func:`~backend.jobs.runner.run_job_from_env`, which rebuilds the adapters
from the environment in the worker process — so the two never share in-memory state, matching how RQ
actually works. ``enqueue`` takes only a ``job_id``: the job's inputs already live in the database
and object storage, so the queue message stays a bare id (Part 6 §3), never file bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.config import Settings


@runtime_checkable
class JobQueue(Protocol):
    """The one interface the API uses to schedule a job's execution."""

    def enqueue(self, job_id: str) -> None:
        """Schedule ``job_id`` for execution (inline: run it now; RQ: push it to Redis)."""
        ...


class InlineJobQueue:
    """Tier 0: run the job synchronously in the submitting process (no services, no worker).

    The submit request therefore returns *after* the job has already reached a terminal state — the
    uniform ``202 → poll`` contract still holds (the first poll simply finds it ``completed``) —
    exactly the near-synchronous ergonomics the long-poll design targets for small files (§3.1).
    """

    def __init__(self, runner: Callable[[str], None]) -> None:
        self._runner = runner

    def enqueue(self, job_id: str) -> None:
        self._runner(job_id)


class RQJobQueue:
    """Tier 1: enqueue onto an RQ queue backed by Redis; the ``backend.worker`` process executes."""

    def __init__(self, redis_url: str, *, queue_name: str, job_timeout_seconds: int) -> None:
        from redis import Redis
        from rq import Queue

        self._queue = Queue(
            queue_name, connection=Redis.from_url(redis_url), default_timeout=job_timeout_seconds
        )

    def enqueue(self, job_id: str) -> None:
        from backend.jobs.runner import run_job_from_env

        # RQ enqueues a function *reference* + args; the worker imports and calls it. The job id is
        # also the RQ job id, so a redelivery maps to the same row (execute_job is idempotent).
        self._queue.enqueue(run_job_from_env, job_id, job_id=job_id)


def create_job_queue(settings: Settings, *, runner: Callable[[str], None]) -> JobQueue:
    """Build the configured queue backend. ``runner`` is used only by the inline backend.

    The composition root for the queue: the rest of the service receives a :class:`JobQueue` and
    never learns which backend it is. An unknown backend name fails loudly at startup.
    """
    backend = settings.queue_backend.lower()
    if backend == "inline":
        return InlineJobQueue(runner)
    if backend == "rq":
        return RQJobQueue(
            settings.redis_url,
            queue_name=settings.queue_name,
            job_timeout_seconds=settings.job_timeout_seconds,
        )
    raise ValueError(
        f"unknown queue_backend {settings.queue_backend!r} (expected 'inline' or 'rq')"
    )
