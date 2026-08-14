"""``/v1/limits`` — every constraint surfaced from configuration (M21)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_limits_reflect_settings(client: TestClient) -> None:
    resp = client.get("/v1/limits")
    assert resp.status_code == 200
    body = resp.json()
    # These two were overridden in the test settings fixture; the rest carry code defaults.
    assert body["max_upload_bytes"] == 1234
    # Days-based retention (no hours override): days is the active field, hours is null.
    assert body["report_retention_days"] == 7
    assert body["report_retention_hours"] is None


def test_limits_has_every_part6_field(client: TestClient) -> None:
    body = client.get("/v1/limits").json()
    assert set(body) == {
        "max_upload_bytes",
        "max_frames",
        "max_concurrent_jobs",
        "rate_limit_per_minute",
        "upload_retention_hours",
        "output_retention_hours",
        "awaiting_recovery_ttl_minutes",
        "report_retention_days",
        "report_retention_hours",
    }


def test_report_retention_may_be_null_for_self_hosts() -> None:
    from fastapi.testclient import TestClient as _TC

    from backend.app import create_app
    from backend.config import Settings

    settings = Settings(_env_file=None, report_retention_days=None)  # type: ignore[call-arg]
    client = _TC(create_app(settings))
    body = client.get("/v1/limits").json()
    # Indefinite retention: both units null.
    assert body["report_retention_days"] is None
    assert body["report_retention_hours"] is None


def test_sub_day_report_retention_is_advertised_in_hours() -> None:
    from fastapi.testclient import TestClient as _TC

    from backend.app import create_app
    from backend.config import Settings

    # The hosted-demo posture: a 1-hour override. Hours wins — days goes null so a client never
    # reads a stale "30 days" while the real window is an hour.
    settings = Settings(_env_file=None, report_retention_hours=1)  # type: ignore[call-arg]
    client = _TC(create_app(settings))
    body = client.get("/v1/limits").json()
    assert body["report_retention_hours"] == 1
    assert body["report_retention_days"] is None
