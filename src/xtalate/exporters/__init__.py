"""Exporters — one ``ExporterPlugin`` per format: Canonical Object → native file (Part 4 §1).

Writes exactly the ``write_plan`` handed to it; never reads native files, calls a
parser, or fabricates absent fields (Part 1 §2, Part 4 §1). Depends on ``schema``
and ``sdk``. Lands alongside its paired parser in M3.

``builtin_exporters()`` mirrors ``parsers.builtin_parsers()`` — a downward-only list a
higher layer assembles into a Registry.
"""

from __future__ import annotations

from xtalate.exporters.ase_traj import AseTrajExporter, make_ase_traj_exporter
from xtalate.exporters.cif import CifExporter, make_cif_exporter
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.exporters.poscar import (
    PoscarExporter,
    make_contcar_exporter,
    make_poscar_exporter,
)
from xtalate.exporters.xdatcar import XdatcarExporter, make_xdatcar_exporter
from xtalate.exporters.xyz import XyzExporter
from xtalate.sdk import ExporterPlugin

__all__ = [
    "AseTrajExporter",
    "CifExporter",
    "ExtxyzExporter",
    "PoscarExporter",
    "XdatcarExporter",
    "XyzExporter",
    "builtin_exporters",
    "make_ase_traj_exporter",
    "make_cif_exporter",
    "make_contcar_exporter",
    "make_poscar_exporter",
    "make_xdatcar_exporter",
]


def builtin_exporters() -> list[ExporterPlugin]:
    """The exporters shipped so far (v0.1: M3a XYZ, M3b POSCAR/CONTCAR, M3c extXYZ; v0.3: M13
    XDATCAR, M14 ASE trajectory; v0.4: M19 CIF)."""
    return [
        XyzExporter(),
        ExtxyzExporter(),
        make_poscar_exporter(),
        make_contcar_exporter(),
        make_xdatcar_exporter(),
        make_ase_traj_exporter(),
        make_cif_exporter(),
    ]
