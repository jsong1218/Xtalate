"""Capability table-sync for the variable-N write axis (v2.0 M73-S3; Part 3 §4.2).

Schema 2.0.0 (M72) lifted the constant-N invariant: a ``CanonicalObject``'s frames may now
differ in atom count. Whether a *target* format can express that is a per-format fact, so it
becomes a first-class write-side capability — ``supports_variable_atom_count`` — read directly by
the pre-flight, never inferred from a hard-coded format list (P6). This pins the declarations the
Part 3 §4.2 write column must match (the table-sync discipline, Part 8 §1.1):

* extXYZ, ASE ``.traj``, LAMMPS dump, and ASE ``.db`` write a fresh atom count per frame/row, so
  they hold variable N — ``True``.
* XYZ, POSCAR, CONTCAR, CIF, XDATCAR write one fixed composition (POSCAR/CONTCAR a single
  structure; XDATCAR one header count shared by every frame), so they stay constant-N — ``False``.

The default is ``False``: a format is constant-N until it declares otherwise, so a new exporter
that forgets the axis refuses variable N rather than silently truncating it (P1).
"""

from __future__ import annotations

import pytest

from xtalate.registry import default_registry

MATRIX = default_registry().capability_matrix()
_REGISTRY = default_registry()

_VARIABLE_N_CAPABLE = ["extxyz", "ase_traj", "lammps_dump", "ase_db"]
_CONSTANT_N_ONLY = ["xyz", "poscar", "contcar", "cif", "xdatcar"]


@pytest.mark.parametrize("format_id", _VARIABLE_N_CAPABLE)
def test_variable_n_capable_targets_declare_the_axis(format_id: str) -> None:
    # The exporter's own declaration and the matrix write row agree (table-sync).
    assert _REGISTRY.get_exporter(format_id).capabilities().supports_variable_atom_count is True
    assert MATRIX.get(format_id, "write").supports_variable_atom_count is True


@pytest.mark.parametrize("format_id", _CONSTANT_N_ONLY)
def test_constant_n_only_targets_do_not_declare_the_axis(format_id: str) -> None:
    assert _REGISTRY.get_exporter(format_id).capabilities().supports_variable_atom_count is False
    assert MATRIX.get(format_id, "write").supports_variable_atom_count is False


def test_axis_defaults_to_false() -> None:
    # A format is constant-N until it declares otherwise — the safe default is refusal, so a new
    # exporter that never sets the flag refuses variable N rather than truncating it (P1).
    from xtalate.sdk import FormatCapabilities

    minimal = FormatCapabilities(
        format_id="toy",
        format_name="Toy",
        direction="write",
        native_coordinate_system="cartesian",
    )
    assert minimal.supports_variable_atom_count is False
