"""``/v1/health`` — liveness always, readiness green with an empty probe registry (M21)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_ok(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["checks"] == {}
    # Version is the installed library version, surfaced verbatim.
    assert isinstance(body["version"], str) and body["version"]


def test_readiness_green_with_no_dependencies(client: TestClient) -> None:
    # M21 registers no probes, so readiness is trivially green (M24 adds db/object probes).
    resp = client.get("/v1/health", params={"ready": "true"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readiness_degraded_returns_503(client: TestClient) -> None:
    # Simulate the M24 shape: a failing probe must flip status to degraded AND the code to 503,
    # so an orchestrator's readiness gate reacts. Registered directly on app.state for the test.
    from backend.models import ReadinessCheck

    async def _failing_probe() -> ReadinessCheck:
        return ReadinessCheck(ok=False, detail="database: connection refused")

    client.app.state.readiness_checks["database"] = _failing_probe  # type: ignore[attr-defined]
    resp = client.get("/v1/health", params={"ready": "true"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == {"ok": False, "detail": "database: connection refused"}


def test_request_id_header_is_echoed(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.headers.get("X-Request-ID")


def test_client_request_id_is_honoured(client: TestClient) -> None:
    resp = client.get("/v1/health", headers={"X-Request-ID": "my-trace-123"})
    assert resp.headers["X-Request-ID"] == "my-trace-123"


def test_malformed_client_request_id_is_replaced(client: TestClient) -> None:
    # A newline-bearing id must never reach the logs verbatim: it is replaced with a minted one.
    resp = client.get("/v1/health", headers={"X-Request-ID": "bad\nid injection"})
    echoed = resp.headers["X-Request-ID"]
    assert echoed != "bad\nid injection"
    assert "\n" not in echoed
