"""Shared parser helpers (MASTER_SPEC Part 3 §2, §5).

Every parser establishes Provenance the same way: it records the source format, the
coordinate system the *source* used, the source units, and appends exactly one
``ConversionRecord(operation="parse")`` to the history (Part 2 §3.9). This module holds
that boilerplate so each format module stays focused on its grammar. It imports only
``schema`` (and the package version), never another parser — the P2 boundary holds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chembridge import __version__
from chembridge.schema import ConversionRecord, Provenance


def utc_now() -> str:
    """Current UTC instant as an ISO-8601 ``...Z`` string (Part 2 §3.9 timestamp form).

    Seconds precision, ``Z`` suffix — matching the worked-example fixtures (Part 2 §8).
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_record(format_id: str) -> ConversionRecord:
    """The single ``operation="parse"`` history entry a successful parse appends (§3.9)."""
    return ConversionRecord(
        timestamp=utc_now(),
        operation="parse",
        source_format=format_id,
        target_format=None,
        tool_version=__version__,
        parser_version=f"{format_id}-parser {__version__}",
        assumptions=[],
    )


def build_provenance(
    *,
    format_id: str,
    filename: str | None,
    original_coordinate_system: str,
    source_units: dict[str, str],
    parse_notes: list[str],
) -> Provenance:
    """Assemble the Provenance for a freshly parsed object, history seeded with the parse
    record (§3.9). ``original_coordinate_system`` is what the *source* used, not what the
    canonical object stores (canonical positions are always Cartesian, §4)."""
    return Provenance(
        source_filename=filename,
        source_format=format_id,
        source_units=source_units,
        original_coordinate_system=original_coordinate_system,
        parse_notes=list(parse_notes),
        history=[parse_record(format_id)],
    )
