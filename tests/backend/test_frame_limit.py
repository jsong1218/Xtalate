"""The frame cap enforced by the service (v1.1 M39-S3, the M37 finding-F1 / D128 ticket).

``settings.max_frames`` is a real gate on the inspect and convert job paths: an over-cap
trajectory is refused **during the streaming read** with the Part 6 §5 code
``FRAME_LIMIT_EXCEEDED`` (a *failed* job — the envelope's ``error.code``, carrying
``details.frame_count`` / ``details.max_frames`` — distinct from a *refused* conversion, which is a
completed HTTP-200 job), and an at-cap trajectory converts normally. ``/v1/limits`` keeps reporting
the number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Callable

# One extXYZ frame, 3 atoms — 3 frames ≈ 621 bytes, under the conftest 1234-byte upload gate.
_FRAME = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} config_type=md pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
    "H 0.0 1.0 0.0 0.0 0.0 0.3\n"
)


def _traj(n: int) -> bytes:
    return "".join(_FRAME.format(e=f"-1.{i}") for i in range(n)).encode()


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def test_over_cap_convert_is_refused_422_frame_limit_exceeded(
    build_client: Callable[..., TestClient],
) -> None:
    client = build_client(max_frames=2)
    file_id = _upload(client, _traj(3), "t.xyz")

    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "extxyz"}).json()
    assert env["state"] == "failed"
    error = env["error"]
    assert error["code"] == "FRAME_LIMIT_EXCEEDED"
    assert error["details"] == {"frame_count": 3, "max_frames": 2}
    assert error["documentation_url"].endswith("#frame_limit_exceeded")
    # The poll agrees — the row is terminal, not stuck.
    polled = client.get(f"/v1/jobs/{env['job_id']}").json()
    assert polled["state"] == "failed"
    assert polled["error"]["code"] == "FRAME_LIMIT_EXCEEDED"


def test_at_cap_convert_succeeds(build_client: Callable[..., TestClient]) -> None:
    client = build_client(max_frames=3)
    file_id = _upload(client, _traj(3), "t.xyz")

    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "extxyz"}).json()
    assert env["state"] == "completed", env
    assert env["result"]["conversion_report"]["status"] == "completed"


def test_over_cap_inspect_is_refused_too(build_client: Callable[..., TestClient]) -> None:
    # An inspect job must not materialize a pathological trajectory either — the discovery path
    # enforces the same cap.
    client = build_client(max_frames=2)
    file_id = _upload(client, _traj(3), "t.xyz")

    env = client.post("/v1/inspect", json={"file_id": file_id}).json()
    assert env["state"] == "failed"
    assert env["error"]["code"] == "FRAME_LIMIT_EXCEEDED"
    assert env["error"]["details"] == {"frame_count": 3, "max_frames": 2}


def test_limits_still_report_max_frames(build_client: Callable[..., TestClient]) -> None:
    # The number a client pre-checks against is the same number the job path enforces.
    client = build_client(max_frames=2)
    assert client.get("/v1/limits").json()["max_frames"] == 2
