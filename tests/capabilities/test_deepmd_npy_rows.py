"""Capability table-sync for the `deepmd_npy` rows (v1.5 M56-S1 read side; S2 write side).

``deepmd_npy`` is the first **directory** format (MASTER_SPEC Part 3 §3): both directions
declare ``directory_format = True``, so the engine routes through ``parse_dir`` / ``export_dir``
rather than a single stream. The read side maps ``type_map.raw`` → symbols (PARTIAL — absent
maps resolve through ``missing_species``), derives stress deterministically from ``virial.npy``
+ ``box.npy`` (PARTIAL, no scenario — the D211 recorded mapping), and carries the source
numbering under the ``deepmd_npy:*`` namespace (FULL). The write side declares that namespace
writable so the carry survives pre-flight and is restored through ``type.raw``/``type_map.raw``,
plus the assemble capability the batch surface rides (D214). This pins the declarations the
Part 3 §3 table and the §4.2 declarations must match (Part 8 §1.1).
"""

from __future__ import annotations

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel

MATRIX = default_registry().capability_matrix()


def test_read_declares_directory_format_and_the_virial_derivation() -> None:
    caps = default_registry().get_parser("deepmd_npy").capabilities()
    assert caps.format_id == "deepmd_npy"
    assert caps.direction == "read"
    # the first directory format: a directory in, never a stream.
    assert caps.directory_format is True
    assert caps.native_coordinate_system == "cartesian"
    assert caps.fields["atoms.symbols"].level is CapabilityLevel.PARTIAL
    assert "missing_species" in (caps.fields["atoms.symbols"].notes or "")
    assert caps.fields["atoms.positions"].level is CapabilityLevel.FULL
    assert caps.fields["electronic.stress"].level is CapabilityLevel.PARTIAL
    assert "virial" in (caps.fields["electronic.stress"].notes or "")
    assert caps.fields["user_metadata.custom_global"].level is CapabilityLevel.FULL


def test_write_declares_directory_format_assemble_and_the_writable_carry_namespace() -> None:
    caps = default_registry().get_exporter("deepmd_npy").capabilities()
    assert caps.direction == "write"
    assert caps.directory_format is True
    assert caps.assemble_capable is True  # the batch assemble seam (M56-S3/D214)
    assert caps.required_fields == ["atoms.symbols", "atoms.positions"]
    assert caps.fields["electronic.stress"].level is CapabilityLevel.PARTIAL
    # The carried numbering (type_map + type_indices) is the one writable custom_global
    # namespace: pre-flight keeps it so the exporter can restore it byte-faithfully (D69).
    assert caps.writable_custom_key_pattern == {"user_metadata.custom_global": "deepmd_npy:[^:]*"}


def test_directory_format_is_a_matrix_dimension_beside_assemble() -> None:
    # The capability-matrix declaration is what routes the engine: a directory target is
    # excluded from the streaming path, and the batch layer consults directory_format +
    # assemble_capable (never per-format knowledge, P2/P6).
    read = MATRIX.get("deepmd_npy", "read")
    write = MATRIX.get("deepmd_npy", "write")
    assert read.directory_format and write.directory_format
    assert write.assemble_capable is True
