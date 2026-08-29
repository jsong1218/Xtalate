"""``GET /v1/files/{id}/geometry`` and ``GET /v1/conversions/{id}/geometry`` (v1.6 M59-S1, D232).

The geometry endpoints are a faithful canonical projection over the proven streaming seam, served by
on-demand re-parse behind a bounded server-side cache, expiring with the bytes (410 exactly like
downloads while reports outlive them). These tests pin the load-bearing rules:

* **Faithful projection & P3.** species/positions come straight from the parsed object; a cell-less
  source answers ``cell: null`` (never a fabricated box); a celled source returns its lattice.
* **Ranged reads.** ``?frames=start:end`` returns exactly ``[start, end)`` while ``frame_count``
  reports the whole object's total — and the read streams through the seam, never materializing the
  whole trajectory (a multi-frame fixture proves a small window is honoured).
* **Ranges are half-open 0-based and validated.** a malformed / reversed ``frames`` is a clean 400
  ``INVALID_FRAME_RANGE``.
* **Expiry-with-bytes.** an expired output 410s while the conversion record still resolves.
* **The bounded cache avoids per-range re-parse** within its byte bound (a spy counts parses).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.db import Repository, utcnow
from backend.db.models import Conversion, Job
from backend.storage import ObjectStore

_XYZ = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""
# Two extXYZ frames of 3 atoms; a Lattice= cell on the first gives ``cell`` a real value.
_extxyz_frame: dict[str, str] = {
    "block": (
        "3\n"
        'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
        'Properties=species:S:1:pos:R:3 pbc="T T T"'
        " {comment}\n"
        "O 0.0 0.0 0.0\nH 1.0 0.0 0.0\nH 0.0 1.0 0.0\n"
    )
}


def _extxyz(n: int) -> bytes:
    return b"".join(_extxyz_frame["block"].format(comment=f"frame{i}").encode() for i in range(n))


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def _convert(client: TestClient, file_id: str) -> dict[str, Any]:
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "extxyz"}).json()
    assert env["state"] == "completed", env
    return cast(dict[str, Any], env)


def _seed_output_conversion(
    repository: Repository,
    object_store: ObjectStore,
    *,
    output_bytes: bytes,
    conversion_status: str = "completed",
    validation_status: str = "passed",
    output_available: bool = True,
    expires_delta: timedelta | None = timedelta(hours=1),
) -> str:
    """Persist a completed job + conversion with a stored extXYZ output (self-contained control)."""
    job_id = "job-geo-test"
    repository.add_job(
        Job(
            job_id=job_id,
            kind="convert",
            state="completed",
            request={"options": {}},
            finished_at=utcnow(),
        )
    )
    conversion_id = "cnv-geo-test"
    key = f"outputs/{conversion_id}"
    if output_available:
        object_store.put(key, [output_bytes])
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job_id,
            target_format="extxyz",
            output_storage_key=key if output_available else None,
            output_available=output_available,
            output_expires_at=(utcnow() + expires_delta) if expires_delta is not None else None,
            conversion_status=conversion_status,
            validation_status=validation_status,
        )
    )
    return conversion_id


def test_file_geometry_projects_faithful_species_positions_and_null_cell(
    client: TestClient,
) -> None:
    # A plain (cell-less) XYZ structure: the projection reports its species and positions verbatim
    # and answers cell: null — absence renders as absence (P3), never a fabricated box.
    file_id = _upload(client, _XYZ, "water.xyz")
    resp = client.get(f"/v1/files/{file_id}/geometry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["format_id"] == "xyz"
    assert body["source"]["filename"] == "water.xyz"
    assert body["species"] == ["O", "H", "H"]
    assert body["cell"] is None
    assert body["frame_count"] == 1
    assert body["frame_index_base"] == 0
    (frame,) = body["frames"]
    assert frame["index"] == 0
    assert frame["cell"] is None
    assert frame["positions"] == [[0.0, 0.0, 0.0], [0.757, 0.586, 0.0], [-0.757, 0.586, 0.0]]


def test_celled_source_returns_its_lattice(client: TestClient) -> None:
    file_id = _upload(client, _extxyz(1), "cell.xyz")
    resp = client.get(f"/v1/files/{file_id}/geometry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["format_id"] == "extxyz"
    assert body["frame_count"] == 1
    # Aligned cubic cell (rows a, b, c) — the source's own Lattice=, not an invented one.
    assert body["cell"] == [
        [5.0, 0.0, 0.0],
        [0.0, 5.0, 0.0],
        [0.0, 0.0, 5.0],
    ]
    assert body["frames"][0]["cell"] == body["cell"]


def test_ranged_frames_return_exactly_the_window_with_true_total(client: TestClient) -> None:
    file_id = _upload(client, _extxyz(5), "traj.xyz")
    # Request frames 1:3 (half-open [1, 3) = absolute frame indices 1 and 2) of a 5-frame object.
    resp = client.get(f"/v1/files/{file_id}/geometry", params={"frames": "1:3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frame_count"] == 5  # the whole object's total, not the window's size
    assert body["frame_index_base"] == 1
    assert [f["index"] for f in body["frames"]] == [1, 2]
    # The source's Lattice= lattice still projects on this celled trajectory.
    assert body["cell"] == [
        [5.0, 0.0, 0.0],
        [0.0, 5.0, 0.0],
        [0.0, 0.0, 5.0],
    ]


def test_malformed_and_reversed_ranges_are_clean_400s(client: TestClient) -> None:
    file_id = _upload(client, _XYZ, "water.xyz")
    for bad in ("3:1", "start:end", "1:", ":2", "1.5:2", "x:y", "5"):
        resp = client.get(f"/v1/files/{file_id}/geometry", params={"frames": bad})
        assert resp.status_code == 400, (bad, resp.text)
        assert resp.json()["error"]["code"] == "INVALID_FRAME_RANGE"


def test_conversion_sides_resolve_source_and_output(client: TestClient) -> None:
    # A real convert then serves both sides: source = the original upload's geometry, output = the
    # written target's geometry — each a faithful projection of those bytes.
    file_id = _upload(client, _extxyz(2), "src.xyz")
    env = _convert(client, file_id)
    conversion_id = env["result"]["conversion_id"]

    src = client.get(f"/v1/conversions/{conversion_id}/geometry", params={"side": "source"})
    assert src.status_code == 200, src.text
    assert src.json()["source"]["format_id"] == "extxyz"
    assert src.json()["frame_count"] == 2

    out = client.get(f"/v1/conversions/{conversion_id}/geometry", params={"side": "output"})
    assert out.status_code == 200, out.text
    assert out.json()["source"]["format_id"] == "extxyz"
    assert out.json()["frame_count"] == 2
    # The output side length matched the source: the conversion's output is also a 2-frame object.
    assert out.json()["frames"][0]["positions"] == src.json()["frames"][0]["positions"]


def test_side_parameter_is_restricted(client: TestClient) -> None:
    file_id = _upload(client, _XYZ, "water.xyz")
    env = _convert(client, file_id)
    conversion_id = env["result"]["conversion_id"]
    resp = client.get(f"/v1/conversions/{conversion_id}/geometry", params={"side": "bogus"})
    assert resp.status_code == 400  # the pattern mismatch is a request-validation failure
    assert resp.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_expired_output_geometry_is_410_while_record_still_resolves(
    client: TestClient, repository: Repository
) -> None:
    # Geometry is bytes-derived, so it expires with the bytes: an expired output's geometry 410s
    # (OUTPUT_EXPIRED, the downloads twin) while the conversion record + reports remain readable.
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    conversion_id = _seed_output_conversion(
        repository, object_store, output_bytes=_extxyz(1), expires_delta=timedelta(hours=-1)
    )

    geo = client.get(f"/v1/conversions/{conversion_id}/geometry", params={"side": "output"})
    assert geo.status_code == 410, geo.text
    assert geo.json()["error"]["code"] == "OUTPUT_EXPIRED"

    # Reports outlive bytes: the record surface is unaffected by the geometry 410.
    record = client.get(f"/v1/conversions/{conversion_id}")
    assert record.status_code == 200, record.text


def test_geometry_cache_avoids_reparse_within_its_bound(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two ranged reads of the same small object hit the bounded cache: the second does not re-parse
    # (no object-store re-read), proving a viewer that scrubs across ranges stays cheap.
    file_id = _upload(client, _extxyz(4), "traj.xyz")

    object_store = cast(ObjectStore, client.app.state.object_store)  # type: ignore[attr-defined]
    original_open = object_store.open
    reopens = 0

    def counting_open(key: str) -> AbstractContextManager[Iterator[bytes]]:
        nonlocal reopens
        reopens += 1
        return original_open(key)

    monkeypatch.setattr(object_store, "open", counting_open)

    first = client.get(f"/v1/files/{file_id}/geometry", params={"frames": "0:2"})
    assert first.status_code == 200, first.text
    assert reopens == 1  # the first request read + parsed the object

    second = client.get(f"/v1/files/{file_id}/geometry", params={"frames": "2:4"})
    assert second.status_code == 200, second.text
    assert reopens == 1  # the second range sliced from cache — no re-parse, no re-read

    assert [f["index"] for f in first.json()["frames"]] == [0, 1]
    assert [f["index"] for f in second.json()["frames"]] == [2, 3]
