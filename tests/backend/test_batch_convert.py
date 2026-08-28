"""The ``batch_convert`` API job — fan-out to ordinary child jobs + verbatim aggregate (v1.5 M58).

Over real HTTP through the shared ``client`` fixture (inline queue): a mixed manifest fans out to
N ordinary ``kind="convert"`` child jobs, each its own navigable record; the parent's aggregate
embeds every child's ``ConversionReport``/``ValidationReport`` **verbatim** (byte-identical to the
same file converted solo); the tallies reuse the library's ``BatchTallies``/``LabelPresence`` and
match ``xtalate.conversion.batch.run_batch`` on the same inputs; failure isolation is structural
(one bad child never aborts the batch); and a child needing an un-preset recovery choice pauses at
``awaiting_recovery`` **individually** — the batch never answers a recovery question wholesale, and
the parent stays honestly non-terminal until every child is terminal (re-driving lazily on its own
poll).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

from backend.app import create_app

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

# A single celled frame carrying the three MLIP labels — converted to extXYZ these survive, so the
# label-presence tallies are non-zero (energy/forces/stress).
LABELED_EXTXYZ = (
    b"2\n"
    b'Lattice="6.0 0.0 0.0 0.0 6.0 0.0 0.0 0.0 6.0" Properties=species:S:1:pos:R:3:forces:R:3 '
    b'energy=-14.25 stress="1.0 0.5 0.25 0.5 2.0 0.75 0.25 0.75 3.0" pbc="T T T"\n'
    b"N 1.0 1.0 1.0 0.25 0.0 0.0\n"
    b"O 2.0 2.0 2.0 -0.1 0.0 0.5\n"
)

CORRUPT = b"this is definitely not a structure file"


def _norm(report: dict[str, Any]) -> dict[str, Any]:
    """Normalise the run-varying identifiers (the library batch test's own precedent): a fresh
    UUID is minted per report and a ValidationReport links to *its* ConversionReport by id, so two
    runs' ids differ by construction — the substantive content is what must be byte-identical."""
    import json

    report = json.loads(json.dumps(report))
    report["report_id"] = "X"
    report["created_at"] = "X"
    if "conversion_report_id" in report:
        report["conversion_report_id"] = "X"
    return report


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def _submit_batch(
    client: TestClient,
    file_ids: list[str],
    target: str,
    *,
    options: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"file_ids": file_ids, "target_format_id": target}
    if options:
        body["options"] = options
    if overrides:
        body["overrides"] = overrides
    resp = client.post("/v1/batch/convert", json=body)
    assert resp.status_code == 202, resp.text
    return dict(resp.json())


def _tally_tuple(tallies: dict[str, Any]) -> tuple[int, int, int, int]:
    return tallies["total"], tallies["converted"], tallies["refused"], tallies["failed"]


# --- the mixed manifest: fan-out, verbatim embedding, failure isolation ---------------------------


def test_batch_fans_out_to_ordinary_child_jobs_and_aggregates_verbatim(
    client: TestClient, repository: Repository
) -> None:
    # A mixed manifest: one clean conversion, one refusal (XYZ → POSCAR needs a lattice the file
    # lacks, no preset), one corrupt file (UNKNOWN_FORMAT). Failure isolation is structural — the
    # corrupt child fails and the batch still completes with honest tallies.
    clean = _upload(client, POSCAR_SAMPLE, "POSCAR")
    refusing = _upload(client, XYZ_SAMPLE, "mol.xyz")
    corrupt = _upload(client, CORRUPT, "junk.bin")

    env = _submit_batch(client, [clean, refusing, corrupt], "poscar")
    assert env["kind"] == "batch_convert"
    assert env["state"] == "completed", env.get("error")
    assert env["error"] is None

    result = env["result"]
    assert _tally_tuple(result["tallies"]) == (3, 1, 1, 1)
    # Entries are in manifest order, each naming its child job.
    assert [e["file_id"] for e in result["entries"]] == [clean, refusing, corrupt]

    clean_entry = result["entries"][0]
    assert clean_entry["status"] == "converted"
    assert clean_entry["conversion_report"]["status"] == "completed"
    assert clean_entry["validation_report"] is not None
    assert clean_entry["error"] is None

    refused_entry = result["entries"][1]
    assert refused_entry["status"] == "refused"
    assert refused_entry["conversion_report"]["status"] == "refused"
    assert refused_entry["conversion_report"]["refusal"]["code"] == "RECOVERY_REQUIRED"
    assert refused_entry["validation_report"] is None

    failed_entry = result["entries"][2]
    assert failed_entry["status"] == "failed"
    assert failed_entry["conversion_report"] is None
    assert failed_entry["error"]["code"] == "UNKNOWN_FORMAT"

    # The parent envelope projects its children in manifest order — the record is navigable: each
    # child is one link away, and the projection names its state (a link, never a report copy).
    assert [c["file_id"] for c in env["children"]] == [clean, refusing, corrupt]
    assert [c["state"] for c in env["children"]] == ["completed", "completed", "failed"]
    assert [c["job_id"] for c in env["children"]] == [e["child_job_id"] for e in result["entries"]]

    # The wire contract: children are **ordinary** `kind="convert"` jobs by inspection, each with
    # its own navigable record — the only thing that makes them children is the link.
    for entry, expected_state in (
        (clean_entry, "completed"),
        (refused_entry, "completed"),
        (failed_entry, "failed"),
    ):
        child = repository.get_job(entry["child_job_id"])
        assert child is not None
        assert child.kind == "convert"
        assert child.parent_job_id == env["job_id"]
        assert child.state == expected_state


def test_batch_child_report_is_byte_identical_to_the_solo_convert(client: TestClient) -> None:
    # The aggregate cannot elide or reshape a per-file report: the same file converted alone and
    # inside a batch must serialize byte-identically (P1 at dataset scale).
    clean = _upload(client, POSCAR_SAMPLE, "POSCAR")
    solo = client.post("/v1/convert", json={"file_id": clean, "target_format_id": "poscar"}).json()
    assert solo["state"] == "completed", solo.get("error")

    env = _submit_batch(client, [clean], "poscar")
    entry = env["result"]["entries"][0]
    assert _norm(entry["conversion_report"]) == _norm(solo["result"]["conversion_report"])
    assert _norm(entry["validation_report"]) == _norm(solo["result"]["validation_report"])
    assert entry["child_job_id"] != solo["job_id"]  # a distinct ordinary job, not the solo one


def test_batch_tallies_match_the_library_run_batch_on_the_same_inputs(
    client: TestClient, tmp_path: Path
) -> None:
    # The wire reproduces the M54 library contract — the tallies are the library's own models and
    # counts, so the same files yield identical numbers through the CLI and the API.
    from xtalate.conversion.batch import BatchManifest, run_batch
    from xtalate.registry import default_registry

    clean = _upload(client, POSCAR_SAMPLE, "POSCAR")
    refusing = _upload(client, XYZ_SAMPLE, "mol.xyz")
    corrupt = _upload(client, CORRUPT, "junk.bin")

    wire = _submit_batch(client, [clean, refusing, corrupt], "poscar")
    assert wire["state"] == "completed", wire.get("error")
    wire_tallies = wire["result"]["tallies"]

    (tmp_path / "a.poscar").write_bytes(POSCAR_SAMPLE)
    (tmp_path / "b.xyz").write_bytes(XYZ_SAMPLE)
    (tmp_path / "c.bin").write_bytes(CORRUPT)
    library = run_batch(
        BatchManifest(
            sources=[str(tmp_path / "a.poscar"), str(tmp_path / "b.xyz"), str(tmp_path / "c.bin")],
            target="poscar",
        ),
        default_registry(),
    )
    lib = library.tallies
    assert _tally_tuple(wire_tallies) == (lib.total, lib.converted, lib.refused, lib.failed)
    assert wire_tallies["label_presence"] == lib.label_presence.model_dump()


def test_batch_label_presence_counts_labels_carried_by_converted_outputs(
    client: TestClient, tmp_path: Path
) -> None:
    # Label-presence tallies derive from the converted outputs' preserved canonical paths — the
    # library's own derivation, reused — so an extXYZ carrying energy/forces/stress converted to
    # extXYZ contributes all three labels, and the wire agrees with `run_batch`. (The stress
    # carried verbatim by the parser needs its sign convention declared before it is promoted —
    # the same preset on both surfaces.)
    from xtalate.conversion.batch import BatchManifest, run_batch
    from xtalate.registry import default_registry

    stress_choice = {"ambiguous_stress_convention": {"choice": "tension_positive"}}
    labeled = _upload(client, LABELED_EXTXYZ, "labeled.extxyz")
    wire = _submit_batch(client, [labeled], "extxyz", options={"recovery_choices": stress_choice})
    assert wire["state"] == "completed", wire.get("error")
    assert wire["result"]["entries"][0]["status"] == "converted"

    (tmp_path / "labeled.extxyz").write_bytes(LABELED_EXTXYZ)
    library = run_batch(
        BatchManifest(
            sources=[str(tmp_path / "labeled.extxyz")],
            target="extxyz",
            recovery_choices=["ambiguous_stress_convention=tension_positive"],
        ),
        default_registry(),
    )
    presence = library.tallies.label_presence
    assert (presence.energy, presence.forces, presence.stress) == (1, 1, 1)
    assert wire["result"]["tallies"]["label_presence"] == presence.model_dump()


# --- per-file consent is per-file: the pause is the child's, never the batch's --------------------


def _paused_batch(client: TestClient) -> tuple[str, str]:
    """Submit an allow_recovery batch whose one child pauses; return (parent_id, child_id)."""
    pauser = _upload(client, XYZ_SAMPLE, "mol.xyz")
    env = _submit_batch(client, [pauser], "poscar", options={"allow_recovery": True})
    assert env["state"] == "awaiting_recovery"
    # The envelope projects the child in every state — the paused child is navigable from the
    # parent even before the batch completes (the seam the UI renders the incomplete batch from).
    child_id = str(env["children"][0]["job_id"])
    assert env["children"] == [
        {"job_id": child_id, "file_id": pauser, "state": "awaiting_recovery"}
    ]
    return str(env["job_id"]), child_id


def test_paused_child_leaves_the_parent_honestly_non_terminal_and_resume_completes(
    client: TestClient,
) -> None:
    # XYZ → POSCAR needs a lattice; with allow_recovery the **child** pauses at awaiting_recovery
    # — individually, through the existing per-job machinery. The parent pauses too (honestly
    # non-terminal) but carries **no block of its own**: the batch never answers a recovery
    # question wholesale (a non-empty resume of the parent is refused as unoffered).
    parent_id, child_id = _paused_batch(client)
    parent = client.get(f"/v1/jobs/{parent_id}").json()
    assert parent["state"] == "awaiting_recovery"
    assert parent["result"] is None
    assert parent["awaiting_recovery"] is None  # no batch-level question
    assert parent["expires_at"] is None  # the parent owns no input bytes; the child's TTL governs

    # The child's own pause is the ordinary one: a real block with the computed option lists.
    child_env = client.get(f"/v1/jobs/{child_id}").json()
    assert child_env["state"] == "awaiting_recovery"
    assert child_env["awaiting_recovery"]["draft_report"]["status"] == "awaiting_recovery"
    scenarios = {s["scenario"] for s in child_env["awaiting_recovery"]["unresolved_scenarios"]}
    assert "missing_lattice" in scenarios

    # The batch never answers wholesale: resuming the *parent* with a choice is a 422 naming the
    # unoffered scenario — the client must answer the child that asked.
    resp = client.post(
        f"/v1/jobs/{parent_id}/recovery",
        json={
            "choices": {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
            }
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_RECOVERY_CHOICE"

    # Answer the child's own question; the child completes through the ordinary machinery.
    resumed = client.post(
        f"/v1/jobs/{child_id}/recovery",
        json={
            "choices": {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
            }
        },
    ).json()
    assert resumed["state"] == "completed"
    assert resumed["result"]["conversion_report"]["status"] == "completed"

    # Polling the parent re-drives it once every child is terminal: the aggregate now embeds the
    # resumed child's report verbatim (origin "user" — answered interactively, not preset).
    completed = client.get(f"/v1/jobs/{parent_id}").json()
    assert completed["state"] == "completed"
    entry = completed["result"]["entries"][0]
    assert entry["status"] == "converted"
    assert entry["conversion_report"] == resumed["result"]["conversion_report"]
    assert _tally_tuple(completed["result"]["tallies"]) == (1, 1, 0, 0)


def test_expired_child_pause_resolves_to_a_refusal_and_the_parent_completes_on_poll(
    client: TestClient, repository: Repository, settings: Settings
) -> None:
    # The bright line holds per child: a child's pause that times out resolves to a **refused**
    # conversion (RECOVERY_REQUIRED), never a silent default — and once every child is terminal
    # (here: expired), polling the parent re-drives it to a completed aggregate that embeds the
    # refusal verbatim.
    from backend.db import utcnow
    from backend.jobs.expiry import sweep_expired

    parent_id, child_id = _paused_batch(client)
    expired = sweep_expired(repository, settings, now=utcnow() + timedelta(days=1))
    assert child_id in expired

    child = client.get(f"/v1/jobs/{child_id}").json()
    assert child["state"] == "expired"
    assert child["error"]["code"] == "RECOVERY_REQUIRED"

    completed = client.get(f"/v1/jobs/{parent_id}").json()
    assert completed["state"] == "completed"
    entry = completed["result"]["entries"][0]
    assert entry["status"] == "refused"
    assert entry["conversion_report"]["status"] == "refused"
    assert entry["conversion_report"]["refusal"]["code"] == "RECOVERY_REQUIRED"
    assert _tally_tuple(completed["result"]["tallies"]) == (1, 0, 1, 0)


def test_parent_poll_alone_expires_a_due_child_with_no_sweeper(settings: Settings) -> None:
    # Finding-1 regression. A client watching the aggregate polls the **parent**, not each child.
    # Tier 0 runs no background sweeper, so the parent's own poll must cascade the lazy expiry to a
    # child whose TTL has lapsed — otherwise a batch with an unanswered child hangs at
    # awaiting_recovery forever (the "no sweeper needed" guarantee broken for a batch). Here the
    # child's recovery TTL is zero, so a single GET of the *parent* (never the child, never a
    # manual sweep) resolves the child to a refusal and completes the parent.
    from tests.backend.conftest import _migrate

    fast = settings.model_copy(update={"awaiting_recovery_ttl_minutes": 0})
    _migrate(fast.database_url)
    with TestClient(create_app(fast), raise_server_exceptions=False) as client:
        parent_id, child_id = _paused_batch(client)

        completed = client.get(f"/v1/jobs/{parent_id}").json()

        assert completed["state"] == "completed"
        entry = completed["result"]["entries"][0]
        assert entry["status"] == "refused"
        assert entry["conversion_report"]["refusal"]["code"] == "RECOVERY_REQUIRED"
        assert _tally_tuple(completed["result"]["tallies"]) == (1, 0, 1, 0)
        # The child was resolved as a side effect of the parent poll: it now reads expired on its
        # own record too, with no separate poke.
        assert client.get(f"/v1/jobs/{child_id}").json()["state"] == "expired"


def test_a_queued_orphan_child_is_redriven_not_skipped(
    client: TestClient, repository: Repository
) -> None:
    # Tier-1 crash simulation. A parent's first dispatch persists a child row (``add_job``) and
    # then the worker dies before ``execute_job`` runs it, leaving the child ``queued``. A
    # redelivery of the parent must DRIVE that orphan to terminal — the old idempotent skip
    # ("already fanned out, continue") would hang the parent forever on a child that cannot run
    # itself. Plant that exact half-dispatched state, redeliver the parent, and assert it heals.
    import uuid

    from backend.db.models import Job
    from backend.jobs.runner import execute_job

    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    parent_id, child_id = uuid.uuid4().hex, uuid.uuid4().hex
    repository.add_job(
        Job(
            job_id=parent_id,
            kind="batch_convert",
            state="queued",
            request={
                "file_ids": [file_id],
                "target_format_id": "poscar",
                "options": {},
                "overrides": {},
                "request_id": None,
            },
        )
    )
    repository.add_job(
        Job(
            job_id=child_id,
            kind="convert",
            state="queued",
            parent_job_id=parent_id,
            request={
                "file_id": file_id,
                "target_format_id": "poscar",
                "options": {},
                "request_id": None,
            },
        )
    )
    state = client.app.state  # type: ignore[attr-defined]
    # Redeliver the crashed parent through the real runner (the RQ re-dispatch).
    execute_job(
        parent_id,
        repository=repository,
        object_store=state.object_store,
        registry=state.registry,
        settings=state.settings,
    )

    # The orphan was driven (not skipped) and the parent completed on the same dispatch — and no
    # second child row was minted for the same file_id.
    driven_child = repository.get_job(child_id)
    parent = repository.get_job(parent_id)
    assert driven_child is not None and driven_child.state == "completed"
    assert parent is not None and parent.state == "completed"
    assert [c.job_id for c in repository.get_child_jobs(parent_id)] == [child_id]
    env = client.get(f"/v1/jobs/{parent_id}").json()
    assert env["state"] == "completed"
    assert _tally_tuple(env["result"]["tallies"]) == (1, 1, 0, 0)


# --- submit-time validation ----------------------------------------------------------------------


def test_batch_empty_manifest_is_422(client: TestClient) -> None:
    resp = client.post("/v1/batch/convert", json={"file_ids": [], "target_format_id": "poscar"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EMPTY_BATCH"


def test_batch_unknown_file_is_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/batch/convert", json={"file_ids": ["nope"], "target_format_id": "poscar"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_batch_unknown_target_is_422(client: TestClient) -> None:
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    resp = client.post(
        "/v1/batch/convert", json={"file_ids": [file_id], "target_format_id": "not_a_format"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNKNOWN_FORMAT"


def test_batch_duplicate_file_id_is_400(client: TestClient) -> None:
    # A file_id is the identity of one upload, and both the override map and the child fan-out key
    # on it — so the same file_id twice is an ambiguous request, not a request to convert the file
    # twice. Refuse it honestly (naming the offenders) rather than silently collapsing two manifest
    # slots to one child while reporting two identical entries.
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    resp = client.post(
        "/v1/batch/convert",
        json={"file_ids": [file_id, file_id], "target_format_id": "poscar"},
    )
    assert resp.status_code == 400
    body = resp.json()["error"]
    assert body["code"] == "MALFORMED_REQUEST"
    assert body["details"]["duplicate_file_ids"] == [file_id]


def test_batch_override_for_an_unlisted_file_is_400(client: TestClient) -> None:
    # An override naming a file outside the manifest is a malformed request, never silently
    # ignored — the manifest is the whole contract of what the batch converts.
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    resp = client.post(
        "/v1/batch/convert",
        json={
            "file_ids": [file_id],
            "target_format_id": "poscar",
            "overrides": {"ghost": {"mode": "strict"}},
        },
    )
    assert resp.status_code == 400
    body = resp.json()["error"]
    assert body["code"] == "MALFORMED_REQUEST"
    assert body["details"]["unknown_file_ids"] == ["ghost"]


def test_batch_rejects_an_unknown_tolerance_profile_on_submit(client: TestClient) -> None:
    # The shared options ride the same validator as a single convert: a typo'd profile name is a
    # submit-time 400, not a job the caller must poll to discover was doomed.
    file_id = _upload(client, POSCAR_SAMPLE, "POSCAR")
    resp = client.post(
        "/v1/batch/convert",
        json={
            "file_ids": [file_id],
            "target_format_id": "poscar",
            "options": {"tolerance_profile": "defualt"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_batch_per_file_override_replaces_and_inherits_shared_options(client: TestClient) -> None:
    # Per-file consent is per-file: a per-file override's recovery_choices **replaces** the shared
    # presets (never merges — the library's SourceOverride semantics on the wire), while an unset
    # override field inherits the shared value. The shared preset answers via manual_input; the
    # first file's override answers via bounding_box instead. Both children complete; the reports
    # prove which choice each file actually got.
    pauser = _upload(client, XYZ_SAMPLE, "mol.xyz")
    other = _upload(client, XYZ_SAMPLE, "other.xyz")
    shared_choice = {
        "missing_lattice": {
            "choice": "manual_input",
            "parameters": {"lattice": [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]]},
        }
    }
    override_choice = {
        "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
    }
    env = _submit_batch(
        client,
        [pauser, other],
        "poscar",
        options={"allow_recovery": True, "recovery_choices": shared_choice},
        overrides={pauser: {"recovery_choices": override_choice}},
    )
    assert env["state"] == "completed", env.get("error")

    by_file = {e["file_id"]: e for e in env["result"]["entries"]}
    assumptions = {
        fid: {a["scenario"]: a for a in e["conversion_report"]["assumptions"]}
        for fid, e in by_file.items()
    }
    assert assumptions[pauser]["missing_lattice"]["choice"] == "bounding_box"  # replaced
    assert assumptions[other]["missing_lattice"]["choice"] == "manual_input"  # inherited
