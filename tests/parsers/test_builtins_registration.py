"""The v0.1 builtin parsers/exporters register cleanly and drive the sniffer end to end.

This is the M3 counterpart of M2's dummy-plugin check: real capability declarations must
validate against the canonical schema paths (Part 3 §4.1), and the sniffer must pick the
right format for each fixture from the real ``sniff()`` scores alone (Part 3 §6.1).
"""

from __future__ import annotations

from pathlib import Path

from chembridge.capabilities import Registry
from chembridge.discovery import Sniffer
from chembridge.exporters import builtin_exporters
from chembridge.parsers import builtin_parsers

GOLDEN = Path(__file__).parent.parent / "golden"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def test_builtins_register_without_error() -> None:
    reg = _registry()
    assert {p.format_id for p in reg.parsers()} == {"xyz", "extxyz", "poscar", "contcar"}
    assert {e.format_id for e in reg.exporters()} == {"xyz", "extxyz", "poscar", "contcar"}


def test_capability_matrix_reports_poscar_write_side() -> None:
    matrix = _registry().capability_matrix()
    caps = matrix.get("poscar", "write")
    assert caps.max_frames == 1
    assert set(caps.required_fields) == {"atoms.symbols", "atoms.positions", "cell.lattice_vectors"}
    # Wildcard 'simulation.*' expanded to concrete leaves at registration (§4.1).
    assert matrix.field_capability("poscar", "write", "simulation.temperature").level == "none"
    assert matrix.field_capability("poscar", "write", "cell.lattice_vectors").level == "full"


def test_sniffer_picks_xyz_for_xyz_file() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    result = sniffer.sniff(data, "water_traj.xyz")
    assert result.format_id == "xyz"


def test_sniffer_prefers_extxyz_over_plain_xyz_on_marked_file() -> None:
    # Both parsers accept the .xyz name, but only extXYZ recognises the Lattice=/Properties=
    # markers — the superset wins the disambiguation (Part 3 §6.1, §3 n.2).
    sniffer = Sniffer(_registry())
    data = b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3\nH 0 0 0\n'
    result = sniffer.sniff(data, "structure.xyz")
    assert result.format_id == "extxyz"


def test_sniffer_picks_plain_xyz_over_extxyz_without_markers() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    assert sniffer.sniff(data, "water_traj.xyz").format_id == "xyz"


def test_sniffer_picks_poscar_by_name() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    result = sniffer.sniff(data, "POSCAR")
    assert result.format_id == "poscar"
    assert result.confidence == 1.0


def test_sniffer_flags_poscar_contcar_ambiguity_on_nameless_file() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    result = sniffer.sniff(data, None)
    # POSCAR wins the nameless tie but the CONTCAR candidate is close => ambiguous (§6.1).
    assert result.format_id == "poscar"
    assert result.ambiguous is True
    assert {c.format_id for c in result.candidates} >= {"poscar", "contcar"}
