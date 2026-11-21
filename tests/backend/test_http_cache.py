"""ETag / Cache-Control / 304 on the registry-derived read endpoints (QoL Q5)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

PATHS = ["/v1/capabilities", "/v1/capabilities/xyz", "/v1/plugins", "/v1/limits"]


@pytest.mark.parametrize("path", PATHS)
def test_200_carries_etag_and_cache_control(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["etag"].startswith('"') and response.headers["etag"].endswith('"')
    assert response.headers["cache-control"] == "public, max-age=300"


@pytest.mark.parametrize("path", PATHS)
def test_matching_if_none_match_gives_304_with_no_body(client: TestClient, path: str) -> None:
    etag = client.get(path).headers["etag"]
    again = client.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "public, max-age=300"


@pytest.mark.parametrize("path", PATHS)
def test_stale_etag_gets_a_full_200(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"If-None-Match": '"stale"'})
    assert response.status_code == 200 and response.content


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("*", 304),
        ('W/"x", {etag}', 304),
        ('"nope", {etag}', 304),
        ("W/{etag}", 304),
        ('"nope", W/"other"', 200),
    ],
)
def test_if_none_match_list_wildcard_and_weak_forms(
    client: TestClient, header: str, expected: int
) -> None:
    etag = client.get("/v1/plugins").headers["etag"]
    value = header.replace("{etag}", etag)
    assert client.get("/v1/plugins", headers={"If-None-Match": value}).status_code == expected


def test_etag_is_stable_across_requests(client: TestClient) -> None:
    first = client.get("/v1/capabilities").headers["etag"]
    assert first == client.get("/v1/capabilities").headers["etag"]


def test_limits_etag_changes_when_the_settings_change(
    build_client: Callable[..., TestClient],
) -> None:
    a = build_client()
    b = build_client(max_upload_bytes=12345)
    assert a.get("/v1/limits").headers["etag"] != b.get("/v1/limits").headers["etag"]


def test_errors_are_not_cached(client: TestClient) -> None:
    response = client.get("/v1/capabilities/not-a-format")
    assert response.status_code == 404
    assert "etag" not in response.headers
    assert "max-age" not in response.headers.get("cache-control", "")


def test_job_endpoints_are_untouched(client: TestClient) -> None:
    assert "etag" not in client.get("/v1/history").headers
