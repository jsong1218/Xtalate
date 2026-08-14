"""The `ase_traj` stress carry resolves through `ambiguous_stress_convention` (v1.2 M42-S5,
RF-8/RF-9; DECISIONS.md D163).

M40 made extXYZ stress first-class under a declared convention; RF-8 generalizes the same
promise to the second ASE-backed format — an ASE `.traj` carrying stress under
`custom_per_frame['ase_traj:stress']` (D18) now refuses without a preset and resolves to
first-class `electronic.stress` under one, through the *same* scenario (the hazard is identical,
so it is one scenario over a key set, not two). RF-9 makes the recorded Assumption name the
actual source format ("ASE `.traj`", never a hardcoded "extXYZ" — a report that misnames the
source is a small silent lie, P1).
"""

from __future__ import annotations

import io

import numpy as np

from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.exporters.ase_traj import make_ase_traj_exporter
from xtalate.parsers._common import build_provenance
from xtalate.parsers.ase_traj import AseTrajParser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject, Cell, Frame, UserMetadata
from xtalate.schema.models import AtomsBlock

_STRESS_KEY = "ase_traj:stress"

# A non-diagonal symmetric 3×3 in the canonical tension-positive convention — the same tensor
# the extXYZ tests carry, so the two formats' resolutions agree number-for-number (D163).
_TENSOR = np.array([[1.0, 0.5, 0.25], [0.5, 2.0, 0.75], [0.25, 0.75, 3.0]], dtype=float)


def _stress_traj_bytes() -> bytes:
    """A real ASE `.traj` carrying a 3×3 stress under `ase_traj:stress`, written through
    Xtalate's own exporter (the carry round-trips via the calculator-results channel)."""
    obj = CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=["H", "H"], positions=np.array([[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]])
                ),
                cell=Cell(lattice_vectors=np.eye(3) * 3.0, pbc=(True, True, True)),
            )
        ],
        user_metadata=UserMetadata(custom_per_frame={_STRESS_KEY: np.array([_TENSOR])}),
        provenance=build_provenance(
            format_id="ase_traj",
            filename="s.traj",
            original_coordinate_system="cartesian",
            source_units={},
            parse_notes=[],
        ),
    )
    buffer = io.BytesIO()
    make_ase_traj_exporter().export(obj, buffer)
    return buffer.getvalue()


def _parse_traj(data: bytes) -> CanonicalObject:
    canonical = AseTrajParser().parse(io.BytesIO(data), filename="s.traj").canonical
    assert canonical is not None
    return canonical


def _stress_source() -> CanonicalObject:
    obj = _parse_traj(_stress_traj_bytes())
    assert _STRESS_KEY in obj.user_metadata.custom_per_frame  # D18: carried, never mapped.
    assert obj.frames[0].electronic.stress is None
    return obj


def _convert(
    obj: CanonicalObject, *, target: str, preset: dict[str, str] | None
) -> ConversionResult:
    return ConversionEngine(default_registry()).convert(
        obj,
        source_format_id="ase_traj",
        target_format_id=target,
        recovery_choices=({"ambiguous_stress_convention": preset} if preset is not None else None),
    )


def test_ase_traj_stress_carry_reads_back_and_stays_unmapped() -> None:
    # The .traj round-trips the carry through the calculator-results channel; on read the
    # tensor is parked under ase_traj:stress and electronic.stress stays None (D18).
    obj = _stress_source()
    carried = np.asarray(obj.user_metadata.custom_per_frame[_STRESS_KEY][0], dtype=float)
    if carried.shape == (6,):  # ASE may persist the Voigt-6 form; either spells the same tensor
        from ase.stress import voigt_6_to_full_3x3_stress

        carried = np.asarray(voigt_6_to_full_3x3_stress(carried), dtype=float)
    assert np.allclose(carried, _TENSOR)


