"""Parsers — one ``ParserPlugin`` per format: native file → Canonical Object (Part 3).

Never reads another format, calls another parser, writes files, or defaults an
absent field (Part 1 §2, Part 2 §2). Depends on ``schema`` and ``sdk``.
XYZ in M3a, POSCAR/CONTCAR in M3b, extXYZ in M3c.
"""
