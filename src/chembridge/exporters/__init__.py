"""Exporters — one ``ExporterPlugin`` per format: Canonical Object → native file (Part 4 §1).

Writes exactly the ``write_plan`` handed to it; never reads native files, calls a
parser, or fabricates absent fields (Part 1 §2, Part 4 §1). Depends on ``schema``
and ``sdk``. Lands alongside its paired parser in M3.
"""
