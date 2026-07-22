"""Fixtures for the object-store **parity** suite (v0.5 M21 slice 2).

The ``object_store`` fixture is parametrized over *both* backends, so every test in
``test_object_store_parity.py`` runs identically against the filesystem backend (always, Tier 0)
and the S3 backend (only when a MinIO/S3 endpoint is configured via the environment — otherwise
that leg **skips**, never fails). "Parity is a test, not a hope" (M21) means the same assertions,
not two suites.

To run the S3 leg locally point it at a MinIO instance::

    XTALATE_TEST_S3_ENDPOINT=http://127.0.0.1:9000 \
    XTALATE_TEST_S3_ACCESS_KEY=... XTALATE_TEST_S3_SECRET_KEY=... \
    pytest tests/backend/storage

The Tier 1 compose stack (M21 slice 4) wires exactly these variables so the leg runs in CI.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.storage.filesystem import FilesystemObjectStore  # noqa: E402
from backend.storage.objects import ObjectStore  # noqa: E402

_S3_ENDPOINT_ENV = "XTALATE_TEST_S3_ENDPOINT"


def _s3_configured() -> bool:
    return bool(os.environ.get(_S3_ENDPOINT_ENV))


def _build_s3_store() -> ObjectStore:
    from backend.storage.s3 import S3ObjectStore

    bucket = os.environ.get("XTALATE_TEST_S3_BUCKET", "xtalate-test")
    store = S3ObjectStore(
        bucket=bucket,
        endpoint_url=os.environ[_S3_ENDPOINT_ENV],
        region=os.environ.get("XTALATE_TEST_S3_REGION", "us-east-1"),
        access_key=os.environ.get("XTALATE_TEST_S3_ACCESS_KEY"),
        secret_key=os.environ.get("XTALATE_TEST_S3_SECRET_KEY"),
    )
    _ensure_bucket(store, bucket)
    return store


def _ensure_bucket(store: ObjectStore, bucket: str) -> None:
    # Create the test bucket if the endpoint does not already have it (MinIO fresh start).
    from botocore.exceptions import ClientError

    client = store._client  # type: ignore[attr-defined]
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


@pytest.fixture(params=["filesystem", "s3"])
def object_store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    backend = request.param
    if backend == "filesystem":
        return FilesystemObjectStore(tmp_path)
    if not _s3_configured():
        pytest.skip(f"S3 leg not configured (set {_S3_ENDPOINT_ENV} to run it against MinIO/S3)")
    return _build_s3_store()


@pytest.fixture
def keys(object_store: ObjectStore) -> Iterator[Callable[[str], str]]:
    """Hand out unique per-test keys; delete each on teardown (keeps a real bucket clean)."""
    prefix = f"paritytest-{uuid.uuid4().hex}"
    handed: list[str] = []

    def make(name: str) -> str:
        key = f"{prefix}/{name}"
        handed.append(key)
        return key

    yield make

    for key in handed:
        object_store.delete(key)
