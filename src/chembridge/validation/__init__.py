"""Validation Engine — re-parse the output and check the Conversion Report told the truth.

Not "nothing was lost" but "everything claimed preserved is present and faithful, everything
claimed removed is absent, and nothing unmentioned happened" (Part 5 §1). Emits the
``ValidationReport`` (Part 5 §3) under a named tolerance profile (Part 5 §4). Implemented in M5.

Layering: sits below ``conversion`` in the import graph — it reads the Conversion Report through
the structural :class:`ConversionReportView` Protocol, never importing ``conversion``.
"""

from __future__ import annotations

from chembridge.validation.engine import ConversionReportView, ValidationEngine
from chembridge.validation.report import CheckResult, ValidationReport
from chembridge.validation.rethreshold import rethreshold
from chembridge.validation.tolerance import ToleranceProfile

__all__ = [
    "CheckResult",
    "ConversionReportView",
    "ToleranceProfile",
    "ValidationEngine",
    "ValidationReport",
    "rethreshold",
]
