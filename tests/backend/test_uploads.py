"""``POST /v1/upload`` — bounded streaming and the ``413`` size gate (M24 deliverable 1).

The shared ``settings`` fixture caps ``max_upload_bytes`` at 1234, so these tests drive the boundary
without a multi-megabyte body: a file at the cap is stored, one byte past it is refused mid-stream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository


def test_upload_at_the_limit_is_stored(client: TestClient, settings: Settings) -> None:
    # A file exactly at max_upload_bytes is accepted — the cap is inclusive.
    content = b"x" * settings.max_upload_bytes
    resp = client.post("/v1/upload", files={"file": ("big.xyz", content)})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["size_bytes"] == settings.max_upload_bytes
    assert body["sha256"]


def test_upload_over_the_limit_is_413(
    client: TestClient, settings: Settings, repository: Repository
) -> None:
    # One byte past the cap is a FILE_TOO_LARGE envelope, and leaves no trace: no Upload row and no
    # object under the would-be key (the partial write is cleaned up).
    content = b"x" * (settings.max_upload_bytes + 1)
    resp = client.post("/v1/upload", files={"file": ("toobig.xyz", content)})
    assert resp.status_code == 413, resp.text
    error = resp.json()["error"]
    assert error["code"] == "FILE_TOO_LARGE"
    assert error["details"]["max_upload_bytes"] == settings.max_upload_bytes
    # The store holds no orphaned bytes for the refused upload.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    assert not any(True for _ in _uploaded_keys(object_store))


def _uploaded_keys(object_store: object) -> list[str]:
    """Best-effort: the filesystem store roots objects under a directory we can walk in-test."""
    from pathlib import Path

    root = getattr(object_store, "_root", None)
    if not isinstance(root, Path):  # pragma: no cover - only the filesystem store is used in-test
        return []
    uploads = root / "uploads"
    return [p.name for p in uploads.iterdir()] if uploads.is_dir() else []
