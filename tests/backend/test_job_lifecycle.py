"""The job-lifecycle suite — every Part 6 §3.2 transition *driven*, plus the interactive worked
example (M23 slice 5: the plan's named deliverable #5 and the version's done-means).

Three things this suite proves that the endpoint tests (``test_jobs_api.py``) and the pure-table
test (``jobs/test_state_machine.py``) do not, together:

1. **Every legal edge of the state diagram persists through the real seam.** ``test_state_machine``
   proves the transition *predicate* matches the diagram; here each legal edge is actually taken
   through ``Repository.transition_job`` — the one door every state write goes through — and re-read
   from the store, and an illegal edge is shown to leave the row untouched (no corrupt persisted
   state).
2. **Cancellation from *each* non-terminal state.** Under the Tier 0 inline queue a submitted job is
   already terminal, so ``queued`` and ``running`` are never observable over HTTP; a no-op queue and
   the transition seam put a job into each non-terminal state so the cancel endpoint is exercised
   from all three (``queued``/``running``/``awaiting_recovery``), not just the paused one.
3. **The Part 4 §5 worked example, interactively over HTTP.** Submitting without presets pauses with
   exactly the spec's two scenarios and computed options; resuming with the choices completes; and
   the resulting Conversion Report is byte-equivalent — bar the random id, the timestamp, and the
   ``user``/``preset`` origin — to the preset-driven run of the same input. That byte-equivalence is
   what "done" means for this version: the interactive path is the preset path with the choices
   arriving over the wire, not a second conversion implementation.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.db import Repository, utcnow
from backend.db.models import Job
from backend.deps import get_job_queue
from backend.jobs import state_machine as sm

XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""

# Two frames: a POSCAR target (single-frame, periodic) needs both a frame picked (frame_selection)
# and a lattice supplied (missing_lattice) — exactly the two scenarios of the Part 4 §5 example.
MULTIFRAME_XYZ_SAMPLE = b"""3
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

# The §5 choices, in one place so the preset run and the interactive resume supply them identically.
WORKED_EXAMPLE_CHOICES = {
    "frame_selection": {"choice": "last"},
    "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
}


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


# --- every legal edge, driven through the persistence seam ---------------------------------------


def _job_in_state(repository: Repository, state: str) -> str:
    """Create a fresh job and drive it — through legal edges only — to a non-terminal ``state``.

    Terminal states have no outgoing edges, so only ``queued``/``running``/``awaiting_recovery`` are
    ever transition *sources*; those are the only states this builder is asked for.
    """
    job_id = uuid.uuid4().hex
    repository.add_job(Job(job_id=job_id, kind="convert", state="queued", request={"file_id": "x"}))
    if state == "queued":
        return job_id
    repository.transition_job(job_id, "running", started_at=utcnow())
    if state == "running":
        return job_id
    if state == "awaiting_recovery":
        repository.transition_job(
            job_id,
            "awaiting_recovery",
            expires_at=utcnow() + timedelta(hours=1),
            recovery={"draft_report": {}, "unresolved_scenarios": []},
        )
        return job_id
    raise AssertionError(f"{state!r} is not a non-terminal transition source")


_LEGAL_EDGES = sorted(
    (source, target) for source, targets in sm.LEGAL_TRANSITIONS.items() for target in targets
)


@pytest.mark.parametrize(("source", "target"), _LEGAL_EDGES)
def test_every_legal_edge_persists_through_the_repository(
    repository: Repository, source: str, target: str
) -> None:
    # Each edge of the Part 6 §3.2 diagram, taken through the seam every state write goes through
    # and re-read from the store — the driven counterpart to the pure-table test.
    job_id = _job_in_state(repository, source)
    updated = repository.transition_job(job_id, target)
    assert updated is not None and updated.state == target
    reloaded = repository.get_job(job_id)
    assert reloaded is not None
    assert reloaded.state == target  # persisted, not just returned


def test_illegal_edge_is_refused_and_leaves_the_row_unchanged(repository: Repository) -> None:
    # An illegal transition raises at the repository and writes nothing — there is no path to a
    # corrupt persisted state (the invariant the validated seam exists to guarantee).
    job_id = _job_in_state(repository, "running")
    repository.transition_job(job_id, "completed", finished_at=utcnow())
    with pytest.raises(sm.InvalidTransition):
        repository.transition_job(job_id, "running")  # completed is terminal
    reloaded = repository.get_job(job_id)
    assert reloaded is not None
    assert reloaded.state == "completed"


# --- cancellation from each non-terminal state ---------------------------------------------------


class _NoopQueue:
    """A queue that accepts the enqueue but never runs the job, so a submitted convert stays in
    ``queued`` for a test to observe and drive — the inline queue would complete it at once."""

    def enqueue(self, job_id: str) -> None:  # noqa: D401 - Protocol method
        return None


