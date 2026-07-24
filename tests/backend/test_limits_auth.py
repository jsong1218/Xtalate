"""Limits and auth — rate limiting, the concurrent-job cap, static keys, NOT_ENABLED (M24 slice 5).

The v0.5 auth scope is anonymous self-hosted mode plus optional static API keys; accounts are
deferred and their endpoints answer ``404 NOT_ENABLED``. These tests drive each protection through
its envelope code, using the ``build_client`` factory to configure a low rate limit, a small job
cap, or a configured key without disturbing the shared settings.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from backend.db.models import Job

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.db import Repository


# --- GET /v1/limits (config-driven surface) -----------------------------------------------------


def test_limits_surface_is_config_driven(client: TestClient) -> None:
    body = client.get("/v1/limits").json()
    # Every Part 6 §5 constraint is present, including report_retention_days (Revision 1.5). The
    # test settings set max_upload_bytes=1234 and report_retention_days=7 — the surface echoes them.
    assert body["max_upload_bytes"] == 1234
    assert body["report_retention_days"] == 7
    for field in (
        "max_frames",
        "max_concurrent_jobs",
        "rate_limit_per_minute",
        "upload_retention_hours",
        "output_retention_hours",
        "awaiting_recovery_ttl_minutes",
    ):
        assert field in body


# --- rate limiting ------------------------------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(
    build_client: Callable[..., TestClient],
) -> None:
    client = build_client(rate_limit_per_minute=2)
    assert client.get("/v1/limits").status_code == 200
    assert client.get("/v1/limits").status_code == 200
    blocked = client.get("/v1/limits")
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert blocked.json()["error"]["details"]["retry_after_s"] >= 1
    assert int(blocked.headers["retry-after"]) >= 1


def test_health_is_never_rate_limited(build_client: Callable[..., TestClient]) -> None:
    # Health is unguarded so an orchestrator's probe never trips the limit, however tight it is.
    client = build_client(rate_limit_per_minute=1)
    for _ in range(5):
        assert client.get("/v1/health").status_code == 200


def test_rate_limiter_sweeps_stale_buckets_when_the_minute_advances() -> None:
    # "Bounded memory" made true: a bucket from a past minute is dropped when the clock advances, so
    # the map is bounded by distinct callers *within one minute*, not by every caller ever seen.
    from backend.security import RateLimiter

    limiter = RateLimiter()
    # A hundred distinct callers in minute 0 (each `now` inside window 0 = [0, 60)).
    for i in range(100):
        limiter.check(f"caller-{i}", limit_per_minute=10, now=1.0)
    assert len(limiter._buckets) == 100

    # One request in the next minute (window 1) sweeps all of window 0's now-dead buckets.
    limiter.check("caller-new", limit_per_minute=10, now=61.0)
    assert set(limiter._buckets) == {"caller-new"}


# --- concurrent-job cap -------------------------------------------------------------------------


def test_concurrent_job_cap_returns_429(
    build_client: Callable[..., TestClient], repository: Repository
) -> None:
    client = build_client(max_concurrent_jobs=2)
    # Seed two non-terminal jobs directly, so the next submit is at the cap. (Under the inline queue
    # a real submit completes instantly, so the cap is exercised by pre-seeding active rows.)
    for _ in range(2):
        repository.add_job(
            Job(job_id=uuid.uuid4().hex, kind="convert", state="running", request={})
        )

    resp = client.post("/v1/inspect", json={"file_id": "whatever"})
    assert resp.status_code == 429, resp.text
    assert resp.json()["error"]["code"] == "TOO_MANY_ACTIVE_JOBS"
    assert resp.json()["error"]["details"]["max_concurrent_jobs"] == 2


# --- static API key auth ------------------------------------------------------------------------


def test_anonymous_mode_needs_no_key(client: TestClient) -> None:
    # No keys configured (the default): the guarded data surface is reachable without an
    # Authorization header (history is guarded, unlike the public capabilities/limits).
    assert client.get("/v1/history").status_code == 200


def test_configured_key_is_required_and_checked(
    build_client: Callable[..., TestClient],
) -> None:
    # A guarded data endpoint (history) requires the key when one is configured.
    client = build_client(api_keys="secret-key,other-key")
    assert client.get("/v1/history").status_code == 401  # missing
    assert client.get("/v1/history").json()["error"]["code"] == "UNAUTHORIZED"

    bad = client.get("/v1/history", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401

    ok = client.get("/v1/history", headers={"Authorization": "Bearer secret-key"})
    assert ok.status_code == 200


def test_capabilities_and_limits_are_public_even_with_a_key_configured(
    build_client: Callable[..., TestClient],
) -> None:
    # The Capability Matrix is public and /v1/limits is unauthenticated (Part 6 §4, §5): a pipeline
    # pre-checks them before it authenticates, so they never require a configured static key. Health
    # stays fully open too; only the data surface (history above) challenges for the key.
    client = build_client(api_keys="secret-key")
    assert client.get("/v1/capabilities").status_code == 200
    assert client.get("/v1/limits").status_code == 200
    assert client.get("/v1/health").status_code == 200


# --- account surface disabled -------------------------------------------------------------------


def test_auth_and_key_endpoints_are_not_enabled(client: TestClient) -> None:
    for method, path in (
        ("post", "/v1/auth/login"),
        ("post", "/v1/auth/signup"),
        ("get", "/v1/keys"),
        ("post", "/v1/keys"),
        ("delete", "/v1/keys/abc"),
    ):
        resp = getattr(client, method)(path)
        assert resp.status_code == 404, (path, resp.text)
        assert resp.json()["error"]["code"] == "NOT_ENABLED"


def test_account_surface_is_not_enabled_even_with_a_key_configured(
    build_client: Callable[..., TestClient],
) -> None:
    # NOT_ENABLED wins over the auth challenge: a self-hoster asking about accounts learns they are
    # off rather than being asked for a key first.
    client = build_client(api_keys="secret-key")
    resp = client.post("/v1/auth/login")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_ENABLED"
