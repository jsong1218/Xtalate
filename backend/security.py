"""Request-policy enforcement — auth, rate limiting, the concurrent-job cap (Part 6 §4, §5; M24).

The v0.5 scope is deliberately the smaller half of Part 6 §4: **anonymous self-hosted mode** with
**optional static API keys** from the environment. There are no accounts, no per-user keys, no
sessions — that machinery is hosted-instance work, and its endpoints answer ``404 NOT_ENABLED``
(:mod:`backend.routers.accounts`). What *is* enforced here:

* **Auth.** With no keys configured the instance is anonymous — every request is allowed, and the
  caller is bucketed by client host for the limits below. With one or more keys configured, every
  guarded ``/v1`` request must carry ``Authorization: Bearer <key>`` matching a configured key, or
  it is ``401 UNAUTHORIZED``; the caller is then bucketed by the key.
* **Rate limiting.** A fixed per-minute window per caller — ``429 RATE_LIMITED`` with a
  ``Retry-After`` header (and ``retry_after_s`` in the envelope details) once the window is full.
* **Concurrent-job cap.** Job submission is refused with ``429 TOO_MANY_ACTIVE_JOBS`` when the
  instance already holds ``max_concurrent_jobs`` non-terminal jobs (Part 6 §5).

The rate limiter is in-memory and per-process: correct for the single-instance Tier 0/Tier 1 stack,
and the seam a shared (Redis) limiter attaches behind for a multi-replica hosted instance without a
call-site change (**P6**). Health is never guarded — an orchestrator's probe must not need a key or
be rate-limited.
"""

from __future__ import annotations

import secrets
import threading
import time

from fastapi import Depends, Request, status

from backend.config import Settings
from backend.db import Repository
from backend.deps import get_repository, get_settings
from backend.errors import ApiError


class RateLimiter:
    """A fixed-window per-caller rate limiter (in-memory, thread-safe).

    Each caller gets one counter per wall-clock minute; the counter resets when the minute rolls
    over. A fixed window (not a sliding one) is chosen for its bounded memory and trivial
    correctness — the burst-at-boundary imprecision it trades away does not matter at these limits,
    and a sliding-log limiter is the hosted instance's Redis concern, not Tier 0's.

    "Bounded memory" is made true rather than assumed: a naive ``{caller: bucket}`` map grows
    without limit as distinct client hosts/keys are seen (a public instance meets many), a stale
    bucket from a past minute is never removed. So each time the wall-clock minute advances, every
    bucket from a prior window is swept — a bucket from an old window would be reset to zero on that
    caller's next request anyway, so dropping it loses no enforcement. Memory is then bounded by the
    number of *distinct callers seen within a single minute*, not by all callers ever seen.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: caller key → (minute-window index, count so far in that window).
        self._buckets: dict[str, tuple[int, int]] = {}
        #: The minute window the live buckets belong to; when the clock advances past it, the stale
        #: buckets are swept (see :meth:`check`). ``-1`` means "no window seen yet".
        self._window = -1

    def check(self, caller: str, limit_per_minute: int, *, now: float | None = None) -> None:
        """Count one request for ``caller``; raise :class:`ApiError` ``429`` if the window is full.

        A non-positive ``limit_per_minute`` disables the limit (the local-dev / test escape hatch).
        """
        if limit_per_minute <= 0:
            return
        moment = now if now is not None else time.time()
        window = int(moment // 60)
        with self._lock:
            if window != self._window:
                # A new minute: drop every bucket from a prior window (each would reset to zero on
                # its caller's next request anyway), so the map never accumulates dead callers.
                self._buckets = {c: b for c, b in self._buckets.items() if b[0] == window}
                self._window = window
            bucket_window, count = self._buckets.get(caller, (window, 0))
            if bucket_window != window:
                bucket_window, count = window, 0
            if count >= limit_per_minute:
                retry_after = max(1, int((bucket_window + 1) * 60 - moment))
                raise ApiError(
                    status_code=429,  # literal, not status.HTTP_429_* (deprecated upstream)
                    code="RATE_LIMITED",
                    message="Rate limit exceeded; retry after the window resets.",
                    details={"retry_after_s": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )
            self._buckets[caller] = (bucket_window, count + 1)


def get_rate_limiter(request: Request) -> RateLimiter:
    """The app's shared :class:`RateLimiter` (built once by the factory, stored on app.state)."""
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def _client_id(request: Request) -> str:
    """A best-effort caller identity for anonymous mode — the client host, or ``"anonymous"``."""
    client = request.client
    return client.host if client is not None else "anonymous"


def resolve_principal(request: Request, settings: Settings) -> str:
    """Authenticate the request and return the caller's rate-limit/concurrency bucket key.

    Anonymous mode (no keys configured): the caller is the client host. Keyed mode: the request
    must present ``Authorization: Bearer <key>`` matching a key (constant-time compared), else
    ``401 UNAUTHORIZED``; the caller is then ``key:<key>``. Never logs or echoes the key value.
    """
    keys = settings.api_key_set
    if not keys:
        return _client_id(request)
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if (
        scheme.lower() == "bearer"
        and token
        and any(secrets.compare_digest(token, key) for key in keys)
    ):
        return f"key:{token}"
    raise ApiError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="UNAUTHORIZED",
        message="A valid API key is required (Authorization: Bearer <key>).",
    )


def enforce_request_policy(
    request: Request,
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> str:
    """Router-level dependency: authenticate, then rate-limit, returning the caller principal.

    Stashes the principal on ``request.state.principal`` so a downstream per-endpoint dependency
    (the concurrent-job cap) reuses it rather than re-authenticating.
    """
    principal = resolve_principal(request, settings)
    request.state.principal = principal
    rate_limiter.check(principal, settings.rate_limit_per_minute)
    return principal


def enforce_public_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> str:
    """Rate-limit an **unauthenticated public** endpoint, bucketed by client host — no key required.

    The Capability Matrix (``/v1/capabilities*``) is *public* and ``/v1/limits`` is
    *unauthenticated* by the spec (Part 6 §4, §5): a pipeline reads them *before* it authenticates,
    so requiring a configured static key on them would defeat the pre-check they exist for. They
    are still bucketed for rate limiting (abuse protection) — the difference from
    :func:`enforce_request_policy` is that a missing/invalid key is never a ``401`` here. Health
    stays fully exempt (never even rate-limited); these two are the middle tier — open, but counted.
    """
    caller = _client_id(request)
    request.state.principal = caller
    rate_limiter.check(caller, settings.rate_limit_per_minute)
    return caller


def enforce_active_job_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: Repository = Depends(get_repository),
) -> None:
    """Per-endpoint dependency on job submission: refuse past the concurrent-job cap (§5).

    ``429 TOO_MANY_ACTIVE_JOBS`` when the instance already holds ``max_concurrent_jobs`` active
    jobs. A non-positive cap disables the check. Applied only to the submit endpoints, so polling,
    downloads, and record reads are never blocked by a full worker pool.
    """
    cap = settings.max_concurrent_jobs
    if cap <= 0:
        return
    if repository.count_active_jobs() >= cap:
        raise ApiError(
            status_code=429,  # literal, not status.HTTP_429_* (deprecated upstream)
            code="TOO_MANY_ACTIVE_JOBS",
            message=f"At most {cap} active jobs are allowed at once; wait for one to finish.",
            details={"max_concurrent_jobs": cap},
        )
