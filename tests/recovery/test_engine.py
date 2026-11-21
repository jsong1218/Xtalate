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
from xtalate.schema import CanonicalObject, Constraint

GOLDEN = Path(__file__).parent.parent / "golden"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    return reg


def _source() -> CanonicalObject:
    reg = _registry()
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    return reg.get_parser("xyz").parse(io.BytesIO(data), filename="w.xyz").canonical


# A single-frame POSCAR carrying a real selective_dynamics constraint (some atoms fixed) plus an
# injected non-representable constraint, for the constraint_representation resolver tests.
_SELECTIVE_POSCAR = b"""sd test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
2
Selective dynamics
Direct
  0.0 0.0 0.0   T T F
  0.5 0.5 0.5   F F F
"""


def _constraint_source(*, add_unrepresentable: bool = False) -> CanonicalObject:
    reg = _registry()
    obj = reg.get_parser("poscar").parse(io.BytesIO(_SELECTIVE_POSCAR), filename="POSCAR").canonical
    frame = obj.frames[0]
    constraints = list(frame.dynamics.constraints or [])
    assert constraints and constraints[0].kind == "selective_dynamics"
    if add_unrepresentable:
        constraints.append(Constraint(kind="fixed_bond", atom_indices=[0, 1]))
    new_dyn = frame.dynamics.model_copy(update={"constraints": constraints})
    return obj.model_copy(update={"frames": [frame.model_copy(update={"dynamics": new_dyn})]})


# The offered options a POSCAR target computes for constraint_representation (Part 4 §3.3).
def _constraint_scenario() -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="constraint_representation",
        path="dynamics.constraints",
        options=["project", "drop_all"],
        params={"representable_kinds": ["selective_dynamics"]},
    )


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


# --- constraint_representation (selective reductive, Part 4 §3.3) ---------------------------------


def test_constraint_project_keeps_representable_and_drops_the_remainder() -> None:
    # project keeps the representable subset (selective_dynamics) — genuine data, so Preserved,
    # never Supplied — and drops the unrepresentable remainder (fixed_bond) — Removed.
    src = _constraint_source(add_unrepresentable=True)
    result = RecoveryEngine().resolve(
        src,
        [_constraint_scenario()],
        recovery_choices={"constraint_representation": {"choice": "project"}},
    )
    assert result.canonical is not None
    (a,) = result.assumptions
    assert (a.id, a.scenario, a.choice) == ("A1", "constraint_representation", "project")

    # Selective-reductive bright line: NO SuppliedField.
    assert a.supplied == []
    assert [p.path for p in a.preserved] == ["dynamics.constraints"]
    assert [r.path for r in a.removed] == ["dynamics.constraints"]
    assert a.parameters["dropped_kinds"] == {"fixed_bond": 1}

    # The object keeps only the representable constraint.
    kept = result.canonical.frames[0].dynamics.constraints
    assert kept is not None
    assert [c.kind for c in kept] == ["selective_dynamics"]


def test_constraint_project_with_all_representable_drops_nothing() -> None:
    # Source has only selective_dynamics, which POSCAR represents → kept, nothing removed.
    src = _constraint_source()
    result = RecoveryEngine().resolve(
        src,
        [_constraint_scenario()],
        recovery_choices={"constraint_representation": {"choice": "project"}},
    )
    assert result.canonical is not None
    (a,) = result.assumptions
    assert [p.path for p in a.preserved] == ["dynamics.constraints"]
    assert a.removed == []
    assert a.supplied == []


def test_constraint_drop_all_removes_everything_and_supplies_nothing() -> None:
    src = _constraint_source(add_unrepresentable=True)
    result = RecoveryEngine().resolve(
        src,
        [_constraint_scenario()],
        recovery_choices={"constraint_representation": {"choice": "drop_all"}},
    )
    assert result.canonical is not None
    (a,) = result.assumptions
    assert a.choice == "drop_all"
    assert a.preserved == []
    assert a.supplied == []
    assert [r.path for r in a.removed] == ["dynamics.constraints"]
    assert a.parameters == {"dropped": 2}
    # All constraints gone (absence convention: None, not an empty list).
    assert result.canonical.frames[0].dynamics.constraints is None


def test_constraint_unoffered_choice_raises() -> None:
    with pytest.raises(RecoveryError, match="not an offered option"):
        RecoveryEngine().resolve(
            _constraint_source(),
            [_constraint_scenario()],
            recovery_choices={"constraint_representation": {"choice": "reproject"}},
        )


# --- composition ordering across three scenarios (Part 4 §3.3) ------------------------------------


