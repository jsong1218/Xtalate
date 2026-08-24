"""Conversion Engine — orchestrates parse → capability diff → recovery → export → report.

Owns the pre-flight diff (Part 3 §4.3), the ``write_plan`` (Part 4 §1), the
``ConversionReport`` (Part 4 §2), and the completeness-invariant runtime assertion
(review §4.5). Delegates all format logic to the parsers/exporters via their
``capabilities()`` declarations. Recovery resolution and the automatic final-step
validation land in M5; M4 is the happy path plus structured refusal.
"""

from __future__ import annotations

from xtalate.conversion.batch import (
    BatchEntry,
    BatchError,
    BatchManifest,
    BatchManifestError,
    BatchReport,
    BatchTallies,
    LabelPresence,
    SourceEntry,
    SourceOverride,
    load_manifest,
    parse_recovery_presets,
    run_batch,
)
from xtalate.conversion.engine import (
    CompletenessInvariantError,
    ConversionEngine,
    ConversionResult,
    RecoveryPreview,
    build_expected_object,
)
from xtalate.conversion.parse_recovery import ParseRecovery, parse_with_recovery
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

# Re-exported: the conversion package is ``FrameLimitExceeded``'s named home (M39-S3).
from xtalate.sdk import FrameLimitExceeded

__all__ = [
    "Assumption",
    "BatchEntry",
    "BatchError",
    "BatchManifest",
    "BatchManifestError",
    "BatchReport",
    "BatchTallies",
    "CompletenessInvariantError",
    "ConversionEngine",
    "ConversionReport",
    "ConversionResult",
    "FrameLimitExceeded",
    "LabelPresence",
    "ParseRecovery",
    "PreflightDiff",
    "PreservedEntry",
    "RecoveryPreview",
    "RemovedEntry",
    "ReportWarning",
    "SourceEntry",
    "SourceOverride",
    "SuppliedEntry",
    "UnresolvedScenario",
    "build_expected_object",
    "build_preflight",
    "capability_path",
    "load_manifest",
    "parse_recovery_presets",
    "parse_with_recovery",
    "run_batch",
]
