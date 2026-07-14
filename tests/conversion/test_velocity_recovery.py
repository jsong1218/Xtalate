"""End-to-end velocity/mass recovery (M8, MASTER_SPEC Part 4 §3.3).

Covers the opt-in on-demand fabricative wiring (a user-supplied `missing_velocities` choice becomes
a scenario only when requested, only for a target that can store the field, and never over a
source that already has it — P4), the flagship done-criterion (extXYZ trajectory → POSCAR with a
Maxwell–Boltzmann velocity block, byte-identical on re-run), and the `maxwell_boltzmann →
missing_masses` chain producing two Assumptions (or refusing when masses are absent and no
`missing_masses` choice is supplied).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.recovery import RecoveryError
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden"

# A two-frame extXYZ carrying masses but no Lattice and no velocities — the done-criterion source:
# masses are present (so Maxwell–Boltzmann reads them, no chain), a lattice must be fabricated
# (missing_lattice) and the trajectory reduced to one frame (frame_selection).
_TRAJ_WITH_MASSES = (
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.1 0.0 0.0 15.999\n"
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.25 0.0 0.0 15.999\n"
)

# A CONTCAR that already carries a velocity block, for the P4 (source-has-velocities) guard.
_CONTCAR_WITH_VEL = (
    b"md\n1.0\n  4.0 0.0 0.0\n  0.0 4.0 0.0\n  0.0 0.0 4.0\n"
    b"H\n1\nDirect\n  0.0 0.0 0.0\n\nCartesian\n  0.1 0.2 0.3\n"
)


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _parse(reg: Registry, format_id: str, data: bytes, filename: str) -> CanonicalObject:
    return reg.get_parser(format_id).parse(io.BytesIO(data), filename=filename).canonical


# --- on-demand wiring (opt-in) -------------------------------------------------------------------


def test_no_velocity_request_leaves_velocities_absent() -> None:
    # Emission is opt-in: without a missing_velocities choice, no scenario fires and no velocity is
    # fabricated (a plain extXYZ→POSCAR conversion of a single-frame, lattice-bearing structure).
    reg = _registry()
    source = _parse(
        reg, "extxyz", (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes(), "s.extxyz"
    )
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="poscar"
    )
    assert result.report.status == "completed"
    assert "dynamics.velocities" not in {e.path for e in result.report.supplied}


def test_user_velocity_request_triggers_scenario_and_writes_a_block() -> None:
    reg = _registry()
    source = _parse(
        reg, "extxyz", (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes(), "s.extxyz"
    )
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="extxyz",
        target_format_id="poscar",
        recovery_choices={"missing_velocities": {"choice": "zero_init"}},
    )
    assert result.report.status == "completed"
    assert "dynamics.velocities" in {e.path for e in result.report.supplied}
    assert result.output is not None
    reparsed = _parse(reg, "poscar", result.output, "POSCAR")
    assert reparsed.frames[0].dynamics.velocities is not None


def test_velocity_request_to_a_target_that_cannot_store_it_errors() -> None:
    # Plain XYZ cannot write velocities (capability NONE): an explicit emission request is an honest
    # caller error, not a silent no-op.
    reg = _registry()
    source = _parse(
        reg, "extxyz", (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes(), "s.extxyz"
    )
    with pytest.raises(RecoveryError, match="cannot write 'dynamics.velocities'"):
        ConversionEngine(reg).convert(
            source,
            source_format_id="extxyz",
            target_format_id="xyz",
            recovery_choices={"missing_velocities": {"choice": "zero_init"}},
        )


def test_velocity_request_when_source_already_has_velocities_errors() -> None:
    # Fabricating a field the source already carries would overwrite real data (P4).
    reg = _registry()
    source = _parse(reg, "contcar", _CONTCAR_WITH_VEL, "CONTCAR")
    with pytest.raises(RecoveryError, match="already present on the source"):
        ConversionEngine(reg).convert(
            source,
            source_format_id="contcar",
            target_format_id="poscar",
            recovery_choices={"missing_velocities": {"choice": "zero_init"}},
        )


# --- the flagship done-criterion -----------------------------------------------------------------


def _convert_done_criterion(reg: Registry, source: CanonicalObject) -> ConversionResult:
    return ConversionEngine(reg).convert(
        source,
        source_format_id="extxyz",
        target_format_id="poscar",
        recovery_choices={
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
            "frame_selection": {"choice": "last"},
            "missing_velocities": {
                "choice": "maxwell_boltzmann",
                "parameters": {"temperature_K": 300, "seed": 42},
            },
        },
    )


def test_done_criterion_produces_a_velocity_block_and_traces_velocities() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", _TRAJ_WITH_MASSES, "traj.extxyz")
    result = _convert_done_criterion(reg, source)

    assert result.report.status == "completed"
    assert result.validation is not None
    assert result.validation.status in ("passed", "passed_with_warnings")
    # velocities traced to their Assumption; masses were present on the source, so no mass chain.
    supplied = {e.path for e in result.report.supplied}
    assert "dynamics.velocities" in supplied
    assert "atoms.masses" not in supplied
    assert result.output is not None
    reparsed = _parse(reg, "poscar", result.output, "POSCAR")
    assert reparsed.frames[0].dynamics.velocities is not None


def test_done_criterion_is_byte_identical_on_rerun() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", _TRAJ_WITH_MASSES, "traj.extxyz")
    first = _convert_done_criterion(reg, source)
    second = _convert_done_criterion(reg, source)
    assert first.output == second.output


# --- the maxwell_boltzmann → missing_masses chain ------------------------------------------------


def _xyz_traj(reg: Registry) -> CanonicalObject:
    # Plain XYZ trajectory: no lattice, no velocities, and no masses — so a Maxwell–Boltzmann draw
    # must chain a missing_masses recovery.
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    return _parse(reg, "xyz", data, "water_traj.xyz")


def test_mb_chain_records_two_assumptions_and_traces_masses() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _xyz_traj(reg),
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 3.0}},
            "frame_selection": {"choice": "last"},
            "missing_masses": {"choice": "standard_masses"},
            "missing_velocities": {
                "choice": "maxwell_boltzmann",
                "parameters": {"temperature_K": 300, "seed": 7},
            },
        },
    )
    assert result.report.status == "completed"
    scenarios = [a.scenario for a in result.report.assumptions]
    assert "missing_masses" in scenarios and "missing_velocities" in scenarios
    # masses resolve before velocities (dependency order) so MB reads them.
    assert scenarios.index("missing_masses") < scenarios.index("missing_velocities")
    supplied = {e.path for e in result.report.supplied}
    # Both are audited in `supplied`; masses trace even though POSCAR cannot write them (D47).
    assert {"dynamics.velocities", "atoms.masses"} <= supplied
    assert result.validation is not None
    assert result.validation.status in ("passed", "passed_with_warnings")
    # POSCAR cannot store masses, so the output carries none — the audit trail is in the report.
    assert result.output is not None
    reparsed = _parse(reg, "poscar", result.output, "POSCAR")
    assert reparsed.frames[0].atoms.masses is None
    assert reparsed.frames[0].dynamics.velocities is not None


def test_mb_without_masses_choice_refuses_and_lists_missing_masses() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _xyz_traj(reg),
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 3.0}},
            "frame_selection": {"choice": "last"},
            "missing_velocities": {
                "choice": "maxwell_boltzmann",
                "parameters": {"temperature_K": 300, "seed": 7},
            },
        },
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    unresolved = {s["scenario"] for s in result.report.refusal["unresolved_scenarios"]}
    assert "missing_masses" in unresolved


def test_mb_velocities_are_deterministic_end_to_end() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", _TRAJ_WITH_MASSES, "traj.extxyz")
    a = _convert_done_criterion(reg, source)
    b = _convert_done_criterion(reg, source)
    assert a.output is not None
    assert b.output is not None
    va = _parse(reg, "poscar", a.output, "POSCAR").frames[0].dynamics.velocities
    vb = _parse(reg, "poscar", b.output, "POSCAR").frames[0].dynamics.velocities
    np.testing.assert_array_equal(va, vb)
