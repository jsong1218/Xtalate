"""POST /v1/convert with options.dry_run — preflight-only job (QoL Q4)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.db.repository import Repository
from tests.backend.test_repair_api import CELL_LESS_XYZ, CO_IN_CELL, _convert, _upload

# 4 frames x ~40 bytes: under the test settings' 1234-byte upload cap; multi-frame so the
# streaming-eligible xyz -> extxyz pair would stream if the dry-run gate were missing.
FOUR_FRAMES = b"".join(f"2\nf{i}\nO {i}.0 0 0\nH {i}.0 1 0\n".encode() for i in range(4))


def _job(client: TestClient, env: dict[str, Any]) -> dict[str, Any]:
    resp = client.get(f"/v1/jobs/{env['job_id']}")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_dry_run_completes_with_a_draft_report_and_no_download(
    client: TestClient, repository: Repository
) -> None:
    before = len(repository.list_conversions(limit=100))
    file_id = _upload(client, CO_IN_CELL, "co.extxyz")
    env = _job(client, _convert(client, file_id, "poscar", {"dry_run": True}))
    assert env["state"] == "completed"
    result = env["result"]
    assert result["conversion_report"]["stage"] == "preflight"
    assert result["conversion_report"]["status"] == "completed"
    assert result["conversion_id"] is None
    assert result["validation_report"] is None
    assert result["download"] is None
    # No Conversion row: nothing to download, nothing in history.
    assert len(repository.list_conversions(limit=100)) == before
    assert client.get("/v1/history").json()["items"] == []


def test_dry_run_on_a_streaming_eligible_pair_still_writes_nothing(
    client: TestClient, repository: Repository
) -> None:
    file_id = _upload(client, FOUR_FRAMES, "t.xyz")
    env = _job(client, _convert(client, file_id, "extxyz", {"dry_run": True}))
    assert env["state"] == "completed"
    assert env["result"]["conversion_report"]["stage"] == "preflight"
    assert env["result"]["conversion_id"] is None
    assert env["result"]["download"] is None
    assert repository.list_conversions(limit=100) == []


def test_dry_run_that_needs_recovery_completes_and_never_pauses(client: TestClient) -> None:
    file_id = _upload(client, CELL_LESS_XYZ, "x.xyz")
    env = _job(
        client, _convert(client, file_id, "poscar", {"dry_run": True, "allow_recovery": True})
    )
    assert env["state"] == "completed"
    report = env["result"]["conversion_report"]
    assert report["stage"] == "preflight"
    assert report["status"] == "awaiting_recovery"
    scenarios = {s["scenario"] for s in report["refusal"]["unresolved_scenarios"]}
    assert "missing_lattice" in scenarios


def test_default_false_still_runs_for_real(client: TestClient) -> None:
    file_id = _upload(client, CO_IN_CELL, "co.extxyz")
    env = _job(client, _convert(client, file_id, "poscar", {}))
    assert env["result"]["conversion_report"]["stage"] == "final"
    assert env["result"]["conversion_id"] is not None
    assert env["result"]["download"]["available"] is True


def test_dry_run_applies_repairs_strictly(client: TestClient) -> None:
    file_id = _upload(client, FOUR_FRAMES, "t.xyz")
    env = _job(
        client,
        _convert(
            client,
            file_id,
            "extxyz",
            {
                "dry_run": True,
                "repairs": [{"operation": "select_frames", "parameters": {"stop": 2}}],
            },
        ),
    )
    assert env["state"] == "completed"
    assert env["result"]["conversion_report"]["status"] == "completed"


def test_dry_run_with_malformed_repair_fails_like_a_real_run(client: TestClient) -> None:
    file_id = _upload(client, FOUR_FRAMES, "t.xyz")
    env = _job(
        client,
        _convert(
            client,
            file_id,
            "extxyz",
            {
                "dry_run": True,
                "repairs": [{"operation": "select_frames", "parameters": {"step": 0}}],
            },
        ),
    )
    assert env["state"] == "failed"
    assert env["error"]["code"] == "MALFORMED_REQUEST"


def test_dry_run_with_recovery_choices_is_refused_at_submit(client: TestClient) -> None:
    file_id = _upload(client, CELL_LESS_XYZ, "x.xyz")
    resp = client.post(
        "/v1/convert",
        json={
            "file_id": file_id,
            "target_format_id": "poscar",
            "options": {"dry_run": True, "recovery_choices": {"missing_lattice": "bounding_box"}},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_dry_run_is_in_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    options = schema["components"]["schemas"]["ConvertOptions"]["properties"]
    assert options["dry_run"]["default"] is False


def test_strict_dry_run_with_predicted_loss_and_no_ack_reports_refused(
    client: TestClient, repository: Repository
) -> None:
    # extxyz with a cell -> xyz loses the lattice; strict mode without acknowledge_loss refuses
    # a real run, so the dry run must predict the same status (job still completes, no row).
    file_id = _upload(client, CO_IN_CELL, "co.extxyz")
    env = _job(client, _convert(client, file_id, "xyz", {"dry_run": True, "mode": "strict"}))
    assert env["state"] == "completed"
    assert env["result"]["conversion_report"]["status"] == "refused"
    assert env["result"]["conversion_id"] is None
    assert repository.list_conversions(limit=100) == []


def test_batch_convert_refuses_dry_run_in_shared_options(client: TestClient) -> None:
    file_id = _upload(client, CO_IN_CELL, "co.extxyz")
    resp = client.post(
        "/v1/batch/convert",
        json={"file_ids": [file_id], "target_format_id": "poscar", "options": {"dry_run": True}},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_batch_convert_refuses_dry_run_in_a_per_file_override(client: TestClient) -> None:
    file_id = _upload(client, CO_IN_CELL, "co.extxyz")
    resp = client.post(
        "/v1/batch/convert",
        json={
            "file_ids": [file_id],
            "target_format_id": "poscar",
            "overrides": {file_id: {"dry_run": True}},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MALFORMED_REQUEST"


# Periodic in a and b only: the DeePMD exporter refuses per-axis pbc (UNREPRESENTABLE_VALUE) after
# the capability diff has nothing unresolved, so only an exporter-aware dry run predicts it.
SLAB_EXTXYZ = (
    b'2\nLattice="5 0 0 0 5 0 0 0 5" Properties=species:S:1:pos:R:3 pbc="T T F"\nO 0 0 0\nH 0 0 1\n'
)


def test_dry_run_predicts_an_exporter_level_refusal(
    client: TestClient, repository: Repository
) -> None:
    file_id = _upload(client, SLAB_EXTXYZ, "slab.extxyz")
    real = _job(client, _convert(client, file_id, "deepmd_npy", {}))
    assert real["result"]["conversion_report"]["status"] == "refused"
    real_refusal = real["result"]["conversion_report"]["refusal"]
    assert real_refusal["code"] == "UNREPRESENTABLE_VALUE"

    env = _job(client, _convert(client, file_id, "deepmd_npy", {"dry_run": True}))
    assert env["state"] == "completed"
    report = env["result"]["conversion_report"]
    assert report["stage"] == "preflight"
    assert report["status"] == "refused"
    assert report["refusal"] == real_refusal
    assert env["result"]["conversion_id"] is None
    assert env["result"]["download"] is None
