"""Fake entry points for driving plugin discovery without installing a distribution.

Not a test module (no ``test_`` prefix); imported by tests under ``tests/``. An in-memory
stand-in for :class:`importlib.metadata.EntryPoint`, monkeypatched over
``xtalate.registry.entry_points`` — the real installable proof plugin is M16B
(``tests/fixtures/xtalate_toyfmt/``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

import xtalate.registry as registry_mod


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


def patch_entry_points(
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
