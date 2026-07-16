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
from xtalate.sdk.plugins import ExporterPlugin, ParserPlugin
from xtalate.sdk.results import ParseError, ParseIssue, ParseResult
from xtalate.sdk.streaming import (
    FrameStream,
    StreamFrame,
    StreamHeader,
    export_stream,
    materialize,
    parse_as_stream,
    stream_of,
)

__all__ = [
    "CapabilityLevel",
    "ExporterPlugin",
    "FieldCapability",
    "FormatCapabilities",
    "FrameStream",
    "ParseError",
    "ParseIssue",
    "ParseResult",
    "ParserPlugin",
    "StreamFrame",
    "StreamHeader",
    "export_stream",
    "materialize",
    "parse_as_stream",
    "stream_of",
]
