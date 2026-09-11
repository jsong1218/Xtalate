"""The ``/v1/convert`` ``repairs`` field (v1.7 M66-S2; D256) — the wire mapping over the
frozen seam.

Additive (Part 6 §7): an absent/empty ``options.repairs`` runs the pre-v1.7 pipeline
byte-for-byte — the persisted report serializes with no ``repairs``/``repair_warnings`` keys
(the derived views add no shape). An ordered list is applied in list order and the report
records that order. A malformed repair (unknown operation, missing required parameter) is a
clean ``MALFORMED_REQUEST`` failed job, never a 500 (the engine's ``RepairError`` mapped in the
worker's failure funnel, reusing the binding code — D256). A *blocked* repair (a cell-less
wrap) pauses to ``awaiting_recovery`` with the existing ``missing_lattice`` block iff
``allow_recovery``, else refuses at HTTP 200 — and since v1.7.1 a *resumed* blocked repair
completes in place: the pre-supplied choice is applied to the object before the repair is
retried (D260), so the resume answers the pause instead of re-pausing.
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

# An unwrapped variant of CO_IN_CELL: the C atom pushed one lattice vector (6 Å) outside the
# box, so a wrap genuinely folds atoms. (CO_IN_CELL itself is already in-cell, so wrapping it
# is a no-op that v1.7.1 correctly leaves unwarned — the R5 fixtures use this variant.)
UNWRAPPED_CO_IN_CELL = (
    b"2\n"
    b'Lattice="6.0 0.0 0.0 0.0 6.0 0.0 0.0 0.0 6.0" '
    b"Properties=species:S:1:pos:R:3:masses:R:1:forces:R:3:charge:R:1 "
    b'pbc="T T T" energy=-14.25 config_type=diatomic\n'
    b"C 7.0 1.0 1.0 12.011 0.5 0.0 0.0 0.3\n"
    b"O 2.125 1.0 1.0 15.999 -0.5 0.0 0.0 -0.3\n"
)


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
    # The unwrapped variant: a wrap that genuinely folds atoms carries the R5 warning (a
    # no-op wrap of an already-in-cell structure correctly carries none since v1.7.1).
    file_id = _upload(client, UNWRAPPED_CO_IN_CELL, "sample.extxyz")
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


def test_cell_less_wrap_over_http_completes_on_resume_with_presupplied_recovery(
    client: TestClient,
) -> None:
    """A cell-less ``wrap_into_cell`` over HTTP is resolvable in place since v1.7.1 (D260): the
    resume applies the pre-supplied ``missing_lattice`` choice to the object *before* the
    blocked repair is retried, so the job completes instead of re-pausing with the same block
    (the v1.7 limitation pinned by the test this replaces, D259's option A). The choice is
    recorded as a recovery Assumption ahead of the repair row — the report's row order stays
    the application order.
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
    env = resumed.json()
    # The resumed repair completes in place — no re-pause, nothing silently dropped.
    assert env["state"] == "completed"
    assert env["awaiting_recovery"] is None
    report = env["result"]["conversion_report"]
    assert report["status"] == "completed"
    # Application order: the recovery that un-blocked the wrap precedes the repair row.
    assert [(a["scenario"], a["choice"]) for a in report["assumptions"]] == [
        ("missing_lattice", "bounding_box"),
        ("repair", "wrap_into_cell"),
    ]
    # The fabricated cell is accounted as supplied — never silently invented.
    assert any(s["path"] == "cell.lattice_vectors" for s in report["supplied"])


def test_recovery_preview_on_a_paused_repair_job_describes_the_repaired_document(
    client: TestClient,
) -> None:
    # REPAIR-H3: the interactive preview of a paused repair job is computed on the same *repaired*
    # document the resume converts — and a preview never refuses. A cell-less XYZ → POSCAR pauses
    # for the target-required lattice; the `center` repair applies cleanly (centroid → origin
    # needs no cell), so the preview is computed on the centered document, and its description is
    # byte-identical to what the resume records (P4). The job stays paused and answerable
    # throughout.
    file_id = _upload(client, CELL_LESS_XYZ, "mol.xyz")
    env = _convert(
        client,
        file_id,
        "poscar",
        {
            "repairs": [
                {
                    "operation": "center",
                    "parameters": {"reference": "centroid", "target": "origin"},
                }
            ],
            "allow_recovery": True,
        },
    )
    assert env["state"] == "awaiting_recovery"
    job_id = env["job_id"]
    choice = {"missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}}

    preview = client.post(f"/v1/jobs/{job_id}/recovery/preview", json={"choices": choice})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["unresolved"] == []
    (row,) = body["previews"]
    assert row["scenario"] == "missing_lattice"
    assert row["choice"] == "bounding_box"
    assert client.get(f"/v1/jobs/{job_id}").json()["state"] == "awaiting_recovery"

    resumed = client.post(f"/v1/jobs/{job_id}/recovery", json={"choices": choice}).json()
    assert resumed["state"] == "completed"
    report = resumed["result"]["conversion_report"]
    # Application order (D250): repairs run between parse and pre-flight, so the repair row
    # precedes the pre-flight recovery row.
    assert [(a["scenario"], a["choice"]) for a in report["assumptions"]] == [
        ("repair", "center"),
        ("missing_lattice", "bounding_box"),
    ]
    recorded = [
        a["description"] for a in report["assumptions"] if a["scenario"] == "missing_lattice"
    ]
    assert recorded == [row["description"]]  # the preview is the record (P4)
