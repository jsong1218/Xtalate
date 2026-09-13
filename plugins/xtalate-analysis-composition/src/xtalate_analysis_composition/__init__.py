"""xtalate-analysis-composition — the published reference *analysis* plugin for Xtalate (M69).

A complete, installable third-party analysis plugin built **only** against the frozen public
Plugin SDK (``xtalate.sdk`` + ``xtalate.schema``). It exists to be *copied*: it shows how to
declare an ``AnalysisPlugin``, write only its own ``"composition:"`` namespace, report absence
honestly (P3/P4 — density only where a cell and masses exist), and ship golden cases. Its CI
canary verifies SDK compatibility on every PR, beside ``xtalate-example-format``.
"""

from __future__ import annotations

from xtalate_analysis_composition.analysis import (
    CompositionAnalysis,
    element_counts,
    hill_formula,
)

__all__ = ["CompositionAnalysis", "element_counts", "hill_formula"]
