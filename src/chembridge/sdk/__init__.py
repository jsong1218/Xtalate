"""Plugin SDK — parser/exporter ABCs, error contract, and capability data model.

Publishes ``ParserPlugin``/``ExporterPlugin`` (Part 3 §2), ``ParseResult``/
``ParseIssue``/``ParseError`` (Part 3 §5), and the ``FormatCapabilities``/
``FieldCapability``/``CapabilityLevel`` data model (Part 3 §4.1, placed here per
Revision 1.2 so a plugin can declare capabilities without importing the registry).
Depends only on ``schema``. Populated in M2.
"""
