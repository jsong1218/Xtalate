"""The queue seam: inline runs now, RQ enqueues to Redis, an unknown backend fails loudly."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.config import Settings  # noqa: E402
from backend.jobs.queue import InlineJobQueue, create_job_queue  # noqa: E402


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


def test_inline_backend_runs_the_job_synchronously() -> None:
    ran: list[str] = []
    queue = create_job_queue(_settings(queue_backend="inline"), runner=ran.append)
    assert isinstance(queue, InlineJobQueue)
    queue.enqueue("job-42")
    assert ran == ["job-42"]  # executed inline, before enqueue returned


def test_unknown_backend_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown queue_backend"):
        create_job_queue(_settings(queue_backend="celery"), runner=lambda _job_id: None)


def test_rq_backend_enqueues_the_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fakeredis = pytest.importorskip("fakeredis")

    # Back RQ with an in-memory fake Redis so the test needs no server.
    monkeypatch.setattr("redis.Redis.from_url", lambda _url, **_kw: fakeredis.FakeStrictRedis())
    queue = create_job_queue(_settings(queue_backend="rq"), runner=lambda _job_id: None)
    queue.enqueue("job-99")

    from rq import Queue

    rq_queue = queue._queue  # type: ignore[attr-defined]
    assert isinstance(rq_queue, Queue)
    assert "job-99" in rq_queue.job_ids  # the id landed on the queue, not executed inline
