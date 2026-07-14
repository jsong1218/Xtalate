"""Capability table-sync for the velocity/mass rows (M8, MASTER_SPEC Part 3 §4).

The velocity-family recovery leans on the Capability Matrix (not a hand-coded per-pair list) to
decide where velocities/masses can be emitted, so the declared rows must stay faithful:
POSCAR/CONTCAR read *and* write velocities; plain XYZ can do neither; and `atoms.masses` is a v0.1
formats cannot write (POSCAR has no mass field), which is exactly why a chained `missing_masses`
rides in `supplied` without entering the write plan (D47).
"""

from __future__ import annotations

import pytest

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel

MATRIX = default_registry().capability_matrix()


@pytest.mark.parametrize("format_id", ["poscar", "contcar"])
def test_poscar_family_reads_and_writes_velocities(format_id: str) -> None:
    assert MATRIX.field_capability(format_id, "read", "dynamics.velocities").level is (
        CapabilityLevel.FULL
    )
    assert MATRIX.field_capability(format_id, "write", "dynamics.velocities").level is (
        CapabilityLevel.FULL
    )


def test_plain_xyz_cannot_hold_velocities() -> None:
    # Undeclared → NONE (§4.3): plain XYZ carries no velocity block, so an emission request refuses.
    assert MATRIX.field_capability("xyz", "write", "dynamics.velocities").level is (
        CapabilityLevel.NONE
    )


@pytest.mark.parametrize("format_id", ["xyz", "poscar", "contcar"])
def test_no_v01_format_writes_masses(format_id: str) -> None:
    # None of the four v0.1 formats has a mass field on the write side — a fabricated mass is only
    # ever an intermediate that feeds a velocity draw, kept out of the write plan (D47).
    assert MATRIX.field_capability(format_id, "write", "atoms.masses").level is CapabilityLevel.NONE


def test_extxyz_reads_masses() -> None:
    # extXYZ is the one v0.1 format that carries masses on read (a masses column) — the source of
    # the done-criterion's already-present masses.
    assert MATRIX.field_capability("extxyz", "read", "atoms.masses").level is not (
        CapabilityLevel.NONE
    )
