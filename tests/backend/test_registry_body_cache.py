"""E5: the static registry-derived response bodies are built once per plugin set."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from fastapi.testclient import TestClient  # noqa: E402

from backend.routers import capabilities as cap_router  # noqa: E402
from backend.routers import jobs as jobs_router  # noqa: E402
from backend.routers import plugins as plugins_router  # noqa: E402
from xtalate.capabilities import Registry  # noqa: E402
from xtalate.exporters import builtin_exporters  # noqa: E402
from xtalate.parsers import builtin_parsers  # noqa: E402


def _registry(n: int | None = None) -> Registry:
    reg = Registry()
    for parser in list(builtin_parsers())[:n]:
        reg.register_parser(parser)
    for exporter in list(builtin_exporters())[:n]:
        reg.register_exporter(exporter)
    return reg


def test_capabilities_body_is_built_once_per_registry() -> None:
    reg = _registry()
    assert cap_router.capabilities_body(reg) is cap_router.capabilities_body(reg)


def test_capabilities_body_is_rebuilt_when_a_plugin_is_registered() -> None:
    reg = _registry(2)
    before = set(cap_router.capabilities_body(reg))
    for parser in list(builtin_parsers())[2:]:
        reg.register_parser(parser)
    for exporter in list(builtin_exporters())[2:]:
        reg.register_exporter(exporter)
    after = set(cap_router.capabilities_body(reg))
    assert before < after


def test_plugins_body_is_built_once_and_rebuilt_on_change() -> None:
    reg = _registry(2)
    first = plugins_router.plugins_body(reg)
    assert plugins_router.plugins_body(reg) is first
    reg.register_parser(list(builtin_parsers())[2])
    second = plugins_router.plugins_body(reg)
    assert second is not first
    assert len(second["plugins"]) == len(first["plugins"]) + 1


def test_distinct_registries_do_not_share_a_cache_entry() -> None:
    a, b = _registry(2), _registry()
    assert set(cap_router.capabilities_body(a)) != set(cap_router.capabilities_body(b))


def test_cached_endpoint_payloads_are_unchanged(client: TestClient) -> None:
    first = client.get("/v1/capabilities").json()
    assert first == client.get("/v1/capabilities").json()
    assert "xyz" in first
    assert client.get("/v1/capabilities/xyz").json() == {"xyz": first["xyz"]}
    plugins = client.get("/v1/plugins").json()
    assert plugins == client.get("/v1/plugins").json()


def test_repeated_responses_are_byte_identical(client: TestClient) -> None:
    assert client.get("/v1/capabilities").content == client.get("/v1/capabilities").content


def test_package_version_is_read_from_metadata_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as md

    jobs_router._xtalate_version.cache_clear()
    calls = {"n": 0}
    real = md.version

    def counting(name: str) -> str:
        calls["n"] += 1
        return real(name)

    monkeypatch.setattr(md, "version", counting)
    reg = _registry()
    first = jobs_router._registry_fingerprint(reg)
    for _ in range(5):
        assert jobs_router._registry_fingerprint(reg) == first
    assert calls["n"] == 1
    jobs_router._xtalate_version.cache_clear()
