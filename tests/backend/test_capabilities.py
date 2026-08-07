"""``/v1/capabilities`` — verbatim from the registry, byte-equal to the CLI (M21 done-means)."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import io
import json
from contextlib import redirect_stdout

import pytest
from fastapi.testclient import TestClient

from xtalate.cli import main


def _cli_capabilities_json(argv: list[str]) -> object:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    assert rc == 0
    return json.loads(buf.getvalue())


def _reference_plugin_installed() -> bool:
    try:
        importlib_metadata.distribution("xtalate-example-format")
    except importlib_metadata.PackageNotFoundError:
        return False
    return True


def test_capabilities_equals_cli_json(client: TestClient) -> None:
    resp = client.get("/v1/capabilities")
    assert resp.status_code == 200
    assert resp.json() == _cli_capabilities_json(["capabilities", "--json"])


def test_capabilities_lists_the_seven_phase1_formats(client: TestClient) -> None:
    body = client.get("/v1/capabilities").json()
    expected = {"xyz", "extxyz", "cif", "poscar", "contcar", "xdatcar", "ase_traj"}
    assert expected <= set(body)


def test_single_format_equals_cli_single_format(client: TestClient) -> None:
    resp = client.get("/v1/capabilities/poscar")
    assert resp.status_code == 200
    assert resp.json() == _cli_capabilities_json(["capabilities", "poscar", "--json"])
    # Shape is {format_id: {...}}, matching the CLI's single-format payload.
    assert set(resp.json()) == {"poscar"}


def test_unknown_format_is_404_envelope(client: TestClient) -> None:
    resp = client.get("/v1/capabilities/not_a_format")
    assert resp.status_code == 404
    err = resp.json()["error"]
    # FORMAT_NOT_FOUND — the Part 6 §2/§6 404 code for an unknown format id (distinct from the
    # 422 UNKNOWN_FORMAT a conversion raises when a file cannot be sniffed).
    assert err["code"] == "FORMAT_NOT_FOUND"
    assert "not_a_format" in err["message"]
    assert "known_formats" in err["details"]
    assert err["request_id"]
    assert err["documentation_url"].endswith("#format_not_found")


@pytest.mark.parametrize("fmt", ["xyz", "cif", "ase_traj"])
def test_each_known_format_resolves(client: TestClient, fmt: str) -> None:
    resp = client.get(f"/v1/capabilities/{fmt}")
    assert resp.status_code == 200
    assert fmt in resp.json()


@pytest.mark.skipif(
    not _reference_plugin_installed(),
    reason="xtalate-example-format not installed (CI installs it; it is the M36 canary)",
)
def test_installed_reference_plugin_surfaces_in_both_read_surfaces(client: TestClient) -> None:
    """M36 done-means (S2 deliverable 3): once the reference plugin is installed, ``exfmt`` shows up
    on *both* generated read-surfaces with zero core changes — the ``/v1/capabilities`` data behind
    the format explorer, and the ``xtalate capabilities`` CLI it is byte-equal to (M21). This is a
    pure read assertion against the registry the app and CLI both build, so it needs no
    ``backend/`` change and no running stack. Skip-guarded for a plain local checkout; in CI (which
    always installs the plugin) it runs, and the equality check above (API == CLI) holds because
    both surfaces enumerate the same discovered registry."""
    api = client.get("/v1/capabilities").json()
    cli = _cli_capabilities_json(["capabilities", "--json"])
    assert isinstance(cli, dict)
    assert "exfmt" in api, "reference plugin installed but exfmt missing from /v1/capabilities"
    assert {"read", "write"} <= set(api["exfmt"])
    assert "exfmt" in cli, "reference plugin installed but exfmt missing from CLI capabilities"
    # Single-format resolution works too — the format explorer's per-format page reads this route.
    single = client.get("/v1/capabilities/exfmt")
    assert single.status_code == 200
    assert set(single.json()) == {"exfmt"}
