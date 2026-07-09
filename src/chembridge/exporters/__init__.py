"""Exporters — one ``ExporterPlugin`` per format: Canonical Object → native file (Part 4 §1).

Writes exactly the ``write_plan`` handed to it; never reads native files, calls a
parser, or fabricates absent fields (Part 1 §2, Part 4 §1). Depends on ``schema``
and ``sdk``. Lands alongside its paired parser in M3.

``builtin_exporters()`` mirrors ``parsers.builtin_parsers()`` — a downward-only list a
higher layer assembles into a Registry.
"""

from __future__ import annotations

from chembridge.exporters.extxyz import ExtxyzExporter
from chembridge.exporters.poscar import (
    PoscarExporter,
    make_contcar_exporter,
    make_poscar_exporter,
)
from chembridge.exporters.xyz import XyzExporter
from chembridge.sdk import ExporterPlugin

__all__ = [
    "ExtxyzExporter",
    "PoscarExporter",
    "XyzExporter",
    "builtin_exporters",
    "make_contcar_exporter",
    "make_poscar_exporter",
]


def builtin_exporters() -> list[ExporterPlugin]:
    """The exporters shipped in v0.1 (M3a XYZ, M3b POSCAR/CONTCAR, M3c extXYZ)."""
    return [XyzExporter(), ExtxyzExporter(), make_poscar_exporter(), make_contcar_exporter()]
