"""Conversion Engine — orchestrates parse → capability diff → recovery → export → report.

Owns the pre-flight diff (Part 3 §4.3), the ``write_plan`` (Part 4 §1), the
``ConversionReport`` (Part 4 §2), and the completeness-invariant runtime assertion
(review §4.5). Delegates all format logic to the parsers/exporters via their
``capabilities()`` declarations. Recovery resolution and the automatic final-step
validation land in M5; M4 is the happy path plus structured refusal.
"""

from __future__ import annotations

from xtalate.conversion.engine import (
    CompletenessInvariantError,
    ConversionEngine,
    ConversionResult,
    build_expected_object,
)
from xtalate.conversion.preflight import (
    PreflightDiff,
    build_preflight,
    capability_path,
)
from xtalate.conversion.report import (
    Assumption,
    ConversionReport,
    PreservedEntry,
    RemovedEntry,
    ReportWarning,
    SuppliedEntry,
)
from xtalate.recovery import UnresolvedScenario

__all__ = [
    "Assumption",
    "CompletenessInvariantError",
    "ConversionEngine",
    "ConversionReport",
    "ConversionResult",
    "PreflightDiff",
    "PreservedEntry",
    "RemovedEntry",
    "ReportWarning",
    "SuppliedEntry",
    "UnresolvedScenario",
    "build_expected_object",
    "build_preflight",
    "capability_path",
]
