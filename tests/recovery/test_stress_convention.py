"""`ambiguous_stress_convention` recovery tests (M40, MASTER_SPEC Part 4 §3.3).

Covers the interpretive bright line (an Assumption with **no** `supplied` entry — the stress is
genuine source data, only its sign convention is resolved), the sign-normalization resolver
(`tension_positive` takes the tensor as-is, `ase_sign_convention` negates it), the custom-array
retirement (the field lives in exactly one place after resolution), the refusal-without-preset
default (no preset ⇒ `electronic.stress` stays `None`, the carry survives), the catalog shape
(two-option core; the deferred `virial` option is absent so naming it refuses), and the **teeth
test**: a wrong convention choice produces a *detectably sign-flipped* tensor, proving the
interpretation is the user's recorded decision, never Xtalate's.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from xtalate.capabilities import Registry
from xtalate.parsers import builtin_parsers
from xtalate.recovery import (
    RecoveryEngine,
    RecoveryError,
    UnresolvedScenario,
    available_options,
)
from xtalate.recovery.scenarios import (
    INTERPRETIVE_SCENARIOS,
    SCENARIO_HAZARD,
    HazardClass,
    is_interpretive,
)
from xtalate.schema import CanonicalObject

# A single-frame extXYZ carrying a *non-diagonal symmetric* 3×3 stress on the comment line (nine
# components — the only shape ASE's reader accepts for the SPECIAL_3_3_KEYS). ASE reshapes to 3×3
# and normalizes the calculator result to the Voigt-6 (xx,yy,zz,yz,xz,xy) vector, so the carry the
# parser records is six elements and the resolver's Voigt expansion genuinely reorders the tensor.
_STRESS_3X3_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0.5 0.25 0.5 2 0.75 0.25 0.75 3" pbc="T T T"\nH 0 0 0\n'
)

# The full symmetric 3×3 the fixture above spells out (ASE's order='F' reshape of the nine
# components), in the canonical tension-positive convention.
_TENSOR = [[1.0, 0.5, 0.25], [0.5, 2.0, 0.75], [0.25, 0.75, 3.0]]

# Two frames; only frame 0 carries stress (the parser keys the carry with None for the frame that
# omits it — Part 2 §6.1's per-frame association).
_STRESS_MIXED_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0 0 0 2 0 0 0 3" pbc="T T T"\nH 0 0 0\n'
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 pbc="T T T"\nH 0.1 0 0\n'
)


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    return reg


def _stress_source(data: bytes = _STRESS_3X3_EXTXYZ) -> CanonicalObject:
    reg = _registry()
    obj = reg.get_parser("extxyz").parse(io.BytesIO(data), filename="s.extxyz").canonical
    assert "extxyz:stress" in obj.user_metadata.custom_per_frame
    assert obj.frames[0].electronic.stress is None  # D18: carried, never mapped.
    return obj


def _stress_scenario() -> UnresolvedScenario:
    return UnresolvedScenario(
        scenario="ambiguous_stress_convention",
        path="electronic.stress",
        options=available_options("ambiguous_stress_convention"),
        params={"custom_key": "extxyz:stress"},
    )


# --- catalog (Part 4 §3.3) -------------------------------------------------------------


def test_catalog_registers_the_scenario_as_fabricative_for_mode_gating() -> None:
    # FABRICATIVE gives the mode gating for free: an explicit choice is required in *both* strict
    # and permissive modes, no auto-applied default (Part 4 §3.1–§4).
    assert SCENARIO_HAZARD["ambiguous_stress_convention"] is HazardClass.FABRICATIVE


def test_interpretive_marker_and_two_option_core() -> None:
    assert "ambiguous_stress_convention" in INTERPRETIVE_SCENARIOS
    assert is_interpretive("ambiguous_stress_convention")
    assert not is_interpretive("missing_lattice")  # a true fabricative is not interpretive.
    assert available_options("ambiguous_stress_convention") == [
        "ase_sign_convention",
        "tension_positive",
    ]
    # `virial` is the named cut line (→ v1.1.1): absent from the offered list, so naming it
    # refuses — never offered-then-refused, the Part 4 §3.3 discipline.
    assert "virial" not in available_options("ambiguous_stress_convention")


# --- resolution -----------------------------------------------------------------------


def test_tension_positive_takes_the_tensor_as_is() -> None:
    result = RecoveryEngine().resolve(
        _stress_source(),
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert result.canonical is not None
    assert result.unresolved == []
    (assumption,) = result.assumptions
    assert (assumption.id, assumption.scenario, assumption.choice) == (
        "A1",
        "ambiguous_stress_convention",
        "tension_positive",
    )
    # Interpretive bright line: an Assumption, but NO `supplied` entry — the value is genuine
    # source data, only its convention was resolved.
    assert assumption.supplied == []
    assert [p.path for p in assumption.preserved] == ["electronic.stress"]
    assert [r.path for r in assumption.removed] == [
        "user_metadata.custom_per_frame['extxyz:stress']"
    ]
    assert assumption.parameters == {
        "resolved_source_convention": "tension_positive",
        "custom_key": "extxyz:stress",
    }
    # The interpretation is stated in plain language (the Revision 1.10 operative rule).
    assert "tension-positive per your choice" in assumption.description
    assert "no sign change applied" in assumption.description
    # The tensor is populated as-is (the source is already tension-positive), full 3×3 — the
    # non-diagonal fixture genuinely exercises the Voigt-6 → 3×3 reordering.
    stress = result.canonical.frames[0].electronic.stress
    assert stress is not None
    assert np.allclose(stress, _TENSOR)
    # The custom array is retired — the field lives in exactly one place, so S2's exporter can
    # never double-write it.
    assert "extxyz:stress" not in result.canonical.user_metadata.custom_per_frame


def test_ase_sign_convention_negates_to_tension_positive() -> None:
    result = RecoveryEngine().resolve(
        _stress_source(),
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "ase_sign_convention"}},
    )
    assert result.canonical is not None
    (assumption,) = result.assumptions
    assert assumption.choice == "ase_sign_convention"
    assert assumption.supplied == []
    assert "ASE's sign convention" in assumption.description
    assert "sign inverted" in assumption.description
    assert "tension-positive" in assumption.description
    stress = result.canonical.frames[0].electronic.stress
    assert stress is not None
    # ASE is compression-positive, the opposite of the canonical tension-positive: reaching the
    # canonical convention requires the sign flip.
    assert np.allclose(stress, -np.asarray(_TENSOR))


def test_teeth_wrong_convention_sign_flips_the_tensor() -> None:
    # The interpretation must have teeth: a *wrong* choice is detectably wrong (sign-flipped)
    # against the correct one — proving the sign is the user's recorded decision, never a silent
    # Xtalate guess (a silent flip would be invisible in the output, the exact hazard the
    # scenario exists to refuse).
    pos = RecoveryEngine().resolve(
        _stress_source(),
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    neg = RecoveryEngine().resolve(
        _stress_source(),
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "ase_sign_convention"}},
    )
    assert pos.canonical is not None and neg.canonical is not None
    pos_stress = pos.canonical.frames[0].electronic.stress
    neg_stress = neg.canonical.frames[0].electronic.stress
    assert pos_stress is not None and neg_stress is not None
    assert np.allclose(neg_stress, -pos_stress)
    assert not np.allclose(pos_stress, neg_stress)


def test_raw_carry_shapes_are_expanded_or_taken_as_is() -> None:
    # The Voigt-6 carry (xx,yy,zz,yz,xz,xy) lands in the full 3×3 with the exact ordering the file
    # and §3.7.1 state — the inverse of the order ASE writes, so components round-trip to their
    # file slots. A (3, 3) carry is already full and taken as-is. Anything else is refused rather
    # than guessed (P4).
    source = _stress_source()

    voigt = [1.0, 2.0, 3.0, 0.5, 0.25, 0.75]
    um = source.user_metadata
    voigt_carry = {"extxyz:stress": [voigt]}
    voigt_source = source.model_copy(
        update={"user_metadata": um.model_copy(update={"custom_per_frame": voigt_carry})}
    )
    result = RecoveryEngine().resolve(
        voigt_source,
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert result.canonical is not None
    stress = result.canonical.frames[0].electronic.stress
    assert stress is not None
    assert np.allclose(stress, voigt_6_to_full_3x3_stress(np.asarray(voigt)))

    full_carry = {"extxyz:stress": [_TENSOR]}
    full = source.model_copy(
        update={"user_metadata": um.model_copy(update={"custom_per_frame": full_carry})}
    )
    result = RecoveryEngine().resolve(
        full,
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert result.canonical is not None
    stress = result.canonical.frames[0].electronic.stress
    assert stress is not None
    assert np.allclose(stress, _TENSOR)


def test_mixed_carry_populates_only_the_stress_bearing_frame() -> None:
    source = _stress_source(_STRESS_MIXED_EXTXYZ)
    result = RecoveryEngine().resolve(
        source,
        [_stress_scenario()],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert result.canonical is not None
    assert result.canonical.frames[0].electronic.stress is not None
    assert result.canonical.frames[1].electronic.stress is None  # the frame never carried it.
    assert "extxyz:stress" not in result.canonical.user_metadata.custom_per_frame
    (assumption,) = result.assumptions
    assert [p.path for p in assumption.preserved] == ["electronic.stress"]
    detail = assumption.preserved[0].detail
    assert detail is not None
    assert "frame 0" in detail
    assert [r.path for r in assumption.removed] == [
        "user_metadata.custom_per_frame['extxyz:stress']"
    ]


# --- refusal is the default (Part 4 §3.2) ----------------------------------------------


def test_no_preset_refuses_and_keeps_the_carry() -> None:
    source = _stress_source()
    result = RecoveryEngine().resolve(source, [_stress_scenario()], recovery_choices={})
    assert result.canonical is None  # refused — never a silent interpretation.
    assert result.assumptions == []
    (unresolved,) = result.unresolved
    assert unresolved.scenario == "ambiguous_stress_convention"
    assert unresolved.path == "electronic.stress"
    assert unresolved.options == ["ase_sign_convention", "tension_positive"]
    # The safe state survives untouched: the carry and its value are still reported custom data
    # (today's honest state — the tensor stays where D18 put it).
    assert "extxyz:stress" in source.user_metadata.custom_per_frame
    assert source.frames[0].electronic.stress is None


# --- caller errors, distinct from a refusal (Part 4 §3.2) ------------------------------


def test_naming_the_deferred_virial_option_raises() -> None:
    # `virial` tracks to v1.1.1 and is absent from the offered list, so naming it is a caller
    # error — never offered-then-refused (Part 4 §3.3).
    with pytest.raises(RecoveryError, match="not an offered option"):
        RecoveryEngine().resolve(
            _stress_source(),
            [_stress_scenario()],
            recovery_choices={"ambiguous_stress_convention": {"choice": "virial"}},
        )


def test_resolver_refuses_a_carry_that_is_not_a_stress_tensor() -> None:
    # A carry of an unexpected shape is not a tensor the resolver can honestly interpret — refuse
    # rather than guess (P4).
    source = _stress_source()
    um = source.user_metadata
    new_um = um.model_copy(update={"custom_per_frame": {"extxyz:stress": [[1.0, 2.0]]}})
    source = source.model_copy(update={"user_metadata": new_um})
    with pytest.raises(RecoveryError, match="shape"):
        RecoveryEngine().resolve(
            source,
            [_stress_scenario()],
            recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
        )


def test_resolver_refuses_when_no_carry_exists() -> None:
    # The scenario should never fire without the carry (pre-flight guarantees it); a
    # directly-constructed scenario on a carry-less source is a caller error, not a silent no-op.
    reg = _registry()
    source = (
        reg.get_parser("extxyz")
        .parse(
            io.BytesIO(
                b'1\nLattice="3 0 0 0 3 0 0 0 3" '
                b'Properties=species:S:1:pos:R:3 pbc="T T T"\nH 0 0 0\n'
            ),
            filename="s.extxyz",
        )
        .canonical
    )
    with pytest.raises(RecoveryError, match="carries no 'extxyz:stress'"):
        RecoveryEngine().resolve(
            source,
            [_stress_scenario()],
            recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
        )
