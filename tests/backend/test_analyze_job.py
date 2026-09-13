"""``POST /v1/analyze`` over HTTP — run one installed analysis plugin on an uploaded file (M70).

The plain dev gate installs no analysis plugin (the composition reference plugin ships as its own
distribution, installed only in the Docker image), so these tests inject their own plugins onto the
running app's registry — a good one (returns its own namespace) and a rogue one (escapes it) — to
exercise both completed outcomes, plus the two error paths: an unknown plugin (a submit ``422``) and
an unparseable upload (a ``failed`` job, since there is nothing to analyze).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from pydantic import JsonValue

from xtalate.sdk import AnalysisPlugin

if TYPE_CHECKING:
    from xtalate.schema import CanonicalObject

XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""


class _ProbePlugin(AnalysisPlugin):
    """A well-behaved plugin: writes only its own ``probe:`` namespace (Part 2 §6 rule 2)."""

    name = "probe"
    version = "1.2.3"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        return {"probe:frame_count": len(canonical.frames), "probe:note": "seen"}


class _RoguePlugin(AnalysisPlugin):
    """A misbehaving plugin: writes a key outside its own namespace → :class:`AnalysisError`."""

    name = "rogue"
    version = "0.1.0"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        return {"other:leak": 1}


def _upload(client: TestClient, content: bytes, filename: str) -> str:
    resp = client.post("/v1/upload", files={"file": (filename, content)})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["file_id"])


def test_analyze_completes_and_embeds_the_analysis_report(client: TestClient) -> None:
    client.app.state.registry.register_analysis_plugin(_ProbePlugin())
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")

    resp = client.post("/v1/analyze", json={"file_id": file_id, "plugin": "probe"})
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["kind"] == "analyze"
    # Inline queue: the job is already completed by the time submit returns.
    assert env["state"] == "completed"
    report = env["result"]["analysis_report"]
    assert report["status"] == "ok"
    assert report["plugin"] == "probe"
    assert report["plugin_version"] == "1.2.3"
    # Exactly the plugin's own namespace, verbatim — the keys it wrote into custom_global.
    assert report["results"] == {"probe:frame_count": 1, "probe:note": "seen"}
    # The single operation="analyze" record the run appended to Provenance (D269).
    assert report["record"]["operation"] == "analyze"
    assert report["record"]["parser_version"] == "probe 1.2.3"
    assert report["message"] is None


def test_analyze_unknown_plugin_is_422_envelope(client: TestClient) -> None:
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")
    resp = client.post("/v1/analyze", json={"file_id": file_id, "plugin": "nope"})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "UNKNOWN_PLUGIN"
    # The installed set is listed so a caller can correct the request without a second round-trip.
    # Which analysis plugins are installed varies by environment (none in the plain CI dev gate, the
    # composition reference plugin in the Docker image / a local editable install), so assert only
    # the invariant: the requested name is not among them, and the set is a list of strings.
    installed = error["details"]["installed_plugins"]
    assert isinstance(installed, list)
    assert "nope" not in installed


def test_analyze_plugin_error_is_a_completed_job_reporting_the_failure(client: TestClient) -> None:
    # A plugin that escapes its namespace is its own reported failure (D268) — a completed HTTP-200
    # job whose report says so, the analysis analogue of a refused conversion, never a failed job.
    client.app.state.registry.register_analysis_plugin(_RoguePlugin())
    file_id = _upload(client, XYZ_SAMPLE, "mol.xyz")

    resp = client.post("/v1/analyze", json={"file_id": file_id, "plugin": "rogue"})
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["state"] == "completed"
    report = env["result"]["analysis_report"]
    assert report["status"] == "error"
    assert report["plugin"] == "rogue"
    assert "rogue" in report["message"]
    assert report["results"] is None
    assert report["record"] is None


def test_analyze_unparseable_upload_is_a_failed_job(client: TestClient) -> None:
    # A parse failure is different from a plugin failure: the file could not be read at all, so
    # there is nothing to analyze — the job fails exactly as inspect/convert would.
    client.app.state.registry.register_analysis_plugin(_ProbePlugin())
    file_id = _upload(client, b"not a molecule in any known format\n", "junk.xyz")

    resp = client.post("/v1/analyze", json={"file_id": file_id, "plugin": "probe"})
    assert resp.status_code == 202, resp.text
    env = resp.json()
    assert env["state"] == "failed"
    assert env["error"]["code"] in {"PARSE_ERROR", "UNKNOWN_FORMAT"}
