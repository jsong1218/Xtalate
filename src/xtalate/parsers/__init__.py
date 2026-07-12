"""Parsers — one ``ParserPlugin`` per format: native file → Canonical Object (Part 3).

Never reads another format, calls another parser, writes files, or defaults an
absent field (Part 1 §2, Part 2 §2). Depends on ``schema`` and ``sdk``.
XYZ in M3a, POSCAR/CONTCAR in M3b, extXYZ in M3c.

``builtin_parsers()`` is a pure list of the v0.1 parsers a higher layer (discovery /
conversion) assembles into a Registry — it lives here, in the parsers layer, so that
assembly imports *downward* only and the P2 import contract holds.
"""

from __future__ import annotations

from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.parsers.poscar import PoscarParser, make_contcar_parser, make_poscar_parser
from xtalate.parsers.xyz import XyzParser
from xtalate.sdk import ParserPlugin

__all__ = [
    "ExtxyzParser",
    "PoscarParser",
    "XyzParser",
    "builtin_parsers",
    "make_contcar_parser",
    "make_poscar_parser",
]


def builtin_parsers() -> list[ParserPlugin]:
    """The parsers shipped in v0.1 (M3a XYZ, M3b POSCAR/CONTCAR, M3c extXYZ)."""
    return [XyzParser(), ExtxyzParser(), make_poscar_parser(), make_contcar_parser()]
