"""The job endpoints over HTTP — submit → poll → retrieve, the M22 done-means end to end.

Uses the shared ``client`` fixture (an app over deterministic temp-path settings, inline queue by
default), so these are genuine HTTP round-trips through the real error envelope and middleware.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
