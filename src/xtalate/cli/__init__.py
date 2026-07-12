"""Xtalate CLI — a thin presenter over the engines (MASTER_SPEC Appendix A).

Contains no scientific logic; emits the report schemas of Parts 3-5 verbatim as JSON (``--json``)
or renders them as a terminal inventory, and honors the preset-only recovery model (Part 10 §2).
The command implementations live in :mod:`xtalate.cli.main`; this package exposes the
console-script entry point ``xtalate``.
"""

from xtalate.cli.main import main

__all__ = ["main"]