def test_three_scenarios_resolve_in_dependency_order() -> None:
    # A multi-frame, no-lattice, constraint-bearing source needs all three. They must resolve in
    # dependency order — frame_selection, then constraint_representation, then missing_lattice
    # (the bounding box is computed on the chosen frame) — and be numbered A1, A2, A3 in that order.
    src = _source()  # multi-frame water, no lattice, no constraints…
    frame0 = src.frames[0]
    cons = [
        Constraint(
            kind="selective_dynamics",
            atom_indices=[0, 1, 2],
            parameters={"mask": [[True, True, True]] * 3},
        )
    ]
    frame0 = frame0.model_copy(
        update={"dynamics": frame0.dynamics.model_copy(update={"constraints": cons})}
    )
    src = src.model_copy(update={"frames": [frame0, *src.frames[1:]]})

    result = RecoveryEngine().resolve(
        src,
        [
            UnresolvedScenario(scenario="missing_lattice", path="cell.lattice_vectors"),
            _constraint_scenario(),
            UnresolvedScenario(scenario="frame_selection"),
        ],
        recovery_choices={
            "frame_selection": {"choice": "first"},
            "constraint_representation": {"choice": "project"},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 3.0}},
        },
    )
    assert result.canonical is not None
    assert [(a.id, a.scenario) for a in result.assumptions] == [
        ("A1", "frame_selection"),
        ("A2", "constraint_representation"),
        ("A3", "missing_lattice"),
    ]


# --- missing_lattice: upload_reference (Slice 2, Part 4 §3.3) -------------------------------------

_REF_POSCAR = b"""ref
1.0
  5.0  0.0  0.0
  0.0  6.0  0.0
  0.0  0.0  7.0
O H
1 2
Direct
  0.0 0.0 0.0
  0.1 0.1 0.1
  0.2 0.2 0.2
"""


def _reference() -> CanonicalObject:
    reg = _registry()
    return reg.get_parser("poscar").parse(io.BytesIO(_REF_POSCAR), filename="POSCAR").canonical


def test_upload_reference_borrows_the_reference_lattice() -> None:
    # A no-lattice source (3 atoms) borrows the 3×3 lattice from a 3-atom reference structure;
    # this is fabricative — the cell did not exist in the source — so it supplies cell fields.
    result = RecoveryEngine().resolve(
        _source(),
        [
            UnresolvedScenario(scenario="frame_selection"),
            UnresolvedScenario(
                scenario="missing_lattice",
                path="cell.lattice_vectors",
                options=["manual_input", "upload_reference", "bounding_box"],
            ),
        ],
        recovery_choices={
            "frame_selection": {"choice": "first"},
            "missing_lattice": {
                "choice": "upload_reference",
                "parameters": {"reference": _reference()},
            },
        },
    )
    assert result.canonical is not None
    cell = result.canonical.frames[0].cell
    assert cell is not None
    assert np.allclose(np.diag(np.asarray(cell.lattice_vectors, dtype=float)), [5.0, 6.0, 7.0])
    (assumption,) = [a for a in result.assumptions if a.scenario == "missing_lattice"]
    assert assumption.choice == "upload_reference"
    # Fabricative bright line: the borrowed cell is a SuppliedField, never a PreservedField.
    assert {s.path for s in assumption.supplied} == {"cell.lattice_vectors", "cell.pbc"}


def test_upload_reference_rejects_atom_count_mismatch() -> None:
    reg = _registry()
    # A 2-atom reference against the 3-atom water source.
    two_atom = (
        reg.get_parser("poscar")
        .parse(
            io.BytesIO(_REF_POSCAR.replace(b"1 2\n", b"1 1\n").replace(b"  0.2 0.2 0.2\n", b"")),
            filename="POSCAR",
        )
        .canonical
    )
    with pytest.raises(RecoveryError, match="atom-count mismatch"):
        RecoveryEngine().resolve(
            _source(),
            [
                UnresolvedScenario(scenario="frame_selection"),
                UnresolvedScenario(scenario="missing_lattice", path="cell.lattice_vectors"),
            ],
            recovery_choices={
                "frame_selection": {"choice": "first"},
                "missing_lattice": {
                    "choice": "upload_reference",
                    "parameters": {"reference": two_atom},
                },
            },
        )


# --- frame_selection: split_all (Slice 2, Part 4 §3.3) -------------------------------------------


def test_split_all_keeps_every_frame_and_records_one_assumption() -> None:
    # split_all does not reduce — every frame is retained (the ConversionEngine emits one file each)
    # — and records exactly one Assumption with no removed entries (nothing is dropped).
    src = _source()
    n = src.frame_count
    assert n > 1
    result = RecoveryEngine().resolve(
        src,
        [
            UnresolvedScenario(
                scenario="frame_selection", options=["first", "last", "index", "split_all"]
            )
        ],
        recovery_choices={"frame_selection": {"choice": "split_all"}},
    )
    assert result.canonical is not None
    assert result.canonical.frame_count == n  # no reduction
    (assumption,) = result.assumptions
    assert assumption.scenario == "frame_selection"
    assert assumption.choice == "split_all"
    assert assumption.removed == []  # nothing dropped
    assert assumption.supplied == []  # nothing fabricated
