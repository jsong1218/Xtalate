"""Plugin SDK — parser/exporter ABCs, error contract, and capability data model.

Publishes ``ParserPlugin``/``ExporterPlugin`` (Part 3 §2), ``ParseResult``/
``ParseIssue``/``ParseError`` (Part 3 §5), and the ``FormatCapabilities``/
``FieldCapability``/``CapabilityLevel`` data model (Part 3 §4.1, placed here per
Revision 1.2 so a plugin can declare capabilities without importing the registry).
Depends only on ``schema``. Implemented in M2.
"""

from xtalate.sdk.capabilities import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
)
from xtalate.sdk.deepmd import stress_from_virial, virial_from_stress
from xtalate.sdk.image_flags import IMAGE_FLAGS_CARRY_KEY
from xtalate.sdk.plugins import ExporterPlugin, ParserPlugin
from xtalate.sdk.results import (
    AssembleContribution,
    ExporterWarning,
    FrameLimitExceeded,
    ParseError,
    ParseIssue,
    ParseResult,
    collapse_frame_issues,
)
from xtalate.sdk.streaming import (
    FrameStream,
    StreamFrame,
    StreamHeader,
    enforce_max_frames,
    export_stream,
    materialize,
    parse_as_stream,
    stream_of,
)
from xtalate.sdk.stress_carries import STRESS_CARRY_KEYS

__all__ = [
    "AssembleContribution",
    "CapabilityLevel",
    "ExporterPlugin",
    "FieldCapability",
    "FormatCapabilities",
    "FrameLimitExceeded",
    "FrameStream",
    "ExporterWarning",
    "IMAGE_FLAGS_CARRY_KEY",
    "ParseError",
    "ParseIssue",
    "ParseResult",
    "ParserPlugin",
    "STRESS_CARRY_KEYS",
    "stress_from_virial",
    "virial_from_stress",
    "StreamFrame",
    "StreamHeader",
    "collapse_frame_issues",
    "enforce_max_frames",
    "export_stream",
    "materialize",
    "parse_as_stream",
    "stream_of",
]
