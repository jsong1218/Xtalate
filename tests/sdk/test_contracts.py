"""SDK contract shapes: capability model, error contract, ABC enforcement (Part 3 §2/§4/§5)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from pydantic import ValidationError

from xtalate.schema import AtomsBlock, CanonicalObject, Frame, Provenance
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)


def _obj() -> CanonicalObject:
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=["O"], positions=np.array([[0.0, 0.0, 0.0]])),
            )
        ],
        provenance=Provenance(
            source_filename=None, source_format="xyz", original_coordinate_system="cartesian"
        ),
    )


# --- capability model ----------------------------------------------------------------


def test_format_capabilities_constructs() -> None:
    caps = FormatCapabilities(
        format_id="poscar",
        format_name="VASP POSCAR",
        direction="write",
        fields={"atoms.positions": FieldCapability(level=CapabilityLevel.FULL)},
        max_frames=1,
        required_fields=["atoms.symbols", "atoms.positions", "cell.lattice_vectors"],
        native_coordinate_system="both",
    )
    assert caps.fields["atoms.positions"].level is CapabilityLevel.FULL
    assert caps.max_frames == 1


def test_capability_level_serializes_as_string() -> None:
    fc = FieldCapability(level=CapabilityLevel.PARTIAL, notes="conditional")
    assert fc.model_dump(mode="json")["level"] == "partial"


def test_bad_direction_rejected() -> None:
    with pytest.raises(ValidationError):
        FormatCapabilities(
            format_id="x",
            format_name="X",
            direction="sideways",  # type: ignore[arg-type]
            native_coordinate_system="cartesian",
        )


# --- error contract ------------------------------------------------------------------


def test_parse_result_defaults_to_no_issues() -> None:
    result = ParseResult(canonical=_obj())
    assert result.issues == []


def test_parse_error_requires_an_error_issue() -> None:
    warning_only = [ParseIssue(severity="warning", code="W", message="just a warning")]
    with pytest.raises(ValueError, match="at least one error-severity"):
        ParseError(warning_only)


def test_parse_error_carries_issues_and_message() -> None:
    issues = [
        ParseIssue(severity="warning", code="W", message="odd"),
        ParseIssue(
            severity="error", code="XYZ_BAD", message="declared 64, found 63", location="frame 17"
        ),
    ]
    err = ParseError(issues)
    assert err.issues == issues
    assert "declared 64" in str(err)


# --- ABC enforcement -----------------------------------------------------------------


def test_parser_plugin_is_abstract() -> None:
    with pytest.raises(TypeError):
        ParserPlugin()  # type: ignore[abstract]


def test_exporter_plugin_is_abstract() -> None:
    with pytest.raises(TypeError):
        ExporterPlugin()  # type: ignore[abstract]


def test_concrete_parser_can_be_instantiated() -> None:
    class Dummy(ParserPlugin):
        format_id = "dummy"
        format_name = "Dummy"
        version = "0.1.0"

        def sniff(self, head: bytes, filename: str | None) -> float:
            return 0.0

        def parse(self, stream: io.BufferedIOBase, *, filename: str | None) -> ParseResult:  # type: ignore[override]
            return ParseResult(canonical=_obj())

        def capabilities(self) -> FormatCapabilities:
            return FormatCapabilities(
                format_id=self.format_id,
                format_name=self.format_name,
                direction="read",
                native_coordinate_system="cartesian",
            )

    assert Dummy().capabilities().format_id == "dummy"
