"""``/v1/capabilities`` — verbatim from the registry, byte-equal to the CLI (M21 done-means)."""

from __future__ import annotations

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
    assert err["code"] == "UNKNOWN_FORMAT"
    assert "not_a_format" in err["message"]
    assert "known_formats" in err["details"]
    assert err["request_id"]
    assert err["documentation_url"].endswith("#unknown_format")


@pytest.mark.parametrize("fmt", ["xyz", "cif", "ase_traj"])
def test_each_known_format_resolves(client: TestClient, fmt: str) -> None:
    resp = client.get(f"/v1/capabilities/{fmt}")
    assert resp.status_code == 200
    assert fmt in resp.json()
