"""Structured JSON logs for the worker (MASTER_SPEC Part 9 §6.1).

The worker emits one JSON object per lifecycle event, carrying the correlation ids (``request_id``,
``job_id``) and coarse operational facts (``kind``, ``state``, ``event``) — **never scientific file
content**. That boundary is the whole point of Part 9 §6.1: a log line may quote a job id, never an
atom coordinate or a filename's contents. Structured (not free-text) so the hosted instance can
aggregate on ``job_id`` and the retention-sweep/latency alerts (Part 9 §6.1) have fields to match.

Deliberately tiny and dependency-free: a helper that serializes a flat dict to one JSON line on a
named logger. If a value is not JSON-serializable it is coerced to ``repr`` rather than raising —
a log call must never itself crash the worker.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_LOGGER = logging.getLogger("xtalate.worker")


def log_event(event: str, *, job_id: str, request_id: str | None = None, **fields: Any) -> None:
    """Emit one structured JSON log line for a worker ``event`` (e.g. ``"job.running"``).

    ``**fields`` carries only non-sensitive operational facts (kind, state, error code, durations).
    Callers must never pass file content, coordinates, or report bodies — this helper does not, and
    cannot, redact; the contract is enforced at the call sites (Part 9 §6.1).
    """
    payload: dict[str, Any] = {"event": event, "job_id": job_id}
    if request_id is not None:
        payload["request_id"] = request_id
    payload.update(fields)
    try:
        line = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        line = json.dumps({k: repr(v) for k, v in payload.items()}, ensure_ascii=False)
    _LOGGER.info(line)
