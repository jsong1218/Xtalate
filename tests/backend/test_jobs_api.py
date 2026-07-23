"""The job endpoints over HTTP — submit → poll → retrieve, the M22 done-means end to end.

Uses the shared ``client`` fixture (an app over deterministic temp-path settings, inline queue by
default), so these are genuine HTTP round-trips through the real error envelope and middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository

POSCAR_SAMPLE = b"""NaCl primitive test
1.0
  5.640  0.000  0.000
  0.000  5.640  0.000
  0.000  0.000  5.640
Na Cl
1 1
Direct
  0.00 0.00 0.00
  0.50 0.50 0.50
"""

XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""

# Two frames: a POSCAR target (single-frame, periodic) needs both a frame picked (frame_selection)
# and a lattice supplied (missing_lattice) — a two-scenario pause, for the partial-resume path.
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


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["size_bytes"] == len(content)
    assert body["sha256"]
    return str(body["file_id"])


# --- upload -------------------------------------------------------------------------------------


def test_upload_returns_a_handle(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    assert file_id


# --- inspect ------------------------------------------------------------------------------------


def test_inspect_completes_and_embeds_the_discovery_report(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post("/v1/inspect", json={"file_id": file_id})
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["kind"] == "inspect"
    # Inline queue: the job is already completed by the time submit returns.
    assert env["state"] == "completed"
    assert env["result"]["discovery_report"]["format"]["format_id"] == "xyz"


def test_inspect_is_idempotent_per_file_and_override(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    first = client.post("/v1/inspect", json={"file_id": file_id}).json()
    second = client.post("/v1/inspect", json={"file_id": file_id}).json()
    assert first["job_id"] == second["job_id"]  # same key → same job, no new work

    # A different override is a different key → a different job (always real work).
    override = client.post(
        "/v1/inspect", json={"file_id": file_id, "format_override": "extxyz"}
    ).json()
    assert override["job_id"] != first["job_id"]


def test_inspect_unknown_file_is_404_envelope(client: TestClient) -> None:
    resp = client.post("/v1/inspect", json={"file_id": "nope"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FILE_NOT_FOUND"


# --- convert ------------------------------------------------------------------------------------


def test_convert_with_recovery_preset_completes_end_to_end(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {
                "recovery_choices": {
                    "missing_lattice": {
                        "choice": "bounding_box",
                        "parameters": {"padding_ang": 5.0},
                    }
                }
            },
        },
    )
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["state"] == "completed"
    result = env["result"]
    assert result["conversion_report"]["status"] == "completed"
    assert result["conversion_report"]["supplied"]  # the fabricated lattice, reported (P1/P4)
    assert result["validation_report"] is not None
    assert result["download"]["available"] is True
    assert result["download"]["filename"] == "POSCAR"


def test_convert_refusal_is_a_completed_job_at_200(client: TestClient) -> None:
    # XYZ → POSCAR with no recovery preset refuses; the refusal is a *completed* job, HTTP 202/200,
    # its refusal report the result — never an HTTP error (Part 6 §1, the honesty-defining rule).
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "poscar"})
    assert resp.status_code == 202
    env = resp.json()
    assert env["state"] == "completed"
    assert env["error"] is None
    assert env["result"]["conversion_report"]["status"] == "refused"
    assert env["result"]["download"]["available"] is False


# --- interactive recovery: the pause (M23 slice 1) ----------------------------------------------


def test_convert_without_allow_recovery_still_refuses(client: TestClient) -> None:
    # The M22 contract is unchanged when interactive recovery is not opted into: an unresolved
    # scenario is a *completed* refused job, never a pause the client must poll (Appendix A / CLI).
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "poscar"}).json()
    assert env["state"] == "completed"
    assert env["result"]["conversion_report"]["status"] == "refused"
    assert env["awaiting_recovery"] is None


def test_convert_allow_recovery_pauses_to_awaiting_recovery(client: TestClient) -> None:
    # XYZ → POSCAR needs a lattice the source lacks; with allow_recovery the job *pauses* and asks,
    # instead of refusing (Part 6 §3.2). The block carries the pre-flight draft and the computed
    # option lists the future UI renders from.
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"allow_recovery": True},
        },
    )
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["state"] == "awaiting_recovery"
    assert env["result"] is None
    assert env["error"] is None
    assert env["progress"]["phase"] == "recovery"
    assert env["expires_at"] is not None  # a TTL horizon is stamped on the pause

    block = env["awaiting_recovery"]
    assert block is not None
    draft = block["draft_report"]
    assert draft["stage"] == "preflight"
    assert draft["status"] == "awaiting_recovery"

    scenarios = {s["scenario"]: s for s in block["unresolved_scenarios"]}
    assert "missing_lattice" in scenarios
    codes = [o["choice"] for o in scenarios["missing_lattice"]["options"]]
    # The option list is computed, honest, pair-specific: POSCAR is periodic-only, so `non_periodic`
    # is absent — never offered then refused (Part 4 §3.3, P5).
    assert "non_periodic" not in codes
    assert {"manual_input", "bounding_box", "upload_reference"} <= set(codes)
    # Choices that take parameters advertise the keys the Recovery Engine consumes.
    by_choice = {o["choice"]: o for o in scenarios["missing_lattice"]["options"]}
    assert "padding_ang" in by_choice["bounding_box"]["parameters_schema"]
    assert "lattice" in by_choice["manual_input"]["parameters_schema"]


def test_paused_job_is_served_back_verbatim_on_poll(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    submitted = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"allow_recovery": True},
        },
    ).json()
    job_id = submitted["job_id"]
    polled = client.get(f"/v1/jobs/{job_id}").json()
    assert polled["state"] == "awaiting_recovery"
    # The persisted block is served back on every poll, unchanged (the UI polls, then decides).
    assert polled["awaiting_recovery"] == submitted["awaiting_recovery"]


def test_convert_with_partial_preset_pauses_for_the_rest(client: TestClient) -> None:
    # A single-frame XYZ → POSCAR needs only the lattice, so a complete preset *completes* — even
    # with allow_recovery set. The interactive contract: a preset that fully resolves never pauses.
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    env = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {
                "allow_recovery": True,
                "recovery_choices": {
                    "missing_lattice": {
                        "choice": "bounding_box",
                        "parameters": {"padding_ang": 5.0},
                    }
                },
            },
        },
    ).json()
    assert env["state"] == "completed"
    assert env["awaiting_recovery"] is None
    assert env["result"]["conversion_report"]["status"] == "completed"


# --- interactive recovery: resume (M23 slice 2) -------------------------------------------------


def _pause_xyz_to_poscar(client: TestClient, content: bytes = XYZ_SAMPLE) -> str:
    """Submit an allow_recovery XYZ → POSCAR convert that pauses; return its job_id."""
    file_id = _upload(client, content, "mol.xyz")
    env = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"allow_recovery": True},
        },
    ).json()
    assert env["state"] == "awaiting_recovery", env
    return str(env["job_id"])


def test_resume_unknown_job_is_404(client: TestClient) -> None:
    resp = client.post("/v1/jobs/nope/recovery", json={"choices": {}})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_resume_non_awaiting_job_is_409_with_state(client: TestClient) -> None:
    # A completed inspect job is not paused: resume is a 409 that names the current state, so a
    # client that raced the pause window learns why (Part 6 §3.2 endpoint table).
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    job_id = client.post("/v1/inspect", json={"file_id": file_id}).json()["job_id"]
    resp = client.post(f"/v1/jobs/{job_id}/recovery", json={"choices": {}})
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "JOB_NOT_AWAITING_RECOVERY"
    assert body["details"]["state"] == "completed"


def test_resume_unoffered_choice_is_422_with_offered_choices(client: TestClient) -> None:
    # POSCAR is periodic-only, so `non_periodic` was never offered for missing_lattice — picking it
    # is refused with the actually-offered choices, never coerced (Part 4 §3.3, P5).
    job_id = _pause_xyz_to_poscar(client)
    resp = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={"choices": {"missing_lattice": {"choice": "non_periodic"}}},
    )
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "INVALID_RECOVERY_CHOICE"
    assert body["details"]["scenario"] == "missing_lattice"
    assert "non_periodic" not in body["details"]["offered_choices"]
    assert "bounding_box" in body["details"]["offered_choices"]
    # The job is untouched by a rejected resume — still paused, still answerable.
    assert client.get(f"/v1/jobs/{job_id}").json()["state"] == "awaiting_recovery"


def test_resume_unknown_scenario_is_422(client: TestClient) -> None:
    job_id = _pause_xyz_to_poscar(client)
    resp = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={"choices": {"missing_masses": {"choice": "manual_input"}}},
    )
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "INVALID_RECOVERY_CHOICE"
    assert body["details"]["scenario"] == "missing_masses"
    assert body["details"]["offered_choices"] == []


def test_resume_with_valid_choice_completes_as_user_origin(client: TestClient) -> None:
    # The happy path: pause, answer the one open scenario, the job resumes and completes — and the
    # applied Assumption is recorded origin="user" (interactive), not "preset" (Part 4 §2).
    job_id = _pause_xyz_to_poscar(client)
    resp = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={
            "choices": {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
            }
        },
    )
    assert resp.status_code == 200, resp.text
    env = resp.json()
    assert env["state"] == "completed"
    assert env["awaiting_recovery"] is None  # the paused block is cleared on resume
    report = env["result"]["conversion_report"]
    assert report["status"] == "completed"
    assert report["supplied"]  # the fabricated lattice, reported (P1/P4)
    assumptions = {a["scenario"]: a for a in report["assumptions"]}
    assert assumptions["missing_lattice"]["origin"] == "user"


def test_partial_resume_pauses_again_for_the_rest(client: TestClient) -> None:
    # A two-scenario pause (frame_selection + missing_lattice): answering only one resumes the job,
    # which pauses again for the still-open scenario — then a second resume completes it. Choices
    # accumulate across resumes (Part 6 §3.2).
    job_id = _pause_xyz_to_poscar(client, MULTIFRAME_XYZ_SAMPLE)
    block = client.get(f"/v1/jobs/{job_id}").json()["awaiting_recovery"]
    open_scenarios = {s["scenario"] for s in block["unresolved_scenarios"]}
    assert {"frame_selection", "missing_lattice"} <= open_scenarios

    # Answer only the lattice: the job resumes, converts, and pauses again — now only for the frame.
    first = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={
            "choices": {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
            }
        },
    ).json()
    assert first["state"] == "awaiting_recovery"
    still_open = {s["scenario"] for s in first["awaiting_recovery"]["unresolved_scenarios"]}
    assert still_open == {"frame_selection"}  # the answered scenario is gone; the other remains

    # Answer the frame: the accumulated choices now fully resolve, so the job completes.
    second = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={"choices": {"frame_selection": {"choice": "first"}}},
    ).json()
    assert second["state"] == "completed"
    report = second["result"]["conversion_report"]
    assert report["status"] == "completed"
    origins = {a["scenario"]: a["origin"] for a in report["assumptions"]}
    assert origins["frame_selection"] == "user"
    assert origins["missing_lattice"] == "user"


# --- interactive recovery: expiry (M23 slice 3) ------------------------------------------------


def _expire_all(repository: Repository, settings: Settings) -> list[str]:
    """Drive the expiry sweep with the clock a day ahead — past every live pause's TTL horizon."""
    from datetime import timedelta

    from backend.db import utcnow
    from backend.jobs.expiry import sweep_expired

    return sweep_expired(repository, settings, now=utcnow() + timedelta(days=1))


