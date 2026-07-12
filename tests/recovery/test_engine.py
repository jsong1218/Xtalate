"""Recovery Engine tests (M5, MASTER_SPEC Part 4 §3).

Covers the fabricative bright line (a supplied cell records an Assumption *and* SuppliedFields),
selective-reductive frame selection (an Assumption and a FrameDrop, but *no* SuppliedField),
the refusal-is-default rule (no preset ⇒ canonical=None, unresolved listed — never a silent
default), the dependency ordering (bounding box computed on the frame_selection-chosen frame),
and the invalid-preset caller error (distinct from a refusal).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from xtalate.capabilities import Registry
from xtalate.parsers import builtin_parsers
from xtalate.recovery import RecoveryEngine, RecoveryError, UnresolvedScenario
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden"


def _source() -> CanonicalObject:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    return reg.get_parser("xyz").parse(io.BytesIO(data), filename="w.xyz").canonical


# The two scenarios a multi-frame, no-lattice XYZ → POSCAR raises (Part 4 §5 worked example shape).
_SCENARIOS = [
    UnresolvedScenario(scenario="frame_selection"),
    UnresolvedScenario(scenario="missing_lattice", path="cell.lattice_vectors"),
]


# --- refusal is the default (Part 4 §3.2) --------------------------------------------------------


def test_no_choices_refuses_and_lists_all_unresolved() -> None:
    result = RecoveryEngine().resolve(_source(), _SCENARIOS, recovery_choices={})
    assert result.canonical is None  # refused — never a partially-recovered object.
    assert result.assumptions == []
    assert {u.scenario for u in result.unresolved} == {"frame_selection", "missing_lattice"}


def test_partial_choices_still_refuse() -> None:
    # One of two scenarios chosen ⇒ still refused; all-or-nothing (Part 4 §3.2).
    result = RecoveryEngine().resolve(
        _source(),
        _SCENARIOS,
        recovery_choices={"frame_selection": {"choice": "first"}},
    )
    assert result.canonical is None
    assert [u.scenario for u in result.unresolved] == ["missing_lattice"]


# --- the fabricative + selective bright line (Part 4 §3.1) ----------------------------------------


def test_full_recovery_records_assumptions_supplied_and_frame_drop() -> None:
    src = _source()
    result = RecoveryEngine().resolve(
        src,
        _SCENARIOS,
        recovery_choices={
            "frame_selection": {"choice": "index", "parameters": {"frame_index": 1}},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
        },
    )
    assert result.canonical is not None
    assert result.unresolved == []

    # Assumptions numbered in application order: A1 = frame_selection (runs first), A2 = lattice.
    a1, a2 = result.assumptions
    assert (a1.id, a1.scenario) == ("A1", "frame_selection")
    assert (a2.id, a2.scenario) == ("A2", "missing_lattice")

    # Selective-reductive: a FrameDrop, but NO SuppliedField (the kept frame is genuine data).
    assert a1.supplied == []
    assert [d.path for d in a1.removed] == ["atoms.positions"]

    # Fabricative: two SuppliedFields (lattice + pbc), NO removed.
    assert {s.path for s in a2.supplied} == {"cell.lattice_vectors", "cell.pbc"}
    assert a2.removed == []

    # Object is reduced to the single chosen frame, now carrying a cell with pbc (T,T,T).
    assert result.canonical.frame_count == 1
    cell = result.canonical.frames[0].cell
    assert cell is not None
    assert cell.pbc == (True, True, True)


def test_bounding_box_is_computed_on_the_selected_frame() -> None:
    # frame 1 has all-z = 0.010; the box + shift must be derived from *that* frame (dependency
    # ordering, Part 4 §3.3), and the shift preserves interatomic distances.
    src = _source()
    frame1_positions = np.asarray(src.frames[1].atoms.positions, dtype=float)
    result = RecoveryEngine().resolve(
        src,
        _SCENARIOS,
        recovery_choices={
            "frame_selection": {"choice": "index", "parameters": {"frame_index": 1}},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 2.0}},
        },
    )
    assert result.canonical is not None
    out = np.asarray(result.canonical.frames[0].atoms.positions, dtype=float)

    def pairwise(p: np.ndarray) -> np.ndarray:
        return np.asarray(np.linalg.norm(p[:, None, :] - p[None, :, :], axis=-1))

    assert np.allclose(pairwise(out), pairwise(frame1_positions))
    # Box side per axis = extent + 2·padding; atoms sit ≥ padding from every face.
    cell = result.canonical.frames[0].cell
    assert cell is not None
    lattice = np.asarray(cell.lattice_vectors, dtype=float)
    extent = frame1_positions.max(axis=0) - frame1_positions.min(axis=0)
    assert np.allclose(np.diag(lattice), extent + 2 * 2.0)
    assert out.min() >= 2.0 - 1e-9


def test_manual_input_lattice_is_supplied_verbatim() -> None:
    lattice = [[10.0, 0.0, 0.0], [0.0, 11.0, 0.0], [0.0, 0.0, 12.0]]
    result = RecoveryEngine().resolve(
        _source(),
        _SCENARIOS,
        recovery_choices={
            "frame_selection": {"choice": "first"},
            "missing_lattice": {"choice": "manual_input", "parameters": {"lattice": lattice}},
        },
    )
    assert result.canonical is not None
    cell = result.canonical.frames[0].cell
    assert cell is not None
    got = np.asarray(cell.lattice_vectors, dtype=float)
    assert np.allclose(got, np.asarray(lattice))


# --- invalid presets are caller errors, not refusals (Part 4 §3.2) -------------------------------


def test_unoffered_choice_raises_recovery_error() -> None:
    # non_periodic is not offered for POSCAR (a periodic-only target), so naming it is a caller
    # error — distinct from a refusal, which is a legitimate outcome (Part 4 §3.2).
    with pytest.raises(RecoveryError, match="not an offered option"):
        RecoveryEngine().resolve(
            _source(),
            [UnresolvedScenario(scenario="missing_lattice", path="cell.lattice_vectors")],
            recovery_choices={"missing_lattice": {"choice": "non_periodic"}},
        )


def test_bounding_box_requires_non_negative_padding() -> None:
    with pytest.raises(RecoveryError, match="padding_ang"):
        RecoveryEngine().resolve(
            _source(),
            [UnresolvedScenario(scenario="missing_lattice", path="cell.lattice_vectors")],
            recovery_choices={"missing_lattice": {"choice": "bounding_box", "parameters": {}}},
        )


def test_index_frame_selection_requires_in_range_index() -> None:
    with pytest.raises(RecoveryError, match="frame_index"):
        RecoveryEngine().resolve(
            _source(),
            [UnresolvedScenario(scenario="frame_selection")],
            recovery_choices={
                "frame_selection": {"choice": "index", "parameters": {"frame_index": 99}}
            },
        )
