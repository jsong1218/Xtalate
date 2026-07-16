"""The one UTC-timestamp helper, shared across layers.

Provenance history entries (parse/recovery/convert) and the report ``created_at`` fields all stamp
the same ISO-8601 ``...Z`` form (Part 2 §3.9). This lived as a copied ``strftime`` string in four
modules; centralising it here removes the drift hazard and gives one place to change the precision
if the schema ever does. It is a root-level cross-cutting utility (like ``xtalate.registry``),
outside the import-linter layer graph, so any layer may import it without touching the P2 contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: The provenance/report timestamp format: seconds precision, ``Z`` suffix (Part 2 §3.9, §8).
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> str:
    """Current UTC instant as an ISO-8601 ``...Z`` string (Part 2 §3.9 timestamp form)."""
    return datetime.now(UTC).strftime(_ISO_Z)
