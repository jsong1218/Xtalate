"""The repair property suite — the v1.7 contract at property scale (v1.7 M67-S1; D258).

M64/M65's unit fixtures prove each repair on curated objects; this suite proves the
version's headline contract — *every repair is reproducible from its report alone* —
across **generated** Canonical Objects, where the field-presence combinations and
geometries are not hand-chosen. The four families:

1. **Wrap idempotence** — ``wrap_into_cell`` applied twice equals applied once
   (within the project's position tolerance): an already-wrapped structure is not
   transformed a second time.
2. **Dedupe removal exactness** — ``deduplicate`` removes precisely the atoms its
   recorded Assumption enumerates (index + species), and leaves every other atom —
   and every per-atom array of the survivors — untouched, verbatim.
3. **Reorder is a valid permutation** — ``species_reorder``'s recorded map is a
   bijection over ``[0, n_atoms)`` *and* every per-atom array follows that same map
   (a half-permuted object is the failure this guards against).
4. **Report reconstruction** (the headline property) — a conversion's ordered repair
   stack, re-derived on a fresh conversion from the recorded Assumption parameters
   alone, produces **byte-identical output**: the P4-extended-to-modification
   contract at property scale.

The example budget comes from the registered ``pr``/``nightly`` profile pair
(``tests/conftest.py``) — no new profile, no hard-coded budget; the default ``pr``
run keeps the suite cheap and the ``nightly`` profile widens the search. The
strategies compose the existing stage-2 generator (``_strategies.canonical_objects``)
with filters — no ``_strategies.py`` edit was needed. **No engine behaviour is
changed; tests only** (the engine freeze, M64–M67).

**Recorded deviation from the slice plan (for Claude's review, not patched here):**
family 1's plan wording — "its Assumption/warning reflects a no-op" — is not
literally satisfiable on the frozen engine: ``WrapIntoCell`` does not override
``hazards_for``, so the unconditional ``WRAP_DISCARDS_UNWRAPPED_PATHS`` statement
rides every application, including an idempotent one (unlike ``Deduplicate`` and
``SpeciesReorder``, which suppress their warning when nothing changed). The property
therefore asserts the no-op on the **object** (positions unchanged within tolerance,
both applications fully recorded with complete verbatim parameters) and leaves the
warning count of the second application unasserted, so a future engine fix (a
conditional ``hazards_for`` on wrap) tightens rather than breaks the property.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from tests.property import _strategies
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.repair import RepairRequest, apply_repairs
from xtalate.schema import CanonicalObject
from xtalate.schema.cell import to_fractional

#: The project's position tolerance for repaired coordinates (Å) — the atol the M64
#: flagship uses for the wrap's inverse-solve float noise (tests/repair/test_wrap_into_cell.py).
_POSITION_ATOL = 1e-9

_ENGINE = ConversionEngine(default_registry())


def _fractional_residues_clear(obj: CanonicalObject) -> bool:
    """Every position of every frame has a fractional coordinate at least ``1e-12``
    away from an integer cell face — the wrap-idempotence domain.

    Wrap folds with ``np.mod(frac, 1.0)``, and ``1 - epsilon`` for an epsilon below
    the double ULP of 1.0 (~1.1e-16) is **not representable**: it rounds to exactly
    ``1.0``, so a coordinate within float-underflow of a face folds onto the face on
    the first wrap and to ``0.0`` on the next — deterministic (the documented fold
    rule) but not idempotent. Coordinates that close to a face are subnormal-physics
    (below ~1e-15 Å); the property asserts idempotence for representable residues
    (recorded in the progress doc for Claude's review, not patched here — the engine
    is frozen).
    """
    for frame in obj.frames:
        if frame.cell is None:
            continue
        lattice = np.asarray(frame.cell.lattice_vectors, dtype=float)
        fractional = to_fractional(np.asarray(frame.atoms.positions, dtype=float), lattice)
        if not np.all(np.abs(fractional - np.rint(fractional)) > 1e-12):
            return False
    return True


#: Family 1's domain: any object whose **every** frame carries a usable cell — the
#: domain on which wrap never blocks and idempotence is well-defined. The generator's
#: lattices are diagonal-dominant (hence non-singular), so presence is the only cell
#: gate; the fractional-residue filter excludes the underflow-boundary coordinates
#: above (hypothesis's float strategy draws subnormals).
_WRAP_DOMAIN = _strategies.canonical_objects().filter(
    lambda o: all(f.cell is not None for f in o.frames) and _fractional_residues_clear(o)
)

#: Family 4's domain: a single structure with a cell and no constraints — the domain
#: on which the **whole closed set** applies (deduplicate refuses trajectories and
#: removed-atom-under-constraint refusals are unit-tested in M65-S3, not this
#: removal-exactness property), so a generated ordered stack always completes.
_SINGLE_WITH_CELL_NO_CONSTRAINTS = _strategies.canonical_objects().filter(
    lambda o: (
        o.frame_count == 1 and o.frames[0].cell is not None and not o.frames[0].dynamics.constraints
    )
)

#: The center/dedupe parameter dictionaries (each a *complete* request: center needs
#: both reference and target, dedupe a positive threshold — no defaults, P4).
_CENTER_PARAMS = st.fixed_dictionaries(
    {
        "reference": st.sampled_from(["centroid", "cell_center"]),
        "target": st.sampled_from(["origin", "cell_center"]),
    }
)
_DEDUPE_PARAMS = st.fixed_dictionaries(
    {
        "distance_threshold": st.floats(
            min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False
        )
    }
)


@st.composite
def _repair_stack(draw: st.DrawFn) -> list[RepairRequest]:
    """A generated ordered stack of 1–3 repairs from the closed set of four.

    Order is scientific meaning (D250), so the stack is a list, not a dict: the same
    operation may appear twice, and the report's row order records the applied order.
    """
    requests: list[RepairRequest] = []
    for _ in range(draw(st.integers(min_value=1, max_value=3))):
        operation = draw(
            st.sampled_from(["wrap_into_cell", "center", "deduplicate", "species_reorder"])
        )
        if operation == "center":
            parameters: dict[str, Any] = dict(draw(_CENTER_PARAMS))
        elif operation == "deduplicate":
            parameters = dict(draw(_DEDUPE_PARAMS))
        else:
            parameters = {}
        requests.append(RepairRequest(operation, parameters))
    return requests


@st.composite
def _seeded_duplicate_object(draw: st.DrawFn) -> tuple[CanonicalObject, float]:
    """A generated single-structure object **seeded with a known near-duplicate pair**.

    Atom 1 is moved to within the supplied threshold of atom 0 (a small offset along
    ``+x``, magnitude < threshold). Because the greedy sweep never removes atom 0
    (nothing precedes it), atom 1 is **always** removed — the minimum-image distance
    is ≤ the true offset under any pbc (wrapping only shortens), so the guarantee
    holds whether or not the frame carries a cell. Every other atom's fate is left to
    the engine — the property must hold for *any* removal set, not just the seeded one.
    Constraints are dropped: a removed atom under a constraint *refuses* (unit-tested),
    and this property is about removal exactness, not the refusal.
    """
    obj = draw(
        _strategies.canonical_objects().filter(
            lambda o: o.frame_count == 1 and len(o.frames[0].atoms.symbols) >= 2
        )
    )
    threshold = draw(
        st.floats(min_value=0.05, max_value=5.0, allow_nan=False, allow_infinity=False)
    )
    magnitude = draw(
        st.floats(min_value=1e-3, max_value=0.8 * threshold, allow_nan=False, allow_infinity=False)
    )
    frame = obj.frames[0]
    positions = np.asarray(frame.atoms.positions, dtype=float).copy()
    positions[1] = positions[0] + np.array([magnitude, 0.0, 0.0])
    seeded_frame = frame.model_copy(
        update={
            "atoms": frame.atoms.model_copy(update={"positions": positions}),
            "dynamics": frame.dynamics.model_copy(update={"constraints": None}),
        }
    )
    return obj.model_copy(update={"frames": [seeded_frame]}), threshold


# --- Family 1 — wrap idempotence ---------------------------------------------------------


@given(source=_WRAP_DOMAIN)
def test_wrap_into_cell_is_idempotent_within_tolerance(source: CanonicalObject) -> None:
    """Wrapping an already-wrapped structure is a no-op on the object, within tolerance.

    The second application re-derives the same coordinates the first produced (the
    fold of an already-folded fractional coordinate is itself, up to the inverse-solve
    float noise), and both applications are fully recorded with complete verbatim
    parameters — so the report reproduces the repaired object either way.
    """
    once = apply_repairs(source, [RepairRequest("wrap_into_cell")])
    assert once.canonical is not None and not once.blocked

    twice = apply_repairs(once.canonical, [RepairRequest("wrap_into_cell")])
    assert twice.canonical is not None and not twice.blocked

    # Idempotence: the second application changes no position beyond float noise.
    for out, src in zip(twice.canonical.frames, once.canonical.frames, strict=True):
        assert np.allclose(
            np.asarray(out.atoms.positions, dtype=float),
            np.asarray(src.atoms.positions, dtype=float),
            atol=_POSITION_ATOL,
        )

    # Both applications are recorded, each with the complete verbatim parameters ({} —
    # wrap takes none), so either row of the report re-derives the repaired object.
    (first,) = once.applied
    (second,) = twice.applied
    assert first.operation == second.operation == "wrap_into_cell"
    assert first.parameters == second.parameters == {}

    replay = apply_repairs(source, [RepairRequest("wrap_into_cell", dict(first.parameters))])
    assert replay.canonical is not None
    for out, src in zip(replay.canonical.frames, twice.canonical.frames, strict=True):
        assert np.allclose(
            np.asarray(out.atoms.positions, dtype=float),
            np.asarray(src.atoms.positions, dtype=float),
            atol=_POSITION_ATOL,
        )


# --- Family 2 — dedupe removes exactly the enumerated atoms -------------------------------


def _assert_per_atom_arrays_are_survivor_slices(
    source: CanonicalObject, repaired: CanonicalObject, survivors: list[int]
) -> None:
    """Every per-atom array of the output is the source array indexed by the survivor
    list, verbatim — the engine-independent "no other atom changed" half of family 2.
    ``custom_per_atom`` lives on the **object** (one reindex covers all frames), so it
    is checked at the object level, after the per-frame categories."""
    src, out = source.frames[0], repaired.frames[0]

    assert out.atoms.symbols == [src.atoms.symbols[i] for i in survivors]
    assert out.atoms.atomic_numbers == [src.atoms.atomic_numbers[i] for i in survivors]
    assert np.array_equal(
        np.asarray(out.atoms.positions, dtype=float),
        np.asarray(src.atoms.positions, dtype=float)[survivors],
    )
    if src.atoms.masses is None:
        assert out.atoms.masses is None
    else:
        assert out.atoms.masses is not None
        assert np.array_equal(out.atoms.masses, src.atoms.masses[survivors])
    if src.atoms.occupancies is None:
        assert out.atoms.occupancies is None
    else:
        assert out.atoms.occupancies == [src.atoms.occupancies[i] for i in survivors]

    for key in ("velocities", "forces"):
        source_value = getattr(src.dynamics, key)
        out_value = getattr(out.dynamics, key)
        if source_value is None:
            assert out_value is None
        else:
            assert out_value is not None
            assert np.array_equal(out_value, source_value[survivors])

    for key in ("charges", "magnetic_moments"):
        source_value = getattr(src.electronic, key)
        out_value = getattr(out.electronic, key)
        if source_value is None:
            assert out_value is None
        else:
            assert out_value is not None
            assert np.array_equal(out_value, source_value[survivors])

    # Nothing outside the atom axis changed: cell and frame scalars are untouched.
    assert out.cell == src.cell
    assert out.index == src.index
    assert out.time == src.time

    # Object-level custom_per_atom (ndarray or list[JsonValue] form) follows once.
    for key, value in source.user_metadata.custom_per_atom.items():
        out_value = repaired.user_metadata.custom_per_atom[key]
        if isinstance(value, np.ndarray):
            assert isinstance(out_value, np.ndarray)
            assert np.array_equal(out_value, value[survivors])
        else:
            assert out_value == [value[i] for i in survivors]


@given(seeded=_seeded_duplicate_object())
def test_deduplicate_removes_exactly_the_enumerated_atoms_and_no_others(
    seeded: tuple[CanonicalObject, float],
) -> None:
    """Dedupe removes precisely the atoms its Assumption enumerates — no others.

    The seeded pair guarantees the removal set is non-empty on **every** generated
    example (atom 1 is always within the threshold of the never-removed atom 0), so
    the exactness check is always exercised meaningfully; the complement of the
    recorded set must be exactly the survivors, with every survivor array verbatim.
    """
    source, threshold = seeded
    outcome = apply_repairs(
        source, [RepairRequest("deduplicate", {"distance_threshold": threshold})]
    )
    assert outcome.canonical is not None and not outcome.blocked
    (record,) = outcome.applied

    parameters = record.parameters
    removed_atoms = parameters["removed_atoms"]
    assert parameters["distance_threshold"] == threshold
    assert isinstance(parameters["metric"], str) and parameters["metric"]

    indices = [entry["index"] for entry in removed_atoms]
    assert indices == sorted(set(indices))  # exactly once each, ascending
    source_symbols = source.frames[0].atoms.symbols
    assert all(entry["symbol"] == source_symbols[entry["index"]] for entry in removed_atoms)

    # The seeded guarantee: atom 1 is within the threshold of atom 0, and the greedy
    # sweep never removes atom 0 — so atom 1 is always in the enumerated removal set.
    assert 1 in indices

    # The survivors are the complement of the enumerated set, in ascending order —
    # an atom removed without being enumerated, or enumerated without being removed,
    # shows up here as a shape/value mismatch.
    n = len(source_symbols)
    survivors = [i for i in range(n) if i not in set(indices)]
    assert len(survivors) == n - len(indices)
    assert outcome.canonical.frames[0].atoms.symbols == [source_symbols[i] for i in survivors]
    _assert_per_atom_arrays_are_survivor_slices(source, outcome.canonical, survivors)


# --- Family 3 — reorder emits a valid permutation -----------------------------------------


def _element_grouping_permutation(symbols: list[str]) -> list[int]:
    """The species-reorder rule, re-derived independently in test code (D50): atoms
    grouped by element in first-appearance order, stable within each element."""
    order: list[str] = []
    groups: dict[str, list[int]] = {}
    for i, symbol in enumerate(symbols):
        if symbol not in groups:
            groups[symbol] = []
            order.append(symbol)
        groups[symbol].append(i)
    return [i for symbol in order for i in groups[symbol]]


@given(source=_strategies.canonical_objects())
def test_species_reorder_emits_a_valid_permutation_every_array_follows_it(
    source: CanonicalObject,
) -> None:
    """Reorder's recorded map is a bijection over ``[0, n_atoms)`` — and *every*
    per-atom array follows that same map, in every frame (a half-permuted object is
    the failure this guards against). The map is independently re-derived as the
    element grouping of frame 0's symbols, so a wrong-but-valid permutation fails too.
    """
    outcome = apply_repairs(source, [RepairRequest("species_reorder")])
    assert outcome.canonical is not None and not outcome.blocked
    (record,) = outcome.applied

    permutation = record.parameters["permutation"]
    n = len(source.frames[0].atoms.symbols)
    assert sorted(permutation) == list(range(n))  # bijection over [0, n_atoms)
    assert permutation == _element_grouping_permutation(source.frames[0].atoms.symbols)
    inverse = {old: new for new, old in enumerate(permutation)}

    for out, src in zip(outcome.canonical.frames, source.frames, strict=True):
        assert out.atoms.symbols == [src.atoms.symbols[i] for i in permutation]
        assert out.atoms.atomic_numbers == [src.atoms.atomic_numbers[i] for i in permutation]
        assert np.array_equal(
            np.asarray(out.atoms.positions, dtype=float),
            np.asarray(src.atoms.positions, dtype=float)[permutation],
        )
        if src.atoms.masses is None:
            assert out.atoms.masses is None
        else:
            assert out.atoms.masses is not None
            assert np.array_equal(out.atoms.masses, src.atoms.masses[permutation])
        if src.atoms.occupancies is None:
            assert out.atoms.occupancies is None
        else:
            assert out.atoms.occupancies == [src.atoms.occupancies[i] for i in permutation]

        for key in ("velocities", "forces"):
            source_value = getattr(src.dynamics, key)
            out_value = getattr(out.dynamics, key)
            if source_value is None:
                assert out_value is None
            else:
                assert out_value is not None
                assert np.array_equal(out_value, source_value[permutation])

        for key in ("charges", "magnetic_moments"):
            source_value = getattr(src.electronic, key)
            out_value = getattr(out.electronic, key)
            if source_value is None:
                assert out_value is None
            else:
                assert out_value is not None
                assert np.array_equal(out_value, source_value[permutation])

        # Constraint references follow the inverse permutation (reorder is a bijection,
        # so no reference can be dropped — only remapped).
        if src.dynamics.constraints:
            assert out.dynamics.constraints is not None
            assert len(out.dynamics.constraints) == len(src.dynamics.constraints)
            for out_constraint, src_constraint in zip(
                out.dynamics.constraints, src.dynamics.constraints, strict=True
            ):
                assert out_constraint.kind == src_constraint.kind
                assert out_constraint.atom_indices == [
                    inverse[i] for i in src_constraint.atom_indices
                ]

    # The object-level custom_per_atom follows the map once (one reindex covers all
    # frames — the map is frame-invariant by construction).
    for key, value in source.user_metadata.custom_per_atom.items():
        out_value = outcome.canonical.user_metadata.custom_per_atom[key]
        if isinstance(value, np.ndarray):
            assert isinstance(out_value, np.ndarray)
            assert np.array_equal(out_value, value[permutation])
        else:
            assert out_value == [value[i] for i in permutation]


# --- Family 4 — report reconstruction from parameters alone (the headline property) -------


@given(source=_SINGLE_WITH_CELL_NO_CONSTRAINTS, repairs=_repair_stack())
def test_repair_report_reconstructs_the_repaired_object_byte_identically(
    source: CanonicalObject, repairs: list[RepairRequest]
) -> None:
    """The version's headline contract, at property scale (P4 extended to modification).

    A generated ordered stack of repairs converts to a completed result. A **fresh**
    conversion is then re-derived from the report alone — the recorded Assumption
    parameters, replayed verbatim in row order (no intermediate state is reused) —
    and must produce **byte-identical output**. The row order *is* the application
    order, and each row's parameters are the complete record (D249/D250), so a
    third party with only the source and the report re-derives the repaired object
    exactly. (Validation-pass is out of scope here — see the in-body note.)
    """
    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        source_filename="generated.extxyz",
        repairs=repairs,
    )
    assert result.report.status == "completed"
    assert result.output is not None
    # Validation *pass* is deliberately not asserted here: the generated domain includes
    # configurations where a pre-existing, repair-unrelated exporter/validation gap
    # surfaces (e.g. single-frame extXYZ plans ``custom_per_frame`` as preserved but the
    # re-parse lacks it, failing ``metadata_preservation`` — the same conversion without
    # repairs fails identically). The repair contract under test is reconstruction
    # byte-identity, which holds; asserting validation would pin unrelated exporter
    # behaviour onto a repair property.

    # The report's repair rows name the exact requested stack, in application order.
    assert [row.choice for row in result.report.repairs] == [r.operation for r in repairs]

    # Replay the recorded parameters alone — the report is the only input besides the
    # source object; nothing is carried over from the first conversion.
    replayed = [RepairRequest(row.choice, dict(row.parameters)) for row in result.report.repairs]
    rederived = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        source_filename="generated.extxyz",
        repairs=replayed,
    )
    assert rederived.output is not None and rederived.output == result.output
