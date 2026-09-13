"""``GET /v1/plugins`` — the flat, public roster of every installed plugin (v1.8 M70).

The service holds no plugin knowledge of its own: the endpoint reads the registry and lists what is
installed, across all three plugin kinds, sorted deterministically. It is public and rate-limited
like ``/v1/capabilities`` (Part 6 §4).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_plugins_lists_parsers_and_exporters(client: TestClient) -> None:
    resp = client.get("/v1/plugins")
    assert resp.status_code == 200
    plugins = resp.json()["plugins"]
    kinds = {p["kind"] for p in plugins}
    # The seven Phase-1 formats install both a parser and an exporter; analysis rows appear only
    # when an analysis plugin is installed (none is, in the plain dev gate).
    assert {"parser", "exporter"} <= kinds

    # Every row carries a name and a version; format rows carry a human-readable format_name.
    xyz = next(p for p in plugins if p["kind"] == "parser" and p["name"] == "xyz")
    assert xyz["version"]
    assert xyz["format_name"] == "Plain XYZ"


def test_plugins_is_sorted_by_kind_then_name(client: TestClient) -> None:
    plugins = client.get("/v1/plugins").json()["plugins"]
    keys = [(p["kind"], p["name"]) for p in plugins]
    assert keys == sorted(keys)


def test_plugins_covers_the_seven_phase1_formats(client: TestClient) -> None:
    plugins = client.get("/v1/plugins").json()["plugins"]
    parser_names = {p["name"] for p in plugins if p["kind"] == "parser"}
    expected = {"xyz", "extxyz", "cif", "poscar", "contcar", "xdatcar", "ase_traj"}
    assert expected <= parser_names


def test_plugins_is_public_even_with_a_key_configured(
    build_client: Callable[..., TestClient],
) -> None:
    # Public + unauthenticated like /v1/capabilities: a client asks what an instance can do without
    # holding a key (Part 6 §4).
    client = build_client(api_keys="secret-key")
    assert client.get("/v1/plugins").status_code == 200
