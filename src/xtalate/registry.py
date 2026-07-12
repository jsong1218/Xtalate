"""``default_registry()`` — the standard first-party registry (MASTER_SPEC Part 3 §7.1).

A convenience factory that registers every built-in parser and exporter into one
:class:`~xtalate.capabilities.Registry`, so callers (the CLI, examples, and any embedder)
get the full v0.1 format set without hand-wiring it. This is the "explicit first-party
registration list" the spec calls sufficient before entry-point plugin discovery exists
(Part 3 §7.1); third-party plugins attach at the same registry later (**P6**).

Lives at the package root, not in ``capabilities``: the registry *machinery* must not depend on
the concrete parsers/exporters (that would invert the import graph), so the wiring that pulls
them together sits above both — the same reason the CLI, not the engine, composes the pipeline.
"""

from __future__ import annotations

from xtalate.capabilities import Registry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers


def default_registry() -> Registry:
    """A fresh :class:`Registry` with all built-in parsers and exporters registered."""
    registry = Registry()
    for parser in builtin_parsers():
        registry.register_parser(parser)
    for exporter in builtin_exporters():
        registry.register_exporter(exporter)
    return registry
