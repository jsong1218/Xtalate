"""End-to-end lifecycle over a live Tier 1 compose stack (MASTER_SPEC M25 done-means; Part 6 §3).

This is the test the M25 compose-integration CI job runs *against a running `docker compose up`
stack* — real PostgreSQL, real MinIO, the RQ worker executing jobs asynchronously — rather than the
in-process TestClient. It reproduces the interactive worked example over HTTP: upload → convert
(pauses to ``awaiting_recovery`` with the spec's computed options) → resume with the §5 choices →
poll to ``completed`` → download the POSCAR. It is the same flow ``test_job_lifecycle.py`` proves
in-process, but across the process/queue boundary the unit suite cannot exercise, so a broken worker
image, a queue misconfiguration, or a migration that never ran is caught here and only here.

Skipped unless ``XTALATE_LIVE_BASE_URL`` names the stack (e.g. ``http://localhost:8000``), so the
ordinary PR gate — which has no stack — never collects a failing live call; the CI job sets it after
``docker compose up`` reports the backend healthy. Marked ``integration`` so it can also be selected
explicitly with ``-m integration``.
"""

from __future__ import annotations

import os
import time
from typing import Any, cast

import httpx
import pytest

BASE_URL = os.environ.get("XTALATE_LIVE_BASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not BASE_URL, reason="set XTALATE_LIVE_BASE_URL to run against a live compose stack"
    ),
]

# Two frames + a POSCAR target ⇒ both recovery scenarios of the Part 4 §5 example fire
# (frame_selection, then missing_lattice) — the richest single path through the pipeline.
MULTIFRAME_XYZ = b"""3
frame 1
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
3
frame 2
O  0.100  0.000  0.000
H  0.857  0.586  0.000
H -0.657  0.586  0.000
"""

WORKED_EXAMPLE_CHOICES = {
    "frame_selection": {"choice": "last"},
    "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
}

_TERMINAL = {"completed", "failed", "cancelled", "expired"}


def _poll_until(
    client: httpx.Client, job_id: str, states: set[str], *, timeout: float = 60.0
) -> dict[str, Any]:
    """Poll ``GET /v1/jobs/{id}`` until its state is in ``states`` (or terminal), or time out.

    Tier 1 runs jobs on the RQ worker, so a submit/resume returns before the work is done — the
    caller must poll. Returns the final job envelope.
    """
    deadline = time.monotonic() + timeout
    while True:
        env = cast(dict[str, Any], client.get(f"/v1/jobs/{job_id}").raise_for_status().json())
        if env["state"] in states or env["state"] in _TERMINAL:
            return env
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} stuck in {env['state']!r} after {timeout}s")
        time.sleep(0.5)


def test_ready_then_interactive_convert_and_download() -> None:
    """The full loop across the real queue: ready → pause → resume → complete → download bytes."""
    assert BASE_URL is not None  # guaranteed by the module-level skipif; narrows the type
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Readiness: DB + object store answer (the M21 done-means, now with a real backend).
        health = client.get("/v1/health", params={"ready": "true"})
        assert health.status_code == 200, health.text
        assert health.json()["status"] == "ok"

        # 2. Upload the two-frame input.
        up = client.post("/v1/upload", files={"file": ("traj.xyz", MULTIFRAME_XYZ)})
        assert up.status_code == 201, up.text
        file_id = up.json()["file_id"]

        # 3. Convert asking for interactive recovery — it pauses with exactly the §5 scenarios.
        submitted = client.post(
            "/v1/convert",
            json={
                "file_id": file_id,
                "target_format_id": "poscar",
                "options": {"allow_recovery": True},
            },
        )
        assert submitted.status_code in (200, 201, 202), submitted.text
        job_id = submitted.json()["job_id"]

        paused = _poll_until(client, job_id, {"awaiting_recovery"})
        assert paused["state"] == "awaiting_recovery", paused
        scenarios = {s["scenario"] for s in paused["awaiting_recovery"]["unresolved_scenarios"]}
        assert scenarios == {"frame_selection", "missing_lattice"}

        # 4. Resume with the choices; the worker finishes the conversion.
        resume = client.post(
            f"/v1/jobs/{job_id}/recovery", json={"choices": WORKED_EXAMPLE_CHOICES}
        )
        assert resume.status_code == 200, resume.text
        done = _poll_until(client, job_id, {"completed"})
        assert done["state"] == "completed", done

        result = done["result"]
        assert result["conversion_report"]["status"] == "completed"
        # The §5 choices are recorded as interactively supplied (origin "user"), never silent.
        origins = {a["origin"] for a in result["conversion_report"]["assumptions"]}
        assert origins == {"user"}
        conversion_id = result["conversion_id"]

        # 5. Download the converted POSCAR through the API and confirm it is real output bytes.
        dl = client.get(f"/v1/download/{conversion_id}")
        assert dl.status_code == 200, dl.text
        assert dl.content, "empty download"

        # 6. The durable record serves both reports back verbatim (reports-outlive-bytes surface).
        record = client.get(f"/v1/conversions/{conversion_id}")
        assert record.status_code == 200, record.text
        assert record.json()["conversion_report"]["status"] == "completed"