def test_expired_pause_resolves_to_a_refused_conversion(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # The bright line (Part 4 §3.2): a pause that times out resolves to a *refused* conversion —
    # refusal.code == RECOVERY_REQUIRED — never a silently applied default. The sweep is clock-
    # controlled (an injected `now`), so the transition is deterministic, not wall-clock-dependent.
    job_id = _pause_xyz_to_poscar(client)
    assert _expire_all(repository, settings) == [job_id]

    job = repository.get_job(job_id)
    assert job is not None
    assert job.state == "expired"
    assert job.finished_at is not None
    assert job.recovery is None  # the paused block is cleared once the job leaves the state
    assert job.error is not None
    assert job.error["code"] == "RECOVERY_REQUIRED"

    reports = repository.get_reports_for_job(job_id)
    conversion_report = next(r for r in reports if r.kind == "conversion")
    body = conversion_report.body
    assert body["stage"] == "final"
    assert body["status"] == "refused"
    assert body["refusal"]["code"] == "RECOVERY_REQUIRED"
    # The refusal lists the still-unanswered scenarios as bare option codes (the Part 4 §4 shape),
    # de-enriched from the pause's ``{choice, parameters_schema}`` block — nothing added or dropped.
    unresolved = {s["scenario"]: s for s in body["refusal"]["unresolved_scenarios"]}
    assert "missing_lattice" in unresolved
    options = unresolved["missing_lattice"]["options"]
    assert all(isinstance(o, str) for o in options)
    assert "bounding_box" in options and "non_periodic" not in options

    # An expired pause produces no output file — a refusal, not a fabricated result (Part 6 §3.2).
    assert conversion_report.conversion_id is not None
    conversion = repository.get_conversion(conversion_report.conversion_id)
    assert conversion is not None
    assert conversion.conversion_status == "refused"
    assert conversion.output_available is False
    assert conversion.output_storage_key is None


def test_expired_job_poll_surfaces_the_error_envelope(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # Part 7 §2.4: an expired job renders its error envelope (worded as a refusal for want of a
    # choice). The poll carries error.code == RECOVERY_REQUIRED, no result, and no stale block.
    job_id = _pause_xyz_to_poscar(client)
    _expire_all(repository, settings)
    env = client.get(f"/v1/jobs/{job_id}").json()
    assert env["state"] == "expired"
    assert env["error"]["code"] == "RECOVERY_REQUIRED"
    assert env["result"] is None
    assert env["awaiting_recovery"] is None


def test_resume_after_expiry_is_409_naming_expired(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # A resume that loses the race to the deadline is a 409 that names the ``expired`` state, so a
    # client learns the pause is gone rather than resuming a job whose bytes may already be gone.
    job_id = _pause_xyz_to_poscar(client)
    _expire_all(repository, settings)
    resp = client.post(
        f"/v1/jobs/{job_id}/recovery",
        json={
            "choices": {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
            }
        },
    )
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "JOB_NOT_AWAITING_RECOVERY"
    assert body["details"]["state"] == "expired"


def test_poll_lazily_expires_an_overdue_pause(client: TestClient, repository: Repository) -> None:
    # Tier 0 has no background sweeper: a poll of a paused job past its TTL resolves it in place.
    # We push the horizon into the past (as the clock would, TTL minutes on) and poll with no
    # explicit sweep — the poll itself must expire it (the ``expire_if_due`` lazy path).
    from datetime import timedelta

    from backend.db import utcnow
    from backend.db.models import Job

    job_id = _pause_xyz_to_poscar(client)
    with repository._session_factory.begin() as session:
        paused = session.get(Job, job_id)
        assert paused is not None
        paused.expires_at = utcnow() - timedelta(hours=1)

    env = client.get(f"/v1/jobs/{job_id}").json()
    assert env["state"] == "expired"
    assert env["error"]["code"] == "RECOVERY_REQUIRED"


def test_poll_leaves_a_not_yet_due_pause_awaiting(client: TestClient) -> None:
    # A long-poll of a live (not-yet-due) pause holds and returns it still ``awaiting_recovery`` —
    # the lazy expiry check inside the wait loop is a no-op until the horizon actually passes.
    job_id = _pause_xyz_to_poscar(client)
    env = client.get(f"/v1/jobs/{job_id}", params={"wait": 0.2}).json()
    assert env["state"] == "awaiting_recovery"
    assert env["awaiting_recovery"] is not None


# --- interactive recovery: cancellation (M23 slice 4) ------------------------------------------


def test_cancel_unknown_job_is_404(client: TestClient) -> None:
    resp = client.post("/v1/jobs/nope/cancel")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_cancel_awaiting_recovery_terminates_with_no_report_or_output(
    client: TestClient, repository: Repository
) -> None:
    # Cancelling a paused convert is an abandonment, not a refusal: the job goes terminal
    # ``cancelled`` with no output file and no Conversion Report, and the envelope carries neither a
    # result nor an error body — only the state (Part 6 §3.2, §5).
    job_id = _pause_xyz_to_poscar(client)
    resp = client.post(f"/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 200, resp.text
    env = resp.json()
    assert env["state"] == "cancelled"
    assert env["finished_at"] is not None
    assert env["awaiting_recovery"] is None  # the paused block is cleared on the terminal edge
    assert env["result"] is None
    assert env["error"] is None  # not a failure, not a refusal — just abandoned

    # No Conversion Report and no conversion row: a cancel records only that the job was stopped.
    assert list(repository.get_reports_for_job(job_id)) == []
    with repository._session_factory() as session:
        from sqlalchemy import select

        from backend.db.models import Conversion

        rows = session.scalars(select(Conversion).where(Conversion.job_id == job_id)).all()
        assert list(rows) == []


def test_cancel_is_idempotent(client: TestClient) -> None:
    # A retried cancel of an already-cancelled job is a 200 no-op, never a 409 (Part 6 §5).
    job_id = _pause_xyz_to_poscar(client)
    first = client.post(f"/v1/jobs/{job_id}/cancel")
    assert first.status_code == 200
    assert first.json()["state"] == "cancelled"
    second = client.post(f"/v1/jobs/{job_id}/cancel")
    assert second.status_code == 200
    assert second.json()["state"] == "cancelled"


def test_cancel_completed_job_is_409_already_terminal(client: TestClient) -> None:
    # A job that already reached a non-cancelled terminal state cannot be cancelled: its outcome is
    # recorded and must not be overwritten (409 JOB_ALREADY_TERMINAL naming the state).
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    job_id = client.post("/v1/inspect", json={"file_id": file_id}).json()["job_id"]
    resp = client.post(f"/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "JOB_ALREADY_TERMINAL"
    assert body["details"]["state"] == "completed"


def test_cancel_after_expiry_is_409_naming_expired(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # A cancel that loses the race to the TTL deadline finds the pause already expired-to-refused:
    # expire_if_due runs first, so the cancel is a 409 naming ``expired``, never an erasure of the
    # recorded refusal (Part 4 §3.2's bright line survives a late cancel).
    job_id = _pause_xyz_to_poscar(client)
    _expire_all(repository, settings)
    resp = client.post(f"/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "JOB_ALREADY_TERMINAL"
    assert body["details"]["state"] == "expired"


def test_convert_with_loss_reports_removed_fields(client: TestClient) -> None:
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}).json()
    assert env["state"] == "completed"
    assert env["result"]["conversion_report"]["status"] == "completed"
    # POSCAR → XYZ drops the lattice; the loss is enumerated, never silent (P1).
    assert env["result"]["conversion_report"]["removed"]


def test_convert_unknown_target_is_422_envelope(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "not_a_format"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNKNOWN_FORMAT"


# --- validate (re-threshold) --------------------------------------------------------------------


def test_validate_rethresholds_a_stored_conversion(client: TestClient) -> None:
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    convert = client.post(
        "/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}
    ).json()
    conversion_id = convert["result"]["conversion_id"]

    resp = client.post(
        "/v1/validate",
        json={"conversion_id": conversion_id, "tolerance_profile": "loose"},
    )
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["kind"] == "validate"
    assert env["state"] == "completed"
    assert env["result"]["validation_report"] is not None


def test_validate_unknown_conversion_is_404_envelope(client: TestClient) -> None:
    resp = client.post("/v1/validate", json={"conversion_id": "nope"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSION_NOT_FOUND"


# --- poll ---------------------------------------------------------------------------------------


def test_get_job_returns_the_same_envelope(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    submitted = client.post("/v1/inspect", json={"file_id": file_id}).json()
    polled = client.get(f"/v1/jobs/{submitted['job_id']}")
    assert polled.status_code == 200
    assert polled.json()["job_id"] == submitted["job_id"]
    assert polled.json()["result"]["discovery_report"]


def test_long_poll_returns_terminal_immediately(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    job_id = client.post("/v1/inspect", json={"file_id": file_id}).json()["job_id"]
    # Already completed (inline) → ?wait= returns at once, well under the requested window.
    polled = client.get(f"/v1/jobs/{job_id}", params={"wait": 5})
    assert polled.status_code == 200
    assert polled.json()["state"] == "completed"


def test_get_unknown_job_is_404_envelope(client: TestClient) -> None:
    resp = client.get("/v1/jobs/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_crashed_worker_surfaces_as_failed_over_http(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The done-means end to end: a worker that crashes mid-job yields a `failed` job carrying a
    # structured error envelope — never a stuck `running` row, never a raw 500 to the client.
    from backend.jobs import runner

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(runner, "_dispatch", _boom)

    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    env = client.post("/v1/convert", json={"file_id": file_id, "target_format_id": "xyz"}).json()
    assert env["state"] == "failed"
    assert env["error"]["code"] == "INTERNAL_ERROR"

    polled = client.get(f"/v1/jobs/{env['job_id']}").json()
    assert polled["state"] == "failed"  # the poll agrees; the row is terminal, not stuck
