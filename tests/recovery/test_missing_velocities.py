"""`missing_velocities` resolver tests (M8, MASTER_SPEC Part 4 §3.3).

Covers the four choices — `zero_init`, `maxwell_boltzmann`, `upload_reference`, and ✳`omit` — the
Assumption + `supplied` shape each records (`omit` alone fabricates nothing), the
`maxwell_boltzmann → missing_masses` chain producing two ordered Assumptions, and the invalid-preset
caller errors (non-integer seed, non-positive temperature, unoffered `omit`, absent masses).
"""

from __future__ import annotations

import numpy as np
import pytest

from xtalate.recovery import RecoveryEngine, RecoveryError, UnresolvedScenario
from xtalate.schema import AtomsBlock, CanonicalObject, Dynamics, Frame, Provenance


def _obj(
    symbols: list[str],
    *,
    masses: np.ndarray | None = None,
    velocities: np.ndarray | None = None,
) -> CanonicalObject:
    n = len(symbols)
    positions = np.arange(n * 3, dtype=float).reshape(n, 3)
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=list(symbols), positions=positions, masses=masses),
                dynamics=Dynamics(velocities=velocities),
            )
        ],
        provenance=Provenance(
            source_filename=None,
            source_format="xyz",
            original_coordinate_system="cartesian",
        ),
    )


def _vel_scenario(options: list[str] | None = None) -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="missing_velocities",
        path="dynamics.velocities",
        options=options or ["zero_init", "maxwell_boltzmann", "upload_reference"],
        params={"emit": True},
    )


def _masses_scenario(*, emit: bool = True) -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="missing_masses",
        path="atoms.masses",
        options=["standard_masses", "manual_input"],
        params={"emit": emit},
    )


def test_zero_init_supplies_an_all_zero_rest_state() -> None:
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_vel_scenario()],
        {"missing_velocities": {"choice": "zero_init"}},
    )
    assert result.canonical is not None
    vel = result.canonical.frames[0].dynamics.velocities
    assert vel is not None
    np.testing.assert_array_equal(vel, np.zeros((2, 3)))
    (assumption,) = result.assumptions
    assert [s.path for s in assumption.supplied] == ["dynamics.velocities"]


def test_maxwell_boltzmann_records_temperature_and_seed_and_supplies_velocities() -> None:
    result = RecoveryEngine().resolve(
        _obj(["C", "O"], masses=np.array([12.011, 15.999])),
        [_vel_scenario()],
        {
            "missing_velocities": {
                "choice": "maxwell_boltzmann",
                "parameters": {"temperature_K": 300, "seed": 42},
            }
        },
    )
    assert result.canonical is not None
    assert result.canonical.frames[0].dynamics.velocities is not None
    (assumption,) = result.assumptions
    assert assumption.parameters == {"temperature_K": 300.0, "seed": 42}
    assert [s.path for s in assumption.supplied] == ["dynamics.velocities"]


def test_maxwell_boltzmann_rejects_non_integer_seed() -> None:
    with pytest.raises(RecoveryError, match="integer seed"):
        RecoveryEngine().resolve(
            _obj(["C"], masses=np.array([12.011])),
            [_vel_scenario()],
            {
                "missing_velocities": {
                    "choice": "maxwell_boltzmann",
                    "parameters": {"temperature_K": 300.0, "seed": 4.5},
                }
            },
        )


def test_maxwell_boltzmann_rejects_non_positive_temperature() -> None:
    with pytest.raises(RecoveryError, match="temperature_K must be positive"):
        RecoveryEngine().resolve(
            _obj(["C"], masses=np.array([12.011])),
            [_vel_scenario()],
            {
                "missing_velocities": {
                    "choice": "maxwell_boltzmann",
                    "parameters": {"temperature_K": 0, "seed": 1},
                }
            },
        )


def test_maxwell_boltzmann_without_masses_raises() -> None:
    # Defensive: MB reads masses the chain should have supplied; a lone MB scenario with no masses
    # (and no chained missing_masses) is a caller error.
    with pytest.raises(RecoveryError, match="needs per-atom masses"):
        RecoveryEngine().resolve(
            _obj(["C"]),
            [_vel_scenario()],
            {
                "missing_velocities": {
                    "choice": "maxwell_boltzmann",
                    "parameters": {"temperature_K": 300.0, "seed": 1},
                }
            },
        )


def test_maxwell_boltzmann_chains_masses_in_dependency_order() -> None:
    # masses absent → chain missing_masses; masses resolve *before* velocities so MB reads them.
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_vel_scenario(), _masses_scenario()],
        {
            "missing_masses": {"choice": "standard_masses"},
            "missing_velocities": {
                "choice": "maxwell_boltzmann",
                "parameters": {"temperature_K": 300, "seed": 42},
            },
        },
    )
    assert result.canonical is not None
    assert [(a.id, a.scenario) for a in result.assumptions] == [
        ("A1", "missing_masses"),
        ("A2", "missing_velocities"),
    ]
    assert result.canonical.frames[0].dynamics.velocities is not None
    assert result.canonical.frames[0].atoms.masses is not None


def test_upload_reference_borrows_velocities_shape_checked() -> None:
    ref = _obj(["C", "O"], velocities=np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]))
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_vel_scenario()],
        {"missing_velocities": {"choice": "upload_reference", "parameters": {"reference": ref}}},
    )
    assert result.canonical is not None
    recovered = result.canonical.frames[0].dynamics.velocities
    expected = ref.frames[0].dynamics.velocities
    assert recovered is not None
    assert expected is not None
    np.testing.assert_allclose(recovered, expected)


def test_upload_reference_rejects_shape_mismatch() -> None:
    ref = _obj(["C"], velocities=np.array([[0.1, 0.2, 0.3]]))
    with pytest.raises(RecoveryError, match="shape mismatch"):
        RecoveryEngine().resolve(
            _obj(["C", "O"]),
            [_vel_scenario()],
            {
                "missing_velocities": {
                    "choice": "upload_reference",
                    "parameters": {"reference": ref},
                }
            },
        )


def test_omit_fabricates_nothing_and_leaves_velocities_absent() -> None:
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_vel_scenario(["zero_init", "maxwell_boltzmann", "upload_reference", "omit"])],
        {"missing_velocities": {"choice": "omit"}},
    )
    assert result.canonical is not None
    assert result.canonical.frames[0].dynamics.velocities is None
    (assumption,) = result.assumptions
    assert assumption.choice == "omit"
    assert assumption.supplied == []


def test_omit_when_not_offered_raises() -> None:
    # In strict mode (or a required field) `omit` is absent from the offered list, so naming it is a
    # caller error — the "otherwise refused" behavior of the catalog footnote.
    with pytest.raises(RecoveryError, match="not an offered option"):
        RecoveryEngine().resolve(
            _obj(["C", "O"]),
            [_vel_scenario()],  # no "omit" in options
            {"missing_velocities": {"choice": "omit"}},
        )
