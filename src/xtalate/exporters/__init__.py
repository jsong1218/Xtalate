"""Exporters — one ``ExporterPlugin`` per format: Canonical Object → native file (Part 4 §1).

Writes exactly the ``write_plan`` handed to it; never reads native files, calls a
parser, or fabricates absent fields (Part 1 §2, Part 4 §1). Depends on ``schema``
and ``sdk``. Lands alongside its paired parser in M3.

``builtin_exporters()`` mirrors ``parsers.builtin_parsers()`` — a downward-only list a
higher layer assembles into a Registry.
"""

from __future__ import annotations

from xtalate.exporters.ase_db import AseDbExporter, make_ase_db_exporter
from xtalate.exporters.ase_traj import AseTrajExporter, make_ase_traj_exporter
from xtalate.exporters.cif import CifExporter, make_cif_exporter
from xtalate.exporters.deepmd_npy import DeepmdNpyExporter, make_deepmd_npy_exporter
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.exporters.lammps_data import LammpsDataExporter, make_lammps_data_exporter
from xtalate.exporters.lammps_dump import LammpsDumpExporter, make_lammps_dump_exporter
from xtalate.exporters.poscar import (
    PoscarExporter,
    make_contcar_exporter,
    make_poscar_exporter,
)
from xtalate.exporters.qe_pw_in import QePwInExporter, make_qe_pw_in_exporter
from xtalate.exporters.xdatcar import XdatcarExporter, make_xdatcar_exporter
from xtalate.exporters.xyz import XyzExporter
from xtalate.sdk import ExporterPlugin

__all__ = [
    "AseDbExporter",
    "AseTrajExporter",
    "CifExporter",
    "DeepmdNpyExporter",
    "ExtxyzExporter",
    "LammpsDataExporter",
    "LammpsDumpExporter",
    "PoscarExporter",
    "QePwInExporter",
    "XdatcarExporter",
    "XyzExporter",
    "builtin_exporters",
    "make_ase_db_exporter",
    "make_ase_traj_exporter",
    "make_cif_exporter",
    "make_deepmd_npy_exporter",
    "make_contcar_exporter",
    "make_lammps_data_exporter",
    "make_lammps_dump_exporter",
    "make_poscar_exporter",
    "make_qe_pw_in_exporter",
    "make_xdatcar_exporter",
]


def builtin_exporters() -> list[ExporterPlugin]:
    """The exporters shipped so far (v0.1: M3a XYZ, M3b POSCAR/CONTCAR, M3c extXYZ; v0.3: M13
    XDATCAR, M14 ASE trajectory; v0.4: M19 CIF; v1.4 M51: the QE pw.x input exporter, closing
    M50's parser-only staging state into a full read+write format; v1.5 M55: the ASE database
    exporter, the write half of the .db format on the batch surface)."""
    return [
        XyzExporter(),
        ExtxyzExporter(),
        make_lammps_data_exporter(),
        make_lammps_dump_exporter(),
        make_poscar_exporter(),
        make_contcar_exporter(),
        make_xdatcar_exporter(),
        make_ase_traj_exporter(),
        make_cif_exporter(),
        make_deepmd_npy_exporter(),
        make_qe_pw_in_exporter(),
        make_ase_db_exporter(),
    ]
