"""The report-completeness properties, applied to the M8 fabricative recovery family (B1 gap).

``test_report_completeness`` drives the whole optional-field lattice, but only under
``FIXED_PRESETS`` — ``missing_lattice`` + ``frame_selection``. The opt-in velocity/mass family
(``missing_velocities``, ``missing_masses``) never fires there, because emission is on-demand
(D46): passing it in the shared preset table would fabricate velocities across every existing
round-trip/stage-1 conversion, not exercise it in isolation. So the fabricative path is unit-tested
end to end in ``tests/conversion/test_velocity_recovery.py`` (which runs the *runtime* completeness
assertion inside ``convert``) but never reaches the **independently re-derived** properties of
``_properties`` — the guard that must catch a broken finalizer without the runtime assertion in the
loop (D50).

This module closes that gap: each case genuinely *supplies* ``dynamics.velocities`` and/or
``atoms.masses`` (deterministic choices — ``zero_init``/``standard_masses``, and
``maxwell_boltzmann`` with a fixed seed, D45), and both properties are asserted on the resulting
report. A per-case non-vacuity assertion pins that the fabrication actually happened, so the
property is never trivially satisfied.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.property import _properties
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

GOLDEN = Path(__file__).parent.parent / "golden"
_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_STRICT = ToleranceProfile.named("strict")

# A two-frame extXYZ carrying masses but no Lattice and no velocities: Maxwell–Boltzmann reads the
# present masses (no chain), a lattice is fabricated, and the trajectory is reduced to one frame.
_TRAJ_WITH_MASSES = (
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.1 0.0 0.0 15.999\n"
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.25 0.0 0.0 15.999\n"
)


def _parse(format_id: str, data: bytes, filename: str) -> CanonicalObject:
    return _REGISTRY.get_parser(format_id).parse(io.BytesIO(data), filename=filename).canonical


def _single_frame_extxyz() -> CanonicalObject:
    return _parse(
        "extxyz", (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes(), "s.extxyz"
    )


def _xyz_traj() -> CanonicalObject:
    return _parse("xyz", (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes(), "w.xyz")


@dataclass(frozen=True)
class _Case:
    case_id: str
    source_fmt: str
    source: CanonicalObject
    recovery: dict[str, dict[str, Any]]
    expected_supplied: frozenset[str]


def _cases() -> list[_Case]:
    _LATTICE = {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
    _LAST = {"choice": "last"}
    return [
        # Simplest fabrication: a single-frame lattice-bearing structure, velocities requested with
        # the deterministic zero_init choice. Only velocities are supplied.
        _Case(
            "zero_init_velocities",
            "extxyz",
            _single_frame_extxyz(),
            {"missing_velocities": {"choice": "zero_init"}},
            frozenset({"dynamics.velocities"}),
        ),
        # Maxwell–Boltzmann over a source with masses present: velocities supplied, no mass chain.
        _Case(
            "mb_velocities_masses_present",
            "extxyz",
            _parse("extxyz", _TRAJ_WITH_MASSES, "traj.extxyz"),
            {
                "missing_lattice": _LATTICE,
                "frame_selection": _LAST,
                "missing_velocities": {
                    "choice": "maxwell_boltzmann",
                    "parameters": {"temperature_K": 300, "seed": 42},
                },
            },
            frozenset({"dynamics.velocities"}),
        ),
        # The full D46 chain: a massless plain-XYZ trajectory, so Maxwell–Boltzmann must chain a
        # standard_masses recovery. Both masses and velocities are supplied (masses audited in
        # `supplied` even though POSCAR cannot write them, D47).
        _Case(
            "mb_chain_supplies_masses_and_velocities",
            "xyz",
            _xyz_traj(),
            {
                "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 3.0}},
                "frame_selection": _LAST,
                "missing_masses": {"choice": "standard_masses"},
                "missing_velocities": {
                    "choice": "maxwell_boltzmann",
                    "parameters": {"temperature_K": 300, "seed": 7},
                },
            },
            frozenset({"dynamics.velocities", "atoms.masses"}),
        ),
    ]


_CASES = _cases()


@pytest.mark.parametrize("case", _CASES, ids=[c.case_id for c in _CASES])
def test_fabricative_recovery_satisfies_both_properties(case: _Case) -> None:
    result = _ENGINE.convert(
        case.source,
        source_format_id=case.source_fmt,
        target_format_id="poscar",
        mode="permissive",
        recovery_choices=case.recovery,
        tolerance_profile=_STRICT,
    )
    report = result.report
    assert report.status == "completed", f"{case.case_id}: unexpected {report.status}"

    # Non-vacuity: the fabrication the property is meant to police actually happened.
    supplied = {e.path for e in report.supplied}
    assert case.expected_supplied <= supplied, (
        f"{case.case_id}: expected {set(case.expected_supplied)} supplied, got {supplied}"
    )

    # Property 1 — completeness invariant, re-derived independently of the runtime assertion.
    p1 = _properties.completeness_violations(case.source, report)
    assert not p1, f"{case.case_id}: completeness violated: {p1}"

    # Property 2 — absence conformance over the re-parsed output.
    assert result.output is not None
    reparsed = _parse("poscar", result.output, "POSCAR")
    p2 = _properties.absence_violations(report, reparsed)
    assert not p2, f"{case.case_id}: absence conformance violated: {p2}"


def test_fabricative_cases_are_non_vacuous() -> None:
    """Guard: the suite must collectively supply *both* velocities and masses, or a refactor that
    stopped fabricating would leave the properties trivially satisfied."""
    supplied: set[str] = set()
    for case in _CASES:
        supplied |= set(case.expected_supplied)
    assert {"dynamics.velocities", "atoms.masses"} <= supplied
