"""Entry-point plugin discovery (MASTER_SPEC Part 3 §7.1, M16A).

``default_registry()`` registers the built-ins, then discovers third-party parsers/exporters
advertised under the ``xtalate.parsers`` / ``xtalate.exporters`` entry-point groups. These tests
drive that third pass with *fake* entry points — an in-memory stand-in for an installed
distribution, monkeypatched over ``xtalate.registry.entry_points`` — so no package has to be
pip-installed to exercise the mechanism (the real installable proof plugin is M16B). The contract:
a well-formed plugin is discovered and registered; a plugin that fails to load, declares a bad
capability, or collides with a first-party ``format_id`` fails **loudly** — discovery never
swallows a broken plugin (§7.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

import xtalate.registry as registry_mod
from tests._dummy_plugins import DummyExporter, DummyParser
from xtalate.capabilities.registry import InvalidCapabilityDeclaration
from xtalate.registry import PluginLoadError, default_registry
from xtalate.sdk import CapabilityLevel, FieldCapability


@dataclass
class FakeEntryPoint:
    """Stand-in for :class:`importlib.metadata.EntryPoint` with the surface ``registry.py`` uses:
    ``name``/``group``/``value`` for error messages, and ``load()`` returning the target callable.
    Unlike the real one, ``load()`` hands back an in-memory object instead of importing a module,
    so a test declares a plugin inline without installing a distribution."""

    name: str
    value: str
    group: str
    target: Callable[[], object]

    def load(self) -> Callable[[], object]:
        return self.target


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parsers: list[FakeEntryPoint] | None = None,
    exporters: list[FakeEntryPoint] | None = None,
) -> None:
    """Route ``xtalate.registry.entry_points(group=...)`` to the supplied fakes, per group."""
    by_group = {
        registry_mod.PARSER_ENTRY_POINT_GROUP: parsers or [],
        registry_mod.EXPORTER_ENTRY_POINT_GROUP: exporters or [],
    }

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        return by_group.get(group, [])

    monkeypatch.setattr(registry_mod, "entry_points", fake_entry_points)


# A capability declaration that names a canonical path which does not exist — the registry must
# reject it at registration (the same validation a built-in gets).
_BAD_FIELDS = {"geometry.not_a_real_field": FieldCapability(level=CapabilityLevel.FULL)}


def test_default_registry_has_no_plugins_when_none_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mechanism is additive: with zero entry points, the registry is exactly the built-ins.
    (Guards against discovery accidentally dropping or duplicating a format.)"""
    _patch_entry_points(monkeypatch)
    baseline = {p.format_id for p in default_registry().parsers()}

    # Sanity: the built-in set is non-empty and unchanged by an empty discovery pass.
    assert "xyz" in baseline
    assert baseline == {p.format_id for p in default_registry().parsers()}


def test_wellformed_plugin_is_discovered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed third-party parser + exporter, advertised via entry points, is registered
    into ``default_registry()`` alongside the built-ins and is queryable in the matrix."""
    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist.parser:ToyParser",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                lambda: DummyParser("toyfmt", score=0.5),
            )
        ],
        exporters=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist.exporter:ToyExporter",
                registry_mod.EXPORTER_ENTRY_POINT_GROUP,
                lambda: DummyExporter("toyfmt"),
            )
        ],
    )
    registry = default_registry()

    assert registry.get_parser("toyfmt").format_id == "toyfmt"
    assert registry.get_exporter("toyfmt").format_id == "toyfmt"
    # It went through the real registration path, so the matrix carries its declaration too.
    matrix = registry.capability_matrix()
    assert matrix.get("toyfmt", "read").format_id == "toyfmt"
    assert matrix.get("toyfmt", "write").format_id == "toyfmt"
    # The built-ins are untouched.
    assert registry.get_parser("xyz").format_id == "xyz"


def test_factory_entry_point_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The target may be a factory function (like the built-in ``make_poscar_parser``), not only a
    class — either is a zero-arg callable returning a plugin instance."""

    def make_toy_parser() -> DummyParser:
        return DummyParser("toyfmt", score=0.5)

    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist:make_toy_parser",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                make_toy_parser,
            )
        ],
    )
    assert default_registry().get_parser("toyfmt").format_id == "toyfmt"


def test_bad_capability_declaration_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin declaring a capability against an unknown canonical path is rejected at
    ``default_registry()`` — it goes through the same validation as a built-in, so
    ``InvalidCapabilityDeclaration`` propagates rather than being swallowed (§7.1)."""
    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist:BadParser",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                lambda: DummyParser("toyfmt", fields=_BAD_FIELDS),
            )
        ],
    )
    with pytest.raises(InvalidCapabilityDeclaration):
        default_registry()


def test_format_id_collision_with_builtin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A third-party plugin claiming a first-party ``format_id`` hits the registry's duplicate
    guard. Built-ins register first, so their ids win the namespace and the plugin is rejected."""
    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "xyz",
                "toy_dist:ImposterXyz",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                lambda: DummyParser("xyz", score=0.5),
            )
        ],
    )
    with pytest.raises(ValueError, match="already registered.*'xyz'"):
        default_registry()


def test_import_failure_names_the_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin whose target fails to load (a broken import, a distribution built against a moved
    module) fails with a ``PluginLoadError`` naming the entry point — not an opaque traceback deep
    in someone else's package."""

    def boom() -> object:
        raise ModuleNotFoundError("no module named 'toy_dist.parser'")

    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist.parser:ToyParser",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                boom,
            )
        ],
    )
    with pytest.raises(PluginLoadError, match=r"toyfmt.*toy_dist\.parser:ToyParser"):
        default_registry()


def test_wrong_object_type_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parser-group entry point that yields a non-parser (a misconfigured plugin pointing an
    exporter at the parser group, say) is rejected with a readable ``PluginLoadError`` rather than
    failing obscurely inside ``register_parser``."""
    _patch_entry_points(
        monkeypatch,
        parsers=[
            FakeEntryPoint(
                "toyfmt",
                "toy_dist:NotAParser",
                registry_mod.PARSER_ENTRY_POINT_GROUP,
                lambda: DummyExporter("toyfmt"),
            )
        ],
    )
    with pytest.raises(PluginLoadError, match="not a ParserPlugin"):
        default_registry()
