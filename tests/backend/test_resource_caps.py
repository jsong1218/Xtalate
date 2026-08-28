"""Per-job resource caps, demonstrated (M37 security drill — Part 9 §5.3, §6 item 5).

The security-hardening pass claims each per-job resource cap "exhausts *its own* job and nothing
else": a pathological request is refused with a bounded, honest error while a concurrent well-formed
request is unaffected, and the instance is never wedged. These tests are the *demonstration* of that
claim over the caps the service **actually enforces**:

* the **upload byte cap** (``max_upload_bytes`` → ``413 FILE_TOO_LARGE``, streamed and refused
  mid-body, M24), and
* the **concurrent-job cap** (``max_concurrent_jobs`` → ``429 TOO_MANY_ACTIVE_JOBS``, §5).

They assert *existing* behaviour — no ``src/``/``backend/`` change is made or needed. The framing
they add over the individual limit tests (``test_uploads``, ``test_limits_auth``) is the
**isolation** property the drill is about: the pathological request fails itself and leaves the next
well-formed request working.

Two further per-job resource bounds are evidence *elsewhere*, cited here so the drill's coverage is
legible:

* the **memory** bound — the frame-chunked streaming core keeps RSS sub-linear in frame count (D56),
  proven by ``benchmarks._bench_frame_limit_ceiling`` (a 100,000-frame file *completes* under a peak
  RSS bound), and the **wall-clock** bound — ``job_timeout_seconds`` (Part 6 §5); and
* the advertised **frame-count** cap (``max_frames`` / ``FRAME_LIMIT_EXCEEDED``) is **not** a
  demonstrable per-job cap: it is surfaced by ``GET /v1/limits`` and described in ``config`` as
  parser-enforced, but no parser enforces it and the code exists in no source file. That gap is
  M37 review finding **F1** (``docs/security/REVIEW_M37.md``); it is reconciled in the docs and
  ticketed for enforcement, not demonstrated here as if it held.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from backend.db.base import utcnow
from backend.db.models import Job

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.config import Settings
    from backend.db import Repository

XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""


def _uploaded_keys(object_store: object) -> list[str]:
    """The filesystem store roots objects under a walkable directory (see test_uploads)."""
    root = getattr(object_store, "_root", None)
    if not isinstance(root, Path):  # pragma: no cover - only the filesystem store is used in-test
        return []
    uploads = root / "uploads"
    return [p.name for p in uploads.iterdir()] if uploads.is_dir() else []


# --- the upload byte cap: the oversize request exhausts only itself ------------------------------


def test_oversize_upload_fails_itself_and_a_normal_upload_still_succeeds(
    client: TestClient, settings: Settings
) -> None:
    # (a) The pathological request exhausts *its own* request: one byte past the cap is refused
    #     mid-stream with the bounded FILE_TOO_LARGE envelope — not an OOM, not a 500 — and leaves
    #     no orphaned bytes behind (the partial write is cleaned up).
    oversize = b"x" * (settings.max_upload_bytes + 1)
    bad = client.post("/v1/upload", files={"file": ("bomb.xyz", oversize)})
    assert bad.status_code == 413, bad.text
    assert bad.json()["error"]["code"] == "FILE_TOO_LARGE"
    object_store = client.app.state.object_store  # type: ignore[attr-defined]
    assert not _uploaded_keys(object_store)

    # (b) A concurrent well-formed upload is unaffected — the instance is not wedged by the refusal,
    #     and exactly one object (the good one) now exists.
    ok = client.post("/v1/upload", files={"file": ("mol.xyz", XYZ_SAMPLE)})
    assert ok.status_code == 201, ok.text
    assert len(_uploaded_keys(object_store)) == 1


# --- the concurrent-job cap: the excess submit is refused, running work untouched -----------------


def test_active_job_cap_refuses_only_the_excess_submit_and_capacity_recovers(
    build_client: Callable[..., TestClient], repository: Repository
) -> None:
    client = build_client(max_concurrent_jobs=2)

    # A well-formed job submitted while capacity is available runs to completion — unaffected.
    # (Under the inline queue a real submit completes synchronously, so it holds no slot after.)
    file_id = _upload_via(client)
    ok = client.post("/v1/inspect", json={"file_id": file_id})
    assert ok.status_code == 202, ok.text
    assert ok.json()["state"] == "completed"

    # Saturate the pool to the cap with two non-terminal jobs (the inline queue never leaves real
    # jobs running, so the saturated state is seeded directly — as test_limits_auth does).
    seeded = [uuid.uuid4().hex for _ in range(2)]
    for job_id in seeded:
        repository.add_job(Job(job_id=job_id, kind="convert", state="running", request={}))

    # The *excess* submit is refused with the bounded 429 — the cap fails the newcomer, never the
    # jobs already holding slots.
    refused = client.post("/v1/inspect", json={"file_id": file_id})
    assert refused.status_code == 429, refused.text
    error = refused.json()["error"]
    assert error["code"] == "TOO_MANY_ACTIVE_JOBS"
    assert error["details"]["max_concurrent_jobs"] == 2

    # The cap *bounds* concurrency, it does not permanently wedge the instance: freeing one slot
    # (a job reaches a terminal state) restores capacity for the next submit.
    repository.transition_job(seeded[0], "completed", finished_at=utcnow())
    recovered = client.post("/v1/inspect", json={"file_id": file_id})
    assert recovered.status_code == 202, recovered.text
    assert recovered.json()["state"] == "completed"


def test_cap_cannot_be_weakened_by_a_query_parameter(
    build_client: Callable[..., TestClient], repository: Repository
) -> None:
    """R9 follow-up regression: the concurrent-job cap must not be reachable from the wire.

    The v1.5 review's first pass wired the fan-out count through a
    ``Query(include_in_schema=False)`` parameter on the submit dependency; FastAPI still parses
    such a parameter from the query string, so ``?extra_jobs=0`` (or negative) would have
    weakened or defeated the cap the slice was meant to harden. The capacity knob now lives in a
    plain internal helper, so no query string can move the cap outcome on any submit endpoint.
    """
    client = build_client(max_concurrent_jobs=1)
    file_id = _upload_via(client)

    # Saturate the pool to the cap with one non-terminal job.
    repository.add_job(Job(job_id=uuid.uuid4().hex, kind="convert", state="running", request={}))

    # A client cannot smuggle a capacity knob through the query string of a submit that runs the
    # shared cap dependency — the values are ignored, the cap holds. ``/v1/inspect`` carries the
    # dependency exactly as ``/v1/convert`` and ``/v1/validate`` do; proving the dependency here
    # proves it on every endpoint that uses it.
    for query in ("extra_jobs=0", "extra_jobs=-100", "needed=0", "needed=-100"):
        resp = client.post(f"/v1/inspect?{query}", json={"file_id": file_id})
        assert resp.status_code == 429, f"/v1/inspect?{query} bypassed the cap: {resp.text}"
        assert resp.json()["error"]["code"] == "TOO_MANY_ACTIVE_JOBS"


def _upload_via(client: TestClient) -> str:
    resp = client.post("/v1/upload", files={"file": ("mol.xyz", XYZ_SAMPLE)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])
