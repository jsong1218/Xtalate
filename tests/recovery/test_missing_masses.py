"""`missing_masses` resolver tests (M8, MASTER_SPEC Part 4 §3.3).

Covers the two fabricative choices — `standard_masses` (IUPAC standard atomic weights, a *reported
default*) and `manual_input` — the Assumption + `supplied` shape each records, the `in_write_plan`
flag that keeps chained masses out of the write plan for a target that cannot store them (D47), and
the invalid-preset caller errors (distinct from a refusal).
"""

from __future__ import annotations

import ase.data
import numpy as np
import pytest

from xtalate.recovery import RecoveryEngine, RecoveryError, UnresolvedScenario
from xtalate.schema import AtomsBlock, CanonicalObject, Dynamics, Frame, Provenance


def _obj(symbols: list[str], *, masses: np.ndarray | None = None) -> CanonicalObject:
    n = len(symbols)
    positions = np.arange(n * 3, dtype=float).reshape(n, 3)
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=list(symbols), positions=positions, masses=masses),
                dynamics=Dynamics(),
            )
        ],
        provenance=Provenance(
            source_filename=None,
            source_format="xyz",
            original_coordinate_system="cartesian",
        ),
    )


def _masses_scenario(*, emit: bool = True) -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="missing_masses",
        path="atoms.masses",
        options=["standard_masses", "manual_input"],
        params={"emit": emit},
    )


def test_standard_masses_supplies_iupac_weights() -> None:
    result = RecoveryEngine().resolve(
        _obj(["O", "H", "H"]),
        [_masses_scenario()],
        {"missing_masses": {"choice": "standard_masses"}},
    )
    assert result.canonical is not None
    got = result.canonical.frames[0].atoms.masses
    assert got is not None
    expected = [ase.data.atomic_masses[z] for z in (8, 1, 1)]
    np.testing.assert_allclose(got, expected)

    (assumption,) = result.assumptions
    assert assumption.scenario == "missing_masses"
    assert assumption.choice == "standard_masses"
    assert [s.path for s in assumption.supplied] == ["atoms.masses"]
    assert assumption.supplied[0].in_write_plan is True


def test_standard_masses_refuses_unknown_species_X() -> None:
    with pytest.raises(RecoveryError, match="no standard weight"):
        RecoveryEngine().resolve(
            _obj(["O", "X"]),
            [_masses_scenario()],
            {"missing_masses": {"choice": "standard_masses"}},
        )


def test_manual_input_supplies_the_given_masses() -> None:
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_masses_scenario()],
        {"missing_masses": {"choice": "manual_input", "parameters": {"masses": [12.0, 16.0]}}},
    )
    assert result.canonical is not None
    masses = result.canonical.frames[0].atoms.masses
    assert masses is not None
    np.testing.assert_allclose(masses, [12.0, 16.0])
    (assumption,) = result.assumptions
    assert assumption.parameters == {"masses_u": [12.0, 16.0]}


def test_manual_input_wrong_length_raises() -> None:
    with pytest.raises(RecoveryError, match="needs 2 masses"):
        RecoveryEngine().resolve(
            _obj(["C", "O"]),
            [_masses_scenario()],
            {"missing_masses": {"choice": "manual_input", "parameters": {"masses": [12.0]}}},
        )


def test_manual_input_non_positive_mass_raises() -> None:
    with pytest.raises(RecoveryError, match="must all be positive"):
        RecoveryEngine().resolve(
            _obj(["C", "O"]),
            [_masses_scenario()],
            {"missing_masses": {"choice": "manual_input", "parameters": {"masses": [12.0, 0.0]}}},
        )


def test_emit_false_keeps_masses_out_of_the_write_plan_but_in_supplied() -> None:
    # A chained missing_masses for a target that cannot store masses (POSCAR): still fabricated and
    # recorded in `supplied`, but flagged not-in-write-plan so it is dropped from the output (D47).
    result = RecoveryEngine().resolve(
        _obj(["C", "O"]),
        [_masses_scenario(emit=False)],
        {"missing_masses": {"choice": "standard_masses"}},
    )
    assert result.canonical is not None
    (assumption,) = result.assumptions
    assert assumption.supplied[0].in_write_plan is False
