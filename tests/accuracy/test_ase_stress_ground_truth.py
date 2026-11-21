"""Ground truth: ASE's get_stress() is tension-positive. Xtalate must agree with ASE itself."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ase")
from ase import Atoms  # noqa: E402
from ase.build import bulk  # noqa: E402
from ase.calculators.emt import EMT  # noqa: E402
from ase.io import read, write  # noqa: E402

from xtalate.exporters.extxyz import ExtxyzExporter  # noqa: E402
from xtalate.parsers.extxyz import ExtxyzParser  # noqa: E402
from xtalate.recovery import RecoveryEngine, UnresolvedScenario, available_options  # noqa: E402
from xtalate.schema import CanonicalObject  # noqa: E402


def resolve_stress(obj: CanonicalObject, choice: str) -> CanonicalObject:
    """Resolve the carried extXYZ stress under `choice` (same call shape as
    tests/recovery/test_stress_convention.py)."""
    scenario = UnresolvedScenario(
        scenario="ambiguous_stress_convention",
        path="electronic.stress",
        options=available_options("ambiguous_stress_convention"),
        params={"custom_key": "extxyz:stress"},
    )
    result = RecoveryEngine().resolve(
        obj,
        [scenario],
        recovery_choices={"ambiguous_stress_convention": {"choice": choice}},
    )
    assert result.canonical is not None and result.unresolved == []
    return result.canonical


def _cu(scale: float) -> Atoms:
    atoms = bulk("Cu", "fcc", a=3.61, cubic=True)
    atoms.set_cell(atoms.cell * scale, scale_atoms=True)
    atoms.calc = EMT()
    return atoms


def test_ase_physics_ground_truth() -> None:
    # Compressed solid pushes outward: tension-positive stress has NEGATIVE trace.
    assert np.trace(np.asarray(_cu(0.98).get_stress(voigt=False))) < 0
    assert np.trace(np.asarray(_cu(1.02).get_stress(voigt=False))) > 0


def test_offered_options_are_tension_and_compression() -> None:
    assert available_options("ambiguous_stress_convention") == [
        "tension_positive",
        "compression_positive",
    ]


@pytest.mark.parametrize("scale", [0.98, 1.02])
def test_extxyz_written_by_xtalate_has_the_same_sign_ase_reports(
    scale: float, tmp_path: Path
) -> None:
    atoms = _cu(scale)
    expected = np.asarray(atoms.get_stress(voigt=False))
    src = tmp_path / "src.extxyz"
    write(src, atoms, format="extxyz")
    parsed = ExtxyzParser().parse(io.BytesIO(src.read_bytes()), filename=None)
    # Resolve the carry under tension_positive (the honest reading of an ASE file).
    canonical = resolve_stress(parsed.canonical, "tension_positive")
    stress = np.asarray(canonical.frames[0].electronic.stress)
    np.testing.assert_allclose(stress, expected, atol=1e-9)
    out = io.BytesIO()
    ExtxyzExporter().export(canonical, out)
    dst = tmp_path / "dst.extxyz"
    dst.write_bytes(out.getvalue())
    reread = np.asarray(read(dst, format="extxyz").get_stress(voigt=False))
    np.testing.assert_allclose(reread, expected, atol=1e-9)
