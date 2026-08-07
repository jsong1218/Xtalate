"""xtalate-example-format — the published reference plugin for Xtalate (M36).

A complete, installable third-party plugin for one deliberately small format, ``exfmt``,
built **only** against the frozen public Plugin SDK (``xtalate.sdk`` + ``xtalate.schema``).
It exists to be *copied*: it shows how to package a parser and exporter, declare capabilities
**honestly** (``exfmt`` reads a per-frame label it cannot write back, so that label is reported
``removed`` on conversion — the "PARTIAL/NONE beats optimistic FULL" lesson), and ship golden
cases with licensed manifests.

Two roles that look similar but are not: ``tests/fixtures/xtalate_toyfmt`` in the parent repo is
a *hidden discovery fixture* (its tests skip when absent; it is not in the nightly matrix). This
distribution is the *published reference* whose SDK-compatibility CI verifies on every PR — the
compatibility canary — and which participates in the round-trip matrix.
"""

from __future__ import annotations

from xtalate_examplefmt.exporter import ExampleFormatExporter
from xtalate_examplefmt.parser import ExampleFormatParser

__all__ = ["ExampleFormatExporter", "ExampleFormatParser"]
