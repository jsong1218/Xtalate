"""Image-flag export-time prediction (v1.3 M46-S3; Part 3 §4, DECISIONS.md D176).

A wrapped LAMMPS dump plus its ``ix iy iz`` image flags contains everything needed to
reconstruct continuous trajectories; dropping the flags makes unwrapping impossible while the
output *looks* correct — the version's sharpest silent-and-irreversible-loss hazard. These
tests pin the closure: the flags are carried specifically (never applied on parse), a **named**
capability dimension declares them present on ``lammps_dump``-read and absent on every
incumbent target, and the ordinary pre-flight diff fires ``LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT``
— naming the unwrapping consequence, *before* a byte is written — whenever a flag-carrying
source targets a format that cannot hold them. The wrapped+flags fixture and its ``xu``
counterpart prove the carried flags are sufficient: applying them in the *test* (never the
parser) reconstructs the identical unwrapped coordinates.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from xtalate.capabilities import CapabilityMatrix, Registry
from xtalate.conversion import ConversionEngine
from xtalate.conversion.preflight import build_preflight
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_dump"
PARSER = make_lammps_dump_parser()

# The incumbent targets — every currently-possible target, since M46 has no dump exporter.
_INCUMBENT_TARGETS = ["xyz", "extxyz", "poscar", "contcar", "xdatcar"]


def _parse(case: str) -> CanonicalObject:
    return PARSER.parse(
        io.BytesIO((GOLDEN / case / "dump.lammpstrj").read_bytes()), filename="dump.lammpstrj"
    ).canonical


def _registry() -> tuple[Registry, CapabilityMatrix]:
    reg = default_registry()
    return reg, reg.capability_matrix()


# --- the named capability dimension --------------------------------------------------


def test_image_flag_capability_present_on_lammps_dump_read() -> None:
    _, matrix = _registry()
    assert matrix.get("lammps_dump", "read").holds_image_flags is True


@pytest.mark.parametrize("target", _INCUMBENT_TARGETS)
def test_image_flag_capability_absent_on_incumbent_targets(target: str) -> None:
    """The five incumbents cannot hold image flags — the default (absent) declaration, pinned
    here so the prediction's target side cannot silently flip to present."""
    _, matrix = _registry()
    assert matrix.get(target, "write").holds_image_flags is False


# --- the export-time prediction, before a byte is written ----------------------------


@pytest.mark.parametrize("target", _INCUMBENT_TARGETS)
def test_wrapped_flags_to_incumbent_fires_unwrapping_lost(target: str) -> None:
    """Converting a flag-carrying dump to any incumbent target fires the prediction from the
    ordinary pre-flight diff — the capability comparison, before any exporter runs."""
    _, matrix = _registry()
    source = _parse("wrapped-flags-metal")
    diff = build_preflight(source, matrix, target, source_format_id="lammps_dump")
    codes = [w.code for w in diff.warnings]
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" in codes
    message = next(
        w.message for w in diff.warnings if w.code == "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT"
    )
    assert "can no longer be unwrapped" in message
    assert target in message


@pytest.mark.parametrize("target", _INCUMBENT_TARGETS)
def test_xu_counterpart_to_incumbent_does_not_fire(target: str) -> None:
    """The unwrapped xu counterpart carries no flags, so no prediction fires — nothing is lost."""
    _, matrix = _registry()
    source = _parse("xu-counterpart-metal")
    diff = build_preflight(source, matrix, target, source_format_id="lammps_dump")
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" not in {w.code for w in diff.warnings}


def test_prediction_lands_in_the_conversion_report() -> None:
    """End to end through the engine: the warning rides the ordinary Conversion Report."""
    reg = default_registry()
    source = _parse("wrapped-flags-metal")
    result = ConversionEngine(reg).convert(
        source, source_format_id="lammps_dump", target_format_id="xyz"
    )
    assert result.report.status == "completed"
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" in {w.code for w in result.report.warnings}


def test_prediction_does_not_fire_for_a_non_flag_source() -> None:
    """A declared-metal orthogonal dump (no image flags) targets an incumbent with no warning —
    the prediction is about the object actually carrying flags, not the format alone."""
    _, matrix = _registry()
    source = _parse("metal-ortho-declared")
    diff = build_preflight(source, matrix, "xyz", source_format_id="lammps_dump")
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" not in {w.code for w in diff.warnings}


def test_dump_target_holds_flags_and_only_needs_units_recovery() -> None:
    """S2's write capability and behavior close the dump-to-dump seam: image-flag loss is no
    longer predicted, while the target-driven units scenario remains required."""
    _, matrix = _registry()
    source = _parse("wrapped-flags-metal")
    diff = build_preflight(source, matrix, "lammps_dump", source_format_id="lammps_dump")
    assert "LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT" not in {w.code for w in diff.warnings}
    assert [scenario.scenario for scenario in diff.unresolved].count("ambiguous_units") == 1


# --- the correctness proof: flags are sufficient to unwrap ---------------------------


def test_wrapped_flags_and_xu_counterpart_reconstruct_identically() -> None:
    """The wrapped+flags fixture and its xu counterpart describe the same physical trajectory:
    applying the flags in the test (wrapped + flags·cell) reproduces the xu positions exactly.
    The parser never applies them — the test owns the unwrap arithmetic."""
    wrapped = _parse("wrapped-flags-metal")
    xu = _parse("xu-counterpart-metal")
    flags = wrapped.user_metadata.custom_per_atom["lammps_dump:image_flags"]
    assert np.asarray(flags).shape == (2, 3)
    # The wrapped positions are still wrapped (the parser did not unwrap).
    assert wrapped.frames[0].atoms.positions[1].tolist() == [0.5, 0.5, 0.5]
    cell = wrapped.frames[0].cell
    assert cell is not None
    lengths = np.diag(cell.lattice_vectors)
    reconstructed = wrapped.frames[0].atoms.positions + np.asarray(flags) * lengths
    np.testing.assert_allclose(reconstructed, xu.frames[0].atoms.positions)
