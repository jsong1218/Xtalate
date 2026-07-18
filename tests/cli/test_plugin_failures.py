"""CLI surface for a broken installed plugin (post-v0.3 architectural review).

Every ``xtalate`` command builds ``default_registry()``, so a broken installed plugin — an
import failure, a wrong-kind object, a ``format_id`` collision, a malformed declaration — used
to crash *every* command with a raw traceback. The contract pinned here: the CLI still refuses
to run any command until the offending distribution is fixed or uninstalled (discovery never
silently skips a broken plugin, Part 3 §7.1), but the refusal is a clean stderr message naming
the plugin and exit code 1 (§A.2 "usage/internal error"), not a traceback.
"""

from __future__ import annotations

import pytest

import xtalate.registry as registry_mod
from tests._dummy_plugins import DummyExporter, DummyParser
from tests._fake_entry_points import FakeEntryPoint, patch_entry_points
from xtalate.cli.main import EXIT_USAGE, main


def _broken_parser_entry_point(target: object) -> FakeEntryPoint:
    def factory() -> object:
        if isinstance(target, Exception):
            raise target
        return target

    return FakeEntryPoint(
        "toyfmt", "toy_dist.parser:ToyParser", registry_mod.PARSER_ENTRY_POINT_GROUP, factory
    )


@pytest.mark.parametrize(
    ("label", "target"),
    [
        ("import failure", ModuleNotFoundError("no module named 'toy_dist.parser'")),
        ("wrong kind", DummyExporter("toyfmt")),
        ("format_id collision", DummyParser("xyz", score=0.5)),
    ],
)
def test_broken_plugin_is_a_clean_error_naming_the_entry_point(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    label: str,
    target: object,
) -> None:
    patch_entry_points(monkeypatch, parsers=[_broken_parser_entry_point(target)])
    assert main(["capabilities"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "broken installed plugin" in err
    assert "toy_dist.parser:ToyParser" in err  # the failure points at the distribution
    assert "Traceback" not in err


def test_malformed_declaration_is_a_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``InvalidCapabilityDeclaration`` path: it names the format ids itself, and the CLI
    wraps it in the same clean surface."""
    patch_entry_points(
        monkeypatch,
        parsers=[_broken_parser_entry_point(DummyParser("toyfmt", declared_format_id="otherfmt"))],
    )
    assert main(["capabilities"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "broken installed plugin" in err
    assert "'toyfmt'" in err and "'otherfmt'" in err


def test_every_command_refuses_while_a_broken_plugin_is_installed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Not only ``capabilities``: a command that touches only built-in formats still refuses —
    the fail-loud policy (§7.1) is unchanged, only the surface is."""
    patch_entry_points(
        monkeypatch,
        parsers=[_broken_parser_entry_point(ModuleNotFoundError("no module named 'toy_dist'"))],
    )
    assert main(["inspect", "does-not-even-need-to-exist.xyz"]) == EXIT_USAGE
    assert "broken installed plugin" in capsys.readouterr().err
