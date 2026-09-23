"""Shared parser helpers (MASTER_SPEC Part 3 §2, §5).

Every parser establishes Provenance the same way: it records the source format, the
coordinate system the *source* used, the source units, and appends exactly one
``ConversionRecord(operation="parse")`` to the history (Part 2 §3.9). This module holds
that boilerplate so each format module stays focused on its grammar. It imports only
``schema`` (and the package version), never another parser — the P2 boundary holds.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from xtalate import __version__
from xtalate._time import utc_now as _utc_now
from xtalate.schema import ConversionRecord, Frame, Provenance
from xtalate.sdk import ParseError, ParseIssue

# Coerce a raw per-atom column set exactly as the ``Frame.custom_per_atom`` field would (the
# left-to-right union: numeric input → ndarray, non-numeric → list — D12), driven off the field's
# own annotation so it can never drift from the model.
_PER_ATOM_ADAPTER: TypeAdapter[dict[str, Any]] = TypeAdapter(
    Frame.model_fields["custom_per_atom"].annotation
)


def decode_text(data: bytes, *, format_id: str) -> str:
    """Decode a source file's bytes as UTF-8, turning a decode failure into a ``ParseError`` (§5).

    A non-text file handed to a text parser (directly or via a ``--format`` override) must fail
    through the same structured error contract as any other malformed input — a raw
    ``UnicodeDecodeError`` would escape the ParseResult/ParseError boundary and surface as an
    uncaught traceback in the CLI and API. The offending byte offset is named so the report is
    actionable."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(
            [
                ParseIssue(
                    severity="error",
                    code=f"{format_id.upper()}_ENCODING_ERROR",
                    message=(
                        f"file is not valid UTF-8 text (byte 0x{data[exc.start]:02x} at offset "
                        f"{exc.start}); {format_id} is a text format"
                    ),
                    location=f"byte {exc.start}",
                )
            ]
        ) from exc


def utc_now() -> str:
    """Current UTC instant as an ISO-8601 ``...Z`` string (Part 2 §3.9 timestamp form).

    Re-exported from :mod:`xtalate._time` (the single source) under the name parser code already
    imports; seconds precision, ``Z`` suffix — matching the worked-example fixtures (Part 2 §8).
    """
    return _utc_now()


def parse_record(format_id: str, *, parser_version: str | None = None) -> ConversionRecord:
    """The single ``operation="parse"`` history entry a successful parse appends (§3.9).

    ``parser_version`` overrides the default ``"<fmt>-parser <ver>"`` string. A parser that wraps a
    versioned scientific dependency (the ase_traj parser wraps ASE, M14) folds that dependency's
    version in here — ``"ase_traj-parser 0.2.0 (ase 3.29.0)"`` — so a pin bump that changes parse
    behaviour is visible in every report's Provenance (Part 2 §3.9), not silently absorbed."""
    return ConversionRecord(
        timestamp=utc_now(),
        operation="parse",
        source_format=format_id,
        target_format=None,
        tool_version=__version__,
        parser_version=parser_version or f"{format_id}-parser {__version__}",
        assumptions=[],
    )


def coerce_per_atom(custom_per_atom: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw per-atom column set once, exactly as ``Frame.custom_per_atom`` would (numeric →
    ndarray, non-numeric → list, D12). A streaming parser establishes one frame-invariant column set
    and attaches it onto every ``StreamFrame.frame`` (:func:`with_per_atom`); coercing once here,
    rather than per frame, keeps that cost off the frame loop. An empty set coerces to ``{}``."""
    if not custom_per_atom:
        return {}
    return dict(_PER_ATOM_ADAPTER.validate_python(dict(custom_per_atom)))


def with_per_atom(frame: Frame, coerced: dict[str, Any]) -> Frame:
    """Attach an *already-coerced* per-atom column set onto one ``Frame`` (schema 2.0.0, M72/M73).

    Every parser writes ``custom_per_atom`` per frame — each ``StreamFrame.frame`` (and each
    materialized ``Frame``) carries its own column set, collected from that frame's own arrays and
    validated against that frame's N (Part 2 §3.10; the M73 ``StreamHeader`` relocation, extended in
    the v2.0 review so a column that varies across a constant-N trajectory is lossless too).
    ``model_copy(update=...)`` skips validation, so ``coerced`` must already be a coerced set from
    :func:`coerce_per_atom`. Each frame gets its own dict so a per-frame mutation cannot alias
    another frame's columns. An empty set leaves the frame untouched."""
    if not coerced:
        return frame
    return frame.model_copy(update={"custom_per_atom": dict(coerced)})


def build_provenance(
    *,
    format_id: str,
    filename: str | None,
    original_coordinate_system: str,
    source_units: dict[str, str],
    parse_notes: list[str],
    parser_version: str | None = None,
) -> Provenance:
    """Assemble the Provenance for a freshly parsed object, history seeded with the parse
    record (§3.9). ``original_coordinate_system`` is what the *source* used, not what the
    canonical object stores (canonical positions are always Cartesian, §4). ``parser_version``
    overrides the default parser-version string for a parser that folds a wrapped dependency's
    version in (see ``parse_record``; ase_traj records the ASE version, M14 deliverable 3)."""
    return Provenance(
        source_filename=filename,
        source_format=format_id,
        source_units=source_units,
        original_coordinate_system=original_coordinate_system,
        parse_notes=list(parse_notes),
        history=[parse_record(format_id, parser_version=parser_version)],
    )
