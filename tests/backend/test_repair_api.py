"""The ``/v1/convert`` ``repairs`` field (v1.7 M66-S2; D256) — the wire mapping over the
frozen seam.

Additive (Part 6 §7): an absent/empty ``options.repairs`` runs the pre-v1.7 pipeline
byte-for-byte — the persisted report serializes with no ``repairs``/``repair_warnings`` keys
(the derived views add no shape). An ordered list is applied in list order and the report
records that order. A malformed repair (unknown operation, missing required parameter) is a
clean ``MALFORMED_REQUEST`` failed job, never a 500 (the engine's ``RepairError`` mapped in the
worker's failure funnel, reusing the binding code — D256). A *blocked* repair (a cell-less
wrap) pauses to ``awaiting_recovery`` with the existing ``missing_lattice`` block iff
``allow_recovery``, else refuses at HTTP 200.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
CO_IN_CELL = (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes()

# A single-frame, cell-less XYZ — the fixture for the blocked-repair cases.
CELL_LESS_XYZ = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def _convert(
    client: TestClient, file_id: str, target: str, options: dict[str, Any]
) -> dict[str, Any]:
    body: dict[str, Any] = {"file_id": file_id, "target_format_id": target}
    if options:
        body["options"] = options
    resp = client.post("/v1/convert", json=body)
    assert resp.status_code == 202, resp.text
    return cast(dict[str, Any], resp.json())


def _repair_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The report's repairs section, recovered from the serialized ``assumptions`` view."""
    return [a for a in report["assumptions"] if a["scenario"] == "repair"]


def _repair_warnings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in report["warnings"] if w["source"] == "repair"]


def _strip_volatile(node: object) -> object:
    """Drop the legitimately-varying record identity (UUIDs/timestamps) for byte-comparison."""
    if isinstance(node, dict):
        return {
            k: _strip_volatile(v)
            for k, v in node.items()
            if k not in {"report_id", "created_at", "conversion_report_id"}
        }
    if isinstance(node, list):
        return [_strip_volatile(item) for item in node]
    return node


# --- the wire: an ordered repairs list applies and records --------------------------------


def test_repair_wrap_applies_and_records(client: TestClient) -> None:
    file_id = _upload(client, CO_IN_CELL, "sample.extxyz")
    env = _convert(client, file_id, "extxyz", {"repairs": [{"operation": "wrap_into_cell"}]})
    assert env["state"] == "completed"
    report = env["result"]["conversion_report"]
    assert report["status"] == "completed"
    assert env["result"]["validation_report"]["status"] == "passed"

    (row,) = _repair_rows(report)
    assert row["choice"] == "wrap_into_cell"
    assert row["origin"] == "preset"
    assert "Wrapped all atom positions into the simulation cell" in row["description"]
    (warning,) = _repair_warnings(report)
    assert warning["code"] == "WRAP_DISCARDS_UNWRAPPED_PATHS"


def test_repair_order_is_preserved_across_the_list(client: TestClient) -> None:
    def run(repairs: list[dict[str, Any]]) -> list[str]:
        file_id = _upload(client, CO_IN_CELL, "sample.extxyz")
        env = _convert(client, file_id, "extxyz", {"repairs": repairs})
        assert env["state"] == "completed"
        return [row["choice"] for row in _repair_rows(env["result"]["conversion_report"])]

    center_first: list[dict[str, Any]] = [
        {"operation": "center", "parameters": {"reference": "centroid", "target": "origin"}},
        {"operation": "wrap_into_cell"},
    ]
    wrap_first: list[dict[str, Any]] = [
        {"operation": "wrap_into_cell"},
        {"operation": "center", "parameters": {"reference": "centroid", "target": "origin"}},
    ]
    # Order is scientific meaning (D250): the list is applied in the order given, and the
    # report's row order is the application order — center->wrap and wrap->center are
    # different records, exactly as the CLI proves (M66-S1).
    assert run(center_first) == ["center", "wrap_into_cell"]
    assert run(wrap_first) == ["wrap_into_cell", "center"]


# --- the additive invariant: no repairs is byte-identical ----------------------------------


def test_absent_or_empty_repairs_is_byte_identical(client: TestClient) -> None:
    def run(options: dict[str, Any] | None) -> dict[str, Any]:
        file_id = _upload(client, CO_IN_CELL, "sample.extxyz")
        env = _convert(client, file_id, "extxyz", options or {})
        assert env["state"] == "completed"
        return cast(dict[str, Any], env["result"]["conversion_report"])

    absent = run(None)
    empty = run({"repairs": []})

    # The additive invariant (D250, Part 6 §7): a report without repairs serializes with no
    # `repairs`/`repair_warnings` keys at all — and an explicit empty list is the same
    # pipeline, byte-for-byte modulo the legitimately-varying record identity.
    for report in (absent, empty):
        assert "repairs" not in report
        assert "repair_warnings" not in report
        assert all(a["scenario"] != "repair" for a in report["assumptions"])
    assert _strip_volatile(absent) == _strip_volatile(empty)


# --- a malformed repair is a clean request error, never a 500 ------------------------------


