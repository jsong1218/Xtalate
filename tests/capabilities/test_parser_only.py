"""The parser-only format seam (v1.2 M42-S1, MASTER_SPEC Revision 1.43, DECISIONS.md D159).

A ``ParserPlugin`` may register with **no** paired ``ExporterPlugin`` — the additive
SDK/registry/capability seam every DFT-*output* format needs (outputs of a code are never
conversion *targets*). This pins the seam's three promises:

1. a parser-only format registers cleanly (no error, no stub exporter required);
2. its Capability Matrix row is **read-side only** — the ``read`` direction present, the
   ``write`` direction absent, and the human rendering says so explicitly; and
3. it is **never a conversion target** — absent from every exporter-derived enumeration
   (CLI ``--to`` surface, round-trip targets), so ``convert <src> --to <parser-only-fmt>``
   refuses with the *existing* unknown/unavailable-target error, exactly like an
   unregistered id. No new error code (the plan names this in D159): a parser-only id is
   treated as an unavailable target, never special-cased.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._dummy_plugins import DummyExporter, DummyParser, make_object
from tests.roundtrip import _matrix
from xtalate.capabilities import Registry
from xtalate.cli import render
from xtalate.cli.main import main
from xtalate.conversion import ConversionEngine
from xtalate.sdk import CapabilityLevel, FieldCapability, FormatCapabilities

_READONLY = "readonlyfmt"
_FULL = FieldCapability(level=CapabilityLevel.FULL)
_WATER = str(Path(__file__).parent.parent / "golden" / "xyz" / "water-traj" / "water_traj.xyz")


def _registry_with_parser_only() -> Registry:
    """A registry holding a synthetic parser-only format and nothing else."""
    reg = Registry()
    reg.register_parser(DummyParser(_READONLY, fields={"atoms.positions": _FULL}))
    return reg


def _declarations(registry: Registry) -> dict[str, dict[str, FormatCapabilities]]:
    """The exact shape ``_cmd_capabilities`` builds before rendering/JSON-dumping — a
    parser-only id contributes only its read row. Kept local so the test mirrors the CLI's
    enumeration (the ``/v1/capabilities`` endpoint derives the same matrix and directions)."""
    matrix = registry.capability_matrix()
    format_ids = {p.format_id for p in registry.parsers()} | {
        e.format_id for e in registry.exporters()
    }
    out: dict[str, dict[str, FormatCapabilities]] = {}
    for fid in format_ids:
        directions: dict[str, FormatCapabilities] = {}
        for direction in ("read", "write"):
            try:
                directions[direction] = matrix.get(fid, direction)
            except KeyError:
                continue
        out[fid] = directions
    return out


# --- 1. registration ---------------------------------------------------------------


def test_parser_only_format_registers_without_an_exporter() -> None:
    reg = Registry()
    # No exporter is ever registered for this format — the seam's whole point. Registering
    # must not error (no stub ExporterPlugin costume required; D159).
    reg.register_parser(DummyParser(_READONLY, fields={"atoms.positions": _FULL}))
    assert [p.format_id for p in reg.parsers()] == [_READONLY]
    assert reg.exporters() == []
    # The matrix answers the read row and has no write row — the first-class read-only shape.
    matrix = reg.capability_matrix()
    assert matrix.get(_READONLY, "read").direction == "read"
    assert matrix.get(_READONLY, "read").fields["atoms.positions"].level is CapabilityLevel.FULL
    with pytest.raises(KeyError, match="no 'write' capabilities registered"):
        matrix.get(_READONLY, "write")


def test_parser_only_registration_leaves_exporters_untouched() -> None:
    # Registering a parser-only format into a registry that already has both sides of another
    # format does not disturb the exporter set (additive, P6) — the parser-only format joins
    # the source list only.
    reg = Registry()
    reg.register_parser(DummyParser("xyz"))
    reg.register_exporter(DummyExporter("xyz"))
    reg.register_parser(DummyParser(_READONLY))
    assert {p.format_id for p in reg.parsers()} == {"xyz", _READONLY}
    assert {e.format_id for e in reg.exporters()} == {"xyz"}


# --- 2. capabilities output is read-side only --------------------------------------


def test_capabilities_json_has_read_direction_only() -> None:
    declarations = _declarations(_registry_with_parser_only())
    assert set(declarations[_READONLY]) == {"read"}
    assert "write" not in declarations[_READONLY]


def test_capabilities_render_names_the_read_only_format() -> None:
    out = render.render_capabilities(_declarations(_registry_with_parser_only()))
    assert "read:" in out
    # The write side is stated honestly — a read-only (parser-only) format, never a target —
    # not a bare "not registered" that could imply an unregistered write side.
    assert "read-only/parser-only format" in out
    assert "never a conversion target" in out


# --- 3. never a conversion target ---------------------------------------------------


def test_parser_only_format_absent_from_roundtrip_targets() -> None:
    # The round-trip matrix derives targets from `exporters()` — a parser-only id is a
    # *source* (read side) but never a *target*, so no suite edits are needed and it can
    # never be offered as a `--to` destination (Part 8 §2; D159).
    reg = _registry_with_parser_only()
    assert _READONLY in _matrix.readable_sources(reg)
    assert _READONLY not in _matrix.writeable_targets(reg)


def test_convert_to_parser_only_target_refuses_with_the_existing_error() -> None:
    # The parser-only id has no exporter, so the engine refuses it with the established
    # unknown/unavailable-target error — the same KeyError shape an entirely unregistered
    # id raises. No new error code exists for "parser-only target" (D159); the seam must
    # not special-case it.
    reg = _registry_with_parser_only()
    source = make_object(source_format="xyz")
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        ConversionEngine(reg).convert(source, source_format_id="xyz", target_format_id=_READONLY)
    # The established error is literally identical to a fully unknown target — the parser-only
    # id earns no new path.
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        ConversionEngine(reg).convert(source, source_format_id="xyz", target_format_id="nosuch")


def test_cli_to_parser_only_id_refuses_like_any_unknown_target() -> None:
    # Through the CLI's own registry (default_registry, which has no parser-only format
    # until S2), `--to <parser-only-fmt>` is refused with the same established error as
    # `--to nosuchformat` — the parser-only id is simply an unavailable target there.
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        main(["convert", _WATER, "--to", _READONLY])
    with pytest.raises(KeyError, match="no 'write' capabilities registered for format"):
        main(["convert", _WATER, "--to", "nosuchformat"])
