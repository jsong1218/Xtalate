"""Validation Engine tests (M5, MASTER_SPEC Part 5 §2, §6).

Two pillars:

* **Worked example (Part 5 §6).** A multi-frame, no-lattice water XYZ → POSCAR with the §5 choices
  (select a frame, fabricate a bounding-box lattice) reproduces the spec's Validation Report shape:
  every check passes or is explicitly skipped, and the aggregate is ``passed``. This is the
  "spec and code agree" checkpoint of the M5 plan.
* **Negative tests (deliverable 7).** A deliberately broken POSCAR exporter — perturbed positions,
  a dropped atom, a swapped species — is caught by the corresponding check, turning the aggregate
  ``failed``. This proves validation has teeth: the re-parse through the independent read path
  detects an exporter that lies.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, cast

from chembridge.capabilities import Registry
from chembridge.conversion import ConversionEngine
from chembridge.conversion.engine import ConversionResult
from chembridge.exporters import builtin_exporters
from chembridge.exporters.poscar import PoscarExporter
from chembridge.parsers import builtin_parsers
from chembridge.schema import AtomsBlock, CanonicalObject
from chembridge.validation import CheckResult

GOLDEN = Path(__file__).parent.parent / "golden"

_RECOVERY = {
    "frame_selection": {"choice": "index", "parameters": {"frame_index": 1}},
    "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
}


def _registry(*, exporter: PoscarExporter | None = None) -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exp in builtin_exporters():
        # Substitute a broken poscar exporter when one is supplied (same format_id).
        if exporter is not None and exp.format_id == "poscar":
            continue
        reg.register_exporter(exp)
    if exporter is not None:
        reg.register_exporter(exporter)
    return reg


def _source(reg: Registry) -> CanonicalObject:
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    return reg.get_parser("xyz").parse(io.BytesIO(data), filename="w.xyz").canonical


def _check(result: ConversionResult, check_id: str) -> CheckResult:
    assert result.validation is not None
    return next(c for c in result.validation.checks if c.check_id == check_id)


# --- worked example (Part 5 §6) ------------------------------------------------------------------


def test_worked_example_validation_passes() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _source(reg),
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices=_RECOVERY,
    )
    assert result.report.status == "completed"
    vr = result.validation
    assert vr is not None
    assert vr.conversion_report_id == result.report.report_id
    assert vr.status == "passed"

    # Every catalog check present exactly once (Part 5 §2), skips reported not omitted (§3).
    ids = [c.check_id for c in vr.checks]
    assert set(ids) == {
        "atom_count",
        "species_preservation",
        "positions_rmsd",
        "lattice_consistency",
        "frame_count",
        "numeric_field_fidelity",
        "metadata_preservation",
        "absence_conformance",
        "report_consistency",
    }


def test_worked_example_check_outcomes_match_spec() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _source(reg), source_format_id="xyz", target_format_id="poscar", recovery_choices=_RECOVERY
    )

    assert _check(result, "atom_count").status == "pass"
    assert _check(result, "atom_count").measured["found"] == 3

    species = _check(result, "species_preservation")
    assert species.status == "pass"
    assert species.measured["mismatches"] == 0

    rmsd = _check(result, "positions_rmsd")
    assert rmsd.status == "pass"
    assert cast(float, rmsd.measured["rmsd_ang"]) < 1e-6  # full-precision Cartesian round-trip.

    lattice = _check(result, "lattice_consistency")
    assert lattice.status == "pass"
    assert lattice.measured["pbc_found"] == [True, True, True]

    assert _check(result, "frame_count").measured == {"expected": 1, "found": 1}

    # No numeric fields beyond positions/lattice survived the write plan -> explicit skip (§6).
    fidelity = _check(result, "numeric_field_fidelity")
    assert fidelity.status == "skipped"
    assert fidelity.skip_reason is not None

    # The dropped per-frame comment is verified absent; positions are NOT asserted absent (they are
    # preserved for the retained frame and validated by frame_count).
    absence = _check(result, "absence_conformance")
    assert absence.status == "pass"
    assert absence.measured["violations"] == 0

    consistency = _check(result, "report_consistency")
    assert consistency.status == "pass"
    assert consistency.measured["untraceable_deltas"] == 0
    assert consistency.measured["supplied_traced"] == 2  # cell.lattice_vectors + cell.pbc trace A2.

    assert result.validation is not None
    assert result.validation.tolerance_profile["name"] == "default"


# --- negative tests: a broken exporter is caught (deliverable 7) ----------------------------------


class _PerturbPositions(PoscarExporter):
    """Shifts every atom 0.5 Å on x — far above the 1e-3 Å fail tolerance."""

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        f = canonical.frames[0]
        bad = f.atoms.positions.copy()
        bad[:, 0] += 0.5
        atoms = AtomsBlock(symbols=list(f.atoms.symbols), positions=bad, masses=f.atoms.masses)
        broken = canonical.model_copy(update={"frames": [f.model_copy(update={"atoms": atoms})]})
        super().export(broken, stream)


class _DropAtom(PoscarExporter):
    """Writes one fewer atom than the plan — the most catastrophic conversion bug (§2)."""

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        f = canonical.frames[0]
        atoms = AtomsBlock(
            symbols=list(f.atoms.symbols)[:-1],
            positions=f.atoms.positions[:-1],
            masses=None,
        )
        broken = canonical.model_copy(update={"frames": [f.model_copy(update={"atoms": atoms})]})
        super().export(broken, stream)


class _SwapSpecies(PoscarExporter):
    """Relabels the oxygen as nitrogen — counts intact, chemistry corrupted (§2)."""

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        f = canonical.frames[0]
        symbols = list(f.atoms.symbols)
        symbols[0] = "N"
        atoms = AtomsBlock(symbols=symbols, positions=f.atoms.positions, masses=f.atoms.masses)
        broken = canonical.model_copy(update={"frames": [f.model_copy(update={"atoms": atoms})]})
        super().export(broken, stream)


def _broken_result(exporter: PoscarExporter) -> ConversionResult:
    reg = _registry(exporter=exporter)
    return ConversionEngine(reg).convert(
        _source(reg), source_format_id="xyz", target_format_id="poscar", recovery_choices=_RECOVERY
    )


def test_perturbed_positions_fail_positions_rmsd() -> None:
    result = _broken_result(_PerturbPositions())
    assert result.validation is not None
    assert result.validation.status == "failed"
    rmsd = _check(result, "positions_rmsd")
    assert rmsd.status == "fail"
    assert cast(float, rmsd.measured["rmsd_ang"]) > 1e-3


def test_dropped_atom_fails_atom_count() -> None:
    result = _broken_result(_DropAtom())
    assert result.validation is not None
    assert result.validation.status == "failed"
    assert _check(result, "atom_count").status == "fail"


def test_swapped_species_fails_species_preservation() -> None:
    result = _broken_result(_SwapSpecies())
    assert result.validation is not None
    assert result.validation.status == "failed"
    species = _check(result, "species_preservation")
    assert species.status == "fail"
    assert cast(int, species.measured["mismatches"]) >= 1


def test_strict_tolerance_still_passes_a_faithful_conversion() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _source(reg),
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices=_RECOVERY,
        tolerance_profile="strict",
    )
    # A full-precision Cartesian round-trip is exact, so it passes even the 100×-tighter bar.
    assert result.validation is not None
    assert result.validation.status == "passed"
    assert result.validation.tolerance_profile["name"] == "strict"