@pytest.mark.parametrize(
    "repairs",
    [
        [{"operation": "deduplicate"}],  # missing required distance_threshold
        [{"operation": "teleport"}],  # unknown operation
        [{"operation": "center", "parameters": {"reference": "centroid"}}],  # missing target
    ],
)
def test_malformed_repair_is_malformed_request_not_500(
    client: TestClient, repairs: list[dict[str, Any]]
) -> None:
    file_id = _upload(client, CO_IN_CELL, "sample.extxyz")
    env = _convert(client, file_id, "extxyz", {"repairs": repairs})
    # The engine's RepairError is a caller error, not a server fault: the job fails carrying
    # the binding malformed-request code (D256 — no new error code), never INTERNAL_ERROR.
    assert env["state"] == "failed"
    assert env["error"]["code"] == "MALFORMED_REQUEST"


# --- the cell-less block behaves per allow_recovery ----------------------------------------


def test_cell_less_wrap_without_allow_recovery_refuses_at_200(client: TestClient) -> None:
    # The CLI-refuses / API-pauses split of the fabricative bright line: without the explicit
    # interactive opt-in, a blocked repair is a *completed refused* job at HTTP 200 — never a
    # pause the client must poll, and never a fabricated box.
    file_id = _upload(client, CELL_LESS_XYZ, "mol.xyz")
    env = _convert(client, file_id, "xyz", {"repairs": [{"operation": "wrap_into_cell"}]})
    assert env["state"] == "completed"
    report = env["result"]["conversion_report"]
    assert report["status"] == "refused"
    assert env["awaiting_recovery"] is None
    assert "missing_lattice" in str(report["refusal"])
    assert report["supplied"] == []  # nothing fabricated
    assert _repair_rows(report) == []  # nothing applied


def test_cell_less_wrap_with_allow_recovery_pauses_with_missing_lattice(
    client: TestClient,
) -> None:
    file_id = _upload(client, CELL_LESS_XYZ, "mol.xyz")
    env = _convert(
        client,
        file_id,
        "xyz",
        {"repairs": [{"operation": "wrap_into_cell"}], "allow_recovery": True},
    )
    # The pause fires for a *repair* block, not only a pre-flight one: the worker's existing
    # block -> missing_lattice machinery (D249/D250) routes the cell-less wrap into the same
    # awaiting_recovery path a target-required lattice would take.
    assert env["state"] == "awaiting_recovery"
    assert env["result"] is None
    block = env["awaiting_recovery"]
    assert block is not None
    scenarios = {s["scenario"]: s for s in block["unresolved_scenarios"]}
    assert "missing_lattice" in scenarios
    assert scenarios["missing_lattice"]["path"] == "cell.lattice_vectors"
    codes = {o["choice"] for o in scenarios["missing_lattice"]["options"]}
    assert {"manual_input", "bounding_box", "upload_reference"} <= codes


def test_resumed_blocked_repair_repauses_pending_engine_decision(client: TestClient) -> None:
    """The pause is offered and answerable through the existing recovery path, but a blocked
    repair re-pauses on resume: the engine's repair stage runs before recovery and blocks
    unconditionally (M64 design; D250 "between parse and pre-flight"), so a pre-supplied
    ``missing_lattice`` choice cannot un-block the wrap in the same pipeline pass.

    **Flagged for review (M66-S2):** the slice plan's "resolvable via the existing
    ``POST /v1/jobs/{id}/recovery`` path" overstates the engine here — making a resumed
    repair complete needs an engine change (apply a pre-supplied recovery before retrying a
    blocked repair), which is frozen for M66 and must be decided by the maintainer/Claude.
    This test pins the *current* honest behavior so the gap is visible in the suite.
    """
    file_id = _upload(client, CELL_LESS_XYZ, "mol.xyz")
    env = _convert(
        client,
        file_id,
        "xyz",
        {"repairs": [{"operation": "wrap_into_cell"}], "allow_recovery": True},
    )
    assert env["state"] == "awaiting_recovery"
    job_id = env["job_id"]
    choice = {"missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}}

    # The resume endpoint accepts the choice through the existing path (validation against the
    # offered options — no 422), then re-runs the job with the same repairs.
    resumed = client.post(f"/v1/jobs/{job_id}/recovery", json={"choices": choice})
    assert resumed.status_code == 200, resumed.text
    # The engine re-blocks (the repair stage precedes recovery), so the job pauses again with
    # the same missing_lattice block — nothing fabricated, nothing applied, no silent drop of
    # the requested repair. Completion needs the engine decision flagged above.
    env = resumed.json()
    assert env["state"] == "awaiting_recovery"
    scenarios = {s["scenario"] for s in env["awaiting_recovery"]["unresolved_scenarios"]}
    assert scenarios == {"missing_lattice"}
    # The re-run recorded nothing — the request's repairs are preserved for the eventual fix.
    from backend.db import Repository

    repository = cast(Repository, client.app.state.repository)  # type: ignore[attr-defined]
    job = repository.get_job(job_id)
    # The persisted request carries the normalized wire shape (``parameters`` defaulted to {}).
    assert job is not None and job.request["options"]["repairs"] == [
        {"operation": "wrap_into_cell", "parameters": {}}
    ]