def test_ase_traj_stress_refuses_without_a_preset() -> None:
    # Done-means #1: a .traj stress carry converting to a stress-expressing target refuses
    # without a preset, naming `ambiguous_stress_convention` and its options (RF-8).
    res = _convert(_stress_source(), target="extxyz", preset=None)
    assert res.report.status == "refused"
    assert res.report.refusal is not None
    assert res.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = res.report.refusal["unresolved_scenarios"]
    assert [s["scenario"] for s in scenarios] == ["ambiguous_stress_convention"]
    assert scenarios[0]["options"] == ["ase_sign_convention", "tension_positive"]
    assert _STRESS_KEY in scenarios[0]["detail"]


def test_ase_traj_stress_resolves_and_retires_the_carry() -> None:
    # Done-means #1 (preset side): with a preset the carry populates electronic.stress
    # first-class and is retired — the field lives in exactly one place (D163).
    res = _convert(_stress_source(), target="extxyz", preset={"choice": "tension_positive"})
    assert res.report.status == "completed"
    assert res.canonical_out is not None
    stress = res.canonical_out.frames[0].electronic.stress
    assert stress is not None
    assert np.allclose(stress, _TENSOR)
    assert _STRESS_KEY not in res.canonical_out.user_metadata.custom_per_frame
    assert res.validation is not None and res.validation.status == "passed"


def test_ase_sign_convention_negates_the_tensor() -> None:
    # The second option keeps its existing sign semantics: ASE's convention is
    # compression-positive, so reaching tension-positive negates (RF-9 keeps the semantics,
    # only the format noun generalizes).
    res = _convert(_stress_source(), target="extxyz", preset={"choice": "ase_sign_convention"})
    assert res.report.status == "completed"
    assert res.canonical_out is not None
    stress = res.canonical_out.frames[0].electronic.stress
    assert stress is not None
    assert np.allclose(stress, -_TENSOR)


def test_assumption_names_the_ase_traj_source() -> None:
    # Done-means #2 (RF-9): the recorded Assumption names the actual source format — "ASE
    # `.traj`", never a hardcoded "extXYZ".
    res = _convert(_stress_source(), target="extxyz", preset={"choice": "tension_positive"})
    (assumption,) = res.report.assumptions
    assert assumption.scenario == "ambiguous_stress_convention"
    assert "ASE `.traj`" in assumption.description
    assert "extXYZ" not in assumption.description
    assert assumption.parameters["custom_key"] == _STRESS_KEY


def test_ase_traj_roundtrip_validates_within_the_d151_base() -> None:
    # Done-means #3: a resolved .traj → .traj stress round-trip validates within the M40
    # tolerance base (D151) — no ase_traj-specific base invented (D163 cut line: none).
    res = _convert(_stress_source(), target="ase_traj", preset={"choice": "tension_positive"})
    assert res.report.status == "completed"
    assert res.validation is not None and res.validation.status == "passed"


def test_ase_traj_roundtrip_also_refuses_without_a_preset() -> None:
    # The flip makes ase_traj a stress-expressing target, so an unresolved .traj → .traj
    # conversion refuses exactly as extXYZ → extXYZ does (M40): never a silent interpretation
    # (P4) — the carry is only retired under a recorded convention choice.
    res = _convert(_stress_source(), target="ase_traj", preset=None)
    assert res.report.status == "refused"
    assert res.report.refusal is not None
    assert res.report.refusal["code"] == "RECOVERY_REQUIRED"


def test_extxyz_stress_path_still_names_extxyz() -> None:
    # Done-means #2 (no regression): the extXYZ path still names extXYZ — the RF-9 text is
    # derived from the carried key, so the original format's wording is unchanged.
    from xtalate.parsers.extxyz import ExtxyzParser

    source = (
        b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
        b'stress="1 0.5 0.25 0.5 2 0.75 0.25 0.75 3" pbc="T T T"\nH 0 0 0\n'
    )
    obj = ExtxyzParser().parse(io.BytesIO(source), filename="s.extxyz").canonical
    assert obj is not None
    res = ConversionEngine(default_registry()).convert(
        obj,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    (assumption,) = res.report.assumptions
    assert "extXYZ" in assumption.description
