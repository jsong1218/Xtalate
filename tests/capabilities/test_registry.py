"""Plugin registry + Capability Matrix (Part 3 §4). Covers the M2 done-criterion:
the registry rejects a capability declaration with an unknown canonical path."""

from __future__ import annotations

import pytest

from tests._dummy_plugins import DummyExporter, DummyParser
from xtalate.capabilities import CapabilityMatrix, InvalidCapabilityDeclaration, Registry
from xtalate.sdk import CapabilityLevel, FieldCapability

FULL = FieldCapability(level=CapabilityLevel.FULL)
NONE = FieldCapability(level=CapabilityLevel.NONE)


def test_register_and_retrieve_parser() -> None:
    reg = Registry()
    parser = DummyParser("xyz", fields={"atoms.positions": FULL})
    reg.register_parser(parser)
    assert reg.get_parser("xyz") is parser
    assert [p.format_id for p in reg.parsers()] == ["xyz"]


def test_duplicate_parser_rejected() -> None:
    reg = Registry()
    reg.register_parser(DummyParser("xyz"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register_parser(DummyParser("xyz"))


def test_mismatched_declaration_format_id_rejected() -> None:
    """A ``capabilities()`` declaration must carry the ``format_id`` of the plugin registering
    it — otherwise the matrix would be keyed by one id while its stored declaration names
    another, and ``xtalate capabilities`` would emit a self-contradictory listing."""
    reg = Registry()
    parser = DummyParser("foo", declared_format_id="bar")
    with pytest.raises(InvalidCapabilityDeclaration, match="'foo'.*declares format_id 'bar'"):
        reg.register_parser(parser)
    exporter = DummyExporter("foo", declared_format_id="bar")
    with pytest.raises(InvalidCapabilityDeclaration, match="'foo'.*declares format_id 'bar'"):
        reg.register_exporter(exporter)


def test_unknown_canonical_path_rejected() -> None:
    reg = Registry()
    bad = DummyParser("weird", fields={"atoms.charge": FULL})  # charges live under electronic
    with pytest.raises(InvalidCapabilityDeclaration, match="unknown canonical field path"):
        reg.register_parser(bad)


def test_unknown_required_field_rejected() -> None:
    reg = Registry()
    bad = DummyExporter("weird", required=["cell.matrix"])  # not a canonical path
    with pytest.raises(InvalidCapabilityDeclaration, match="unknown canonical path"):
        reg.register_exporter(bad)


def test_wildcard_expands_in_matrix() -> None:
    reg = Registry()
    reg.register_exporter(DummyExporter("poscar", fields={"simulation.*": NONE}, max_frames=1))
    matrix = reg.capability_matrix()
    # every simulation leaf is now individually queryable as NONE
    assert matrix.field_capability("poscar", "write", "simulation.xc_functional").level is (
        CapabilityLevel.NONE
    )
    assert matrix.field_capability("poscar", "write", "simulation.extra").level is (
        CapabilityLevel.NONE
    )


def test_concrete_key_overrides_wildcard() -> None:
    reg = Registry()
    reg.register_parser(
        DummyParser("extxyz", fields={"simulation.*": NONE, "simulation.xc_functional": FULL})
    )
    matrix = reg.capability_matrix()
    assert matrix.field_capability("extxyz", "read", "simulation.xc_functional").level is (
        CapabilityLevel.FULL
    )
    assert matrix.field_capability("extxyz", "read", "simulation.thermostat").level is (
        CapabilityLevel.NONE
    )


def test_undeclared_path_defaults_to_none() -> None:
    reg = Registry()
    reg.register_parser(DummyParser("xyz", fields={"atoms.positions": FULL}))
    matrix = reg.capability_matrix()
    # positions declared FULL; velocities undeclared -> defaults to NONE (§4.3)
    assert matrix.field_capability("xyz", "read", "atoms.positions").level is CapabilityLevel.FULL
    assert matrix.field_capability("xyz", "read", "dynamics.velocities").level is (
        CapabilityLevel.NONE
    )


def test_matrix_read_and_write_are_separate() -> None:
    reg = Registry()
    reg.register_parser(DummyParser("poscar", fields={"dynamics.velocities": FULL}))
    reg.register_exporter(DummyExporter("poscar", fields={"dynamics.velocities": FULL}))
    matrix = reg.capability_matrix()
    assert matrix.get("poscar", "read").direction == "read"
    assert matrix.get("poscar", "write").direction == "write"


def test_query_unregistered_format_raises() -> None:
    matrix: CapabilityMatrix = Registry().capability_matrix()
    with pytest.raises(KeyError, match="no 'read' capabilities"):
        matrix.get("nope", "read")
