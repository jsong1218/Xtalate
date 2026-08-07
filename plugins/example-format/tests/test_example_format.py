"""Contract tests for the xtalate-example-format reference plugin (``exfmt``, M36).

These run against the *installed* plugin, discovered through ``default_registry()`` exactly as a
real deployment would find it — so they prove the whole path (entry-point discovery → Canonical
Model → conversion), not just the classes in isolation. They are the plugin's contract, and the
CI compatibility canary (S2) makes them a hard gate: a core change that breaks exfmt's
parse/export/capabilities fails the parent build here.

Self-contained by design: the golden cases and their licensed manifests live inside this
distribution, so nothing here touches the parent repo's golden-corpus governance (which scans
only ``tests/golden/``).
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from xtalate_examplefmt.parser import ExampleFormatParser

from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

GOLDEN = Path(__file__).parent / "golden" / "exfmt"
CASES = ["water-monomer", "labeled-methane"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry():
    return default_registry()


# --- discovery -----------------------------------------------------------------------------


def test_exfmt_is_discovered_as_parser_and_exporter() -> None:
    """The installed plugin registers on both sides, additively — the built-ins are untouched."""
    registry = _registry()
    parser_ids = {p.format_id for p in registry.parsers()}
    exporter_ids = {e.format_id for e in registry.exporters()}
    assert "exfmt" in parser_ids
    assert "exfmt" in exporter_ids
    assert {"xyz", "poscar"} <= parser_ids  # built-ins still present (P6)


def test_exfmt_capabilities_are_queryable_in_the_matrix() -> None:
    matrix = _registry().capability_matrix()
    assert matrix.get("exfmt", "read").format_id == "exfmt"
    assert matrix.get("exfmt", "write").format_id == "exfmt"


# --- golden parsing + manifest governance --------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_golden_hashes_match_manifest(case: str) -> None:
    """Mirror the parent's golden discipline: every data file is claimed by a manifest whose
    recorded hashes match the bytes on disk (no drift, no unclaimed file)."""
    manifest = yaml.safe_load((GOLDEN / case / "manifest.yaml").read_text())
    source = GOLDEN / case / manifest["source_file"]
    expected = GOLDEN / case / manifest["expected_canonical"]
    assert _sha256(source) == manifest["sha256"]
    assert _sha256(expected) == manifest["expected_sha256"]
    assert manifest["canonical_schema_version"] == "1.0.0"
    assert manifest["origin"]["license"] == "Apache-2.0"


@pytest.mark.parametrize("case", CASES)
def test_golden_parses_to_expected_canonical(case: str) -> None:
    """The discovered parser turns each source into the hand-verified Canonical Object."""
    manifest = yaml.safe_load((GOLDEN / case / "manifest.yaml").read_text())
    source = GOLDEN / case / manifest["source_file"]
    expected = json.loads((GOLDEN / case / manifest["expected_canonical"]).read_text())
    parser = _registry().get_parser("exfmt")
    with source.open("rb") as fh:
        result = parser.parse(fh, filename=manifest["source_file"])
    assert result.canonical.model_dump(mode="json") == expected


def test_label_is_read_into_custom_per_frame() -> None:
    parser = _registry().get_parser("exfmt")
    with (GOLDEN / "labeled-methane" / "labeled_methane.exfmt").open("rb") as fh:
        obj = parser.parse(fh, filename="labeled_methane.exfmt").canonical
    assert obj.user_metadata.custom_per_frame["exfmt:label"] == ["methane, tetrahedral geometry"]


# --- absence convention (P3): the parser defaults nothing ----------------------------------


def test_absent_fields_are_none_not_defaulted() -> None:
    parser = _registry().get_parser("exfmt")
    with (GOLDEN / "water-monomer" / "water_monomer.exfmt").open("rb") as fh:
        obj = parser.parse(fh, filename="water_monomer.exfmt").canonical
    frame = obj.frames[0]
    assert frame.cell is None
    assert frame.dynamics.velocities is None
    assert frame.dynamics.forces is None
    assert frame.dynamics.constraints is None
    assert frame.electronic.total_energy is None
    assert frame.atoms.masses is None
    assert frame.atoms.occupancies is None
    assert obj.trajectory is None
    assert obj.simulation is None
    # A file with no label carries no label key — absence, not an empty string (P3).
    assert obj.user_metadata.custom_per_frame == {}


# --- identity round-trip (label-free) ------------------------------------------------------


def test_label_free_identity_round_trip_is_byte_stable() -> None:
    """exfmt -> Canonical -> exfmt preserves geometry exactly and is byte-stable for the
    label-free case (the only case that round-trips without loss)."""
    registry = _registry()
    parser = registry.get_parser("exfmt")
    exporter = registry.get_exporter("exfmt")
    with (GOLDEN / "water-monomer" / "water_monomer.exfmt").open("rb") as fh:
        obj = parser.parse(fh, filename="water_monomer.exfmt").canonical

    buf = io.BytesIO()
    exporter.export(obj, buf)
    written = buf.getvalue()

    reparsed = parser.parse(io.BytesIO(written), filename="out.exfmt").canonical
    assert reparsed.frames[0].atoms.symbols == obj.frames[0].atoms.symbols
    np.testing.assert_array_equal(reparsed.frames[0].atoms.positions, obj.frames[0].atoms.positions)
    # Second export of the re-parsed object is identical — no drift.
    buf2 = io.BytesIO()
    exporter.export(reparsed, buf2)
    assert buf2.getvalue() == written


# --- the honest loss: the label is reported `removed`, never silently dropped --------------


def test_label_is_reported_removed_on_conversion() -> None:
    """The whole point of the reference plugin: converting a labeled exfmt reports the label
    `removed` (with its reason), never dropping it silently (P1)."""
    registry = _registry()
    parser = registry.get_parser("exfmt")
    engine = ConversionEngine(registry)
    with (GOLDEN / "labeled-methane" / "labeled_methane.exfmt").open("rb") as fh:
        obj = parser.parse(fh, filename="labeled_methane.exfmt").canonical

    result = engine.convert(
        obj,
        source_format_id="exfmt",
        target_format_id="exfmt",
        source_filename="labeled_methane.exfmt",
    )
    assert result.report.status == "completed"
    removed = {r.path for r in result.report.removed}
    assert "user_metadata.custom_per_frame['exfmt:label']" in removed
    reason = next(r.reason for r in result.report.removed if "exfmt:label" in r.path)
    assert "read-only" in reason  # the honest, human-readable explanation


# --- error contract: malformed input raises attributed ParseErrors -------------------------


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"NOTEXFMT\nO 0.0 0.0 0.0\n", "EXFMT_BAD_MAGIC"),
        (b"EXFMT 1\n", "EXFMT_EMPTY"),
        (b"EXFMT 1\nO 0.0 0.0\n", "EXFMT_MALFORMED_ATOM"),
        (b"EXFMT 1\nO x y z\n", "EXFMT_MALFORMED_COORDINATE"),
    ],
)
def test_malformed_input_raises_attributed_parse_error(payload: bytes, code: str) -> None:
    parser = ExampleFormatParser()
    with pytest.raises(ParseError) as excinfo:
        parser.parse(io.BytesIO(payload), filename="bad.exfmt")
    assert any(issue.code == code for issue in excinfo.value.issues)
