"""``python -m backend.worker`` — the RQ worker, the second entrypoint on the one image (Part 9 §2).

The API image and the worker image are the **same artifact** (D82, Part 9 §2): the container runs
either ``uvicorn backend.asgi:app`` or this module, so there is no API/worker version skew. This
process connects to the same Redis the API's ``rq`` queue enqueues onto and executes each job via
:func:`~backend.jobs.runner.run_job_from_env`, which rebuilds the adapters from the environment.

Tier 0 does not run this at all — its ``inline`` queue executes jobs in the API process — so this
module is only reached under the ``rq`` backend (Tier 1 compose, M25 hardening). Kept minimal: the
work, the retries, and the timeouts live in the runner and the queue config, not here.
"""

from __future__ import annotations

from backend.config import get_settings


def main() -> None:
    from redis import Redis
    from rq import Queue, Worker

    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    # burst=False: run until signalled, the long-lived process the Part 9 §4.2 container manages.
    worker.work(with_scheduler=False)


if __name__ == "__main__":  # pragma: no cover - process entrypoint.
    main()
