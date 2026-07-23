"""The async job core (MASTER_SPEC Part 6 §3) — the critical path of v0.5 (milestone M22).

Submit → poll → retrieve, uniformly, for the three long-running operations. The pieces:

* :mod:`~backend.jobs.state_machine` — the legal-transition table, the single source of truth every
  state write goes through (the done-means' transition-table test targets it directly).
* :mod:`~backend.jobs.envelope` — the :class:`~backend.jobs.envelope.JobEnvelope` wire shape
  returned on submit and every poll; its ``result`` embeds the library's report models verbatim.
* :mod:`~backend.jobs.queue` — the enqueue seam: an inline backend (Tier 0, no services) and an RQ
  backend (Tier 1, Redis) behind one interface, mirroring the storage/database two-backend pattern.
* :mod:`~backend.jobs.runner` — executes a job by calling the library exactly as the CLI does, and
  persists every transition; a refusal is a *completed* job, a crash is a *failed* one.

The ``awaiting_recovery`` pause, cancellation, and the file/download surface are M23/M24 — they add
callers and result detail to these same modules, never reshape them (**P6**).
"""

from __future__ import annotations

from backend.jobs.envelope import JobEnvelope, JobProgress
from backend.jobs.state_machine import (
    LEGAL_TRANSITIONS,
    STATES,
    TERMINAL_STATES,
    InvalidTransition,
    assert_transition,
    is_legal,
    is_terminal,
)

__all__ = [
    "LEGAL_TRANSITIONS",
    "STATES",
    "TERMINAL_STATES",
    "InvalidTransition",
    "JobEnvelope",
    "JobProgress",
    "assert_transition",
    "is_legal",
    "is_terminal",
]