def _hold_jobs_queued(client: TestClient) -> None:
    """Override the app's queue with a no-op so submitted jobs stay non-terminal."""
    cast(FastAPI, client.app).dependency_overrides[get_job_queue] = _NoopQueue


@pytest.mark.parametrize("state", ["queued", "running", "awaiting_recovery"])
def test_cancel_from_each_non_terminal_state(
    client: TestClient, repository: Repository, state: str
) -> None:
    # Cancellation is legal from every non-terminal state (Part 6 §3.2). The no-op queue leaves the
    # convert ``queued``; the transition seam drives it on to ``running``/``awaiting_recovery`` —
    # states the inline queue never leaves observable — and the cancel endpoint terminates each.
    _hold_jobs_queued(client)
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    submitted = client.post(
        "/v1/convert", json={"file_id": file_id, "target_format_id": "poscar"}
    ).json()
    job_id = submitted["job_id"]
    assert submitted["state"] == "queued"  # the no-op queue left it unrun

    if state in ("running", "awaiting_recovery"):
        repository.transition_job(job_id, "running", started_at=utcnow())
    if state == "awaiting_recovery":
        repository.transition_job(
            job_id,
            "awaiting_recovery",
            expires_at=utcnow() + timedelta(hours=1),
            recovery={"draft_report": {}, "unresolved_scenarios": []},
        )
    assert client.get(f"/v1/jobs/{job_id}").json()["state"] == state

    resp = client.post(f"/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 200, resp.text
    env = resp.json()
    assert env["state"] == "cancelled"
    assert env["finished_at"] is not None
    assert env["awaiting_recovery"] is None
    assert env["result"] is None
    assert env["error"] is None  # abandonment: not a failure, not a refusal
    # No Conversion Report is written for a cancel from any state (Part 6 §3.2, §5).
    assert list(repository.get_reports_for_job(job_id)) == []


# --- the interactive worked example (done-means) -------------------------------------------------


def _canonicalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Drop the fields that legitimately differ between two runs of the same conversion, so the
    scientific content can be compared for equality: the random ``report_id``, the wall-clock
    ``created_at``, and each Assumption's ``origin`` (``user`` for an interactive resume, ``preset``
    for a preset-driven run — the *provenance* of the identical choice, not the choice itself)."""
    norm = copy.deepcopy(report)
    norm.pop("report_id", None)
    norm.pop("created_at", None)
    for assumption in norm.get("assumptions") or []:
        assumption.pop("origin", None)
    return norm


def _preset_report(client: TestClient) -> dict[str, Any]:
    """Convert the two-frame input with both choices supplied as presets — completes, no pause."""
    file_id = _upload(client, MULTIFRAME_XYZ_SAMPLE, "traj.xyz")
    env = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"recovery_choices": WORKED_EXAMPLE_CHOICES},
        },
    ).json()
    assert env["state"] == "completed", env
    return cast("dict[str, Any]", env["result"]["conversion_report"])


def _interactive_report(client: TestClient) -> dict[str, Any]:
    """Convert the same input interactively: pause with the two scenarios, resume with choices."""
    file_id = _upload(client, MULTIFRAME_XYZ_SAMPLE, "traj.xyz")
    paused = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"allow_recovery": True},
        },
    ).json()
    assert paused["state"] == "awaiting_recovery", paused
    block = paused["awaiting_recovery"]
    scenarios = {s["scenario"] for s in block["unresolved_scenarios"]}
    assert scenarios == {"frame_selection", "missing_lattice"}  # exactly §5's two scenarios
    lattice = next(s for s in block["unresolved_scenarios"] if s["scenario"] == "missing_lattice")
    offered = {o["choice"] for o in lattice["options"]}
    assert "non_periodic" not in offered  # POSCAR is periodic-only (§3.3)

    resumed = client.post(
        f"/v1/jobs/{paused['job_id']}/recovery", json={"choices": WORKED_EXAMPLE_CHOICES}
    ).json()
    assert resumed["state"] == "completed", resumed
    return cast("dict[str, Any]", resumed["result"]["conversion_report"])


def test_interactive_worked_example_matches_the_preset_run(client: TestClient) -> None:
    # The version's done-means, over HTTP: the interactive resume and the preset run of the same
    # input produce the same Conversion Report — the interactive path is the preset path with the
    # choices arriving over the wire, differing only in the provenance recorded for each choice.
    interactive = _interactive_report(client)
    preset = _preset_report(client)

    assert interactive["status"] == preset["status"] == "completed"
    interactive_origins = {a["scenario"]: a["origin"] for a in interactive["assumptions"]}
    preset_origins = {a["scenario"]: a["origin"] for a in preset["assumptions"]}
    assert set(interactive_origins.values()) == {"user"}  # recorded as interactively supplied
    assert set(preset_origins.values()) == {"preset"}  # recorded as preset-supplied
    assert _canonicalize_report(interactive) == _canonicalize_report(preset)
