"""The single error-envelope path (Part 6 §6) — every non-2xx wears the same shape (M21)."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.errors import ApiError

_ENVELOPE_KEYS = {"code", "message", "details", "request_id", "documentation_url"}


def _settings() -> Settings:
    return Settings(_env_file=None, docs_base_url="https://docs.test/api")  # type: ignore[call-arg]


def test_unknown_route_is_envelope_not_starlette_default(client: TestClient) -> None:
    resp = client.get("/v1/does-not-exist")
    assert resp.status_code == 404
    assert set(resp.json()["error"]) == _ENVELOPE_KEYS
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_method_not_allowed_is_envelope(client: TestClient) -> None:
    resp = client.post("/v1/limits")  # limits is GET-only
    assert resp.status_code == 405
    assert resp.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_request_validation_failure_is_invalid_request(client: TestClient) -> None:
    # `ready` expects a bool; a non-bool triggers FastAPI request validation → our envelope.
    resp = client.get("/v1/health", params={"ready": "not-a-bool"})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "INVALID_REQUEST"
    assert "errors" in err["details"]


def test_unhandled_exception_becomes_500_envelope_without_leaking() -> None:
    app = create_app(_settings())

    @app.get("/v1/_boom")
    async def _boom() -> None:
        raise RuntimeError("secret file content that must never reach the client")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/_boom")
    assert resp.status_code == 500
    err = resp.json()["error"]
    assert err["code"] == "INTERNAL_ERROR"
    # The raw exception text (which could quote file bytes) is never surfaced (Part 9 §6.1).
    assert "secret file content" not in err["message"]
    assert err["request_id"]


def test_api_error_details_survive_to_the_envelope() -> None:
    app = create_app(_settings())

    @app.get("/v1/_teapot")
    async def _teapot() -> None:
        raise ApiError(
            status_code=status.HTTP_418_IM_A_TEAPOT,
            code="TEAPOT",
            message="short and stout",
            details={"handle": "left"},
        )

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/_teapot")
    assert resp.status_code == 418
    err = resp.json()["error"]
    assert err["code"] == "TEAPOT"
    assert err["details"] == {"handle": "left"}
    assert err["documentation_url"] == "https://docs.test/api#teapot"


def test_request_id_is_consistent_between_header_and_body() -> None:
    app = create_app(_settings())

    @app.get("/v1/_teapot2")
    async def _teapot2() -> None:
        raise ApiError(status_code=400, code="NOPE", message="no")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/_teapot2", headers={"X-Request-ID": "trace-xyz"})
    assert resp.headers["X-Request-ID"] == "trace-xyz"
    assert resp.json()["error"]["request_id"] == "trace-xyz"
