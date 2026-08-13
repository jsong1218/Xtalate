"""extXYZ exporter stress write tests (M40-S2, Part 2 §3.7.1, Part 4 §1).

The exporter's stress channel is **dual-source**: a resolved `electronic.stress` is written from
the field — reversed from the canonical tension-positive to the compression-positive convention
ASE-native extXYZ files carry, and reported by `export_warnings` as `STRESS_SIGN_CONVENTION_CHANGED`
— while an unresolved object's `extxyz:stress` carry is written **verbatim** (back-compat: an
opaque extXYZ→extXYZ pass-through round-trips the numbers exactly as they came in, never silently
normalized). The field is preferred defensively when both are present (no double-write; on a
resolved object S1's resolver retires the carry, so in practice only one source exists).
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from xtalate.capabilities import Registry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.recovery import RecoveryEngine, UnresolvedScenario
from xtalate.schema import CanonicalObject
from xtalate.sdk import CapabilityLevel

# A single-frame extXYZ carrying a non-diagonal 3×3 stress (nine components — ASE's reader only
# accepts that shape for the stress special key; it reshapes to 3×3 and carries Voigt-6).
_STRESS_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0.5 0.25 0.5 2 0.75 0.25 0.75 3" pbc="T T T"\nH 0 0 0\n'
)

# Two frames; only frame 0 carries stress (the carry keys frame 1 with None).
_STRESS_MIXED_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0 0 0 2 0 0 0 3" pbc="T T T"\nH 0 0 0\n'
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 pbc="T T T"\nH 0.1 0 0\n'
)


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


@pytest.fixture(scope="module")
def reg() -> Registry:
    return _registry()


def _parse(reg: Registry, data: bytes) -> CanonicalObject:
    return reg.get_parser("extxyz").parse(io.BytesIO(data), filename="s.extxyz").canonical


def _resolved(
    reg: Registry, source: CanonicalObject, choice: str = "ase_sign_convention"
) -> CanonicalObject:
    """Resolve the carry into `electronic.stress` via the recovery (S1), retiring the carry."""
    result = RecoveryEngine().resolve(
        source,
        [UnresolvedScenario(scenario="ambiguous_stress_convention", path="electronic.stress")],
        recovery_choices={"ambiguous_stress_convention": {"choice": choice}},
    )
    assert result.canonical is not None
    return result.canonical


def _reparse(reg: Registry, data: bytes) -> CanonicalObject:
    return reg.get_parser("extxyz").parse(io.BytesIO(data), filename=None).canonical


def _exporter(reg: Registry) -> Any:
    return reg.get_exporter("extxyz")


def _carry(obj: CanonicalObject) -> np.ndarray:
    """The whole per-frame carry coerced to float (shape (F, 6) for the Voigt-6 stress the parser
    records) — the JsonValue union normalized at the boundary so the tests read it as an array."""
    return np.asarray(obj.user_metadata.custom_per_frame["extxyz:stress"], dtype=float)


def _carry_tensor(obj: CanonicalObject) -> np.ndarray:
    """Frame 0's carried stress expanded from ASE's Voigt-6 compression back to the full 3×3 —
    the file's own component order, via ASE's inverse (the same expansion the resolver and the
    validation check apply, Part 2 §3.7.1)."""
    return np.asarray(voigt_6_to_full_3x3_stress(_carry(obj)[0]), dtype=np.float64)


# --- write from the populated field (done means #1's write side) -----------------------


def test_resolved_stress_written_from_field_reversed_to_ase_convention(reg: Registry) -> None:
    resolved = _resolved(reg, _parse(reg, _STRESS_EXTXYZ), choice="ase_sign_convention")
    buf = io.BytesIO()
    _exporter(reg).export(resolved, buf)
    reparsed = _reparse(reg, buf.getvalue())
    # The output carries the tensor in the exporter's declared target convention: the canonical
    # tension-positive value negated to ASE compression-positive (Part 2 §3.7.1). The Voigt-6
    # carry expands back to the same 3×3 the field held, sign-reversed.
    canonical = np.asarray(resolved.frames[0].electronic.stress)
    carried = _carry(reparsed)[0]
    assert carried.shape == (6,)  # ASE compresses the 3×3 to Voigt-6 on write
    assert np.allclose(_carry_tensor(reparsed), -canonical)
    assert not np.allclose(_carry_tensor(reparsed), canonical)  # the reversal really happened


def test_tension_positive_resolution_is_written_reversed_too(reg: Registry) -> None:
    # The exporter writes one declared convention regardless of how the source was resolved: even
    # a tension-positive choice is reversed on write to the ASE convention, because that is the
    # convention the output file carries (and the STRESS_SIGN_CONVENTION_CHANGED warning says so).
    resolved = _resolved(reg, _parse(reg, _STRESS_EXTXYZ), choice="tension_positive")
    buf = io.BytesIO()
    _exporter(reg).export(resolved, buf)
    reparsed = _reparse(reg, buf.getvalue())
    canonical = np.asarray(resolved.frames[0].electronic.stress)
    assert np.allclose(_carry_tensor(reparsed), -canonical)


def test_export_warnings_fire_for_a_populated_field_only(reg: Registry) -> None:
    exporter = _exporter(reg)
    resolved = _resolved(reg, _parse(reg, _STRESS_EXTXYZ))
    warnings = exporter.export_warnings(resolved)
    assert len(warnings) == 1
    (warning,) = warnings
    assert warning.code == "STRESS_SIGN_CONVENTION_CHANGED"
    assert "tension-positive" in warning.message and "compression-positive" in warning.message
    # An unresolved object (only the legacy carry) is written verbatim — no transformation, no
    # warning.
    assert exporter.export_warnings(_parse(reg, _STRESS_EXTXYZ)) == []


# --- unresolved fallback (done means #2: no regression) --------------------------------


def test_unresolved_object_writes_the_carry_verbatim(reg: Registry) -> None:
    source = _parse(reg, _STRESS_EXTXYZ)
    buf = io.BytesIO()
    _exporter(reg).export(source, buf)
    reparsed = _reparse(reg, buf.getvalue())
    # The numbers round-trip exactly as they came in — never sign-normalized, never promoted to a
    # field whose convention was never resolved (D18).
    assert np.allclose(_carry(reparsed)[0], _carry(source)[0])
    assert reparsed.frames[0].electronic.stress is None


def test_dual_source_prefers_the_populated_field(reg: Registry) -> None:
    # Defensive guard: if a resolved object somehow still holds the carry (S1 normally retires
    # it), the exporter writes the field — never both, never the stale carry.
    resolved = _resolved(reg, _parse(reg, _STRESS_EXTXYZ), choice="ase_sign_convention")
    um = resolved.user_metadata
    # A planted stale carry that differs from the field-derived value (Voigt [9,6,4,5,7,8] = a
    # [[9,7,8],[7,6,5],[8,5,4]] tensor).
    both = resolved.model_copy(
        update={
            "user_metadata": um.model_copy(
                update={"custom_per_frame": {"extxyz:stress": [[9.0, 6.0, 4.0, 5.0, 7.0, 8.0]]}}
            )
        }
    )
    buf = io.BytesIO()
    _exporter(reg).export(both, buf)
    reparsed = _reparse(reg, buf.getvalue())
    canonical = np.asarray(resolved.frames[0].electronic.stress)
    assert np.allclose(_carry_tensor(reparsed), -canonical)
    assert not np.allclose(
        _carry_tensor(reparsed), [[9.0, 7.0, 8.0], [7.0, 6.0, 5.0], [8.0, 5.0, 4.0]]
    )
    # The dropped carry is not silent: a differing dual source is reported as a warning.
    warnings = _exporter(reg).export_warnings(both)
    assert any(w.code == "STRESS_CARRY_DROPPED" for w in warnings)


def test_mixed_frames_write_stress_only_where_the_field_is_populated(reg: Registry) -> None:
    source = _parse(reg, _STRESS_MIXED_EXTXYZ)
    result = RecoveryEngine().resolve(
        source,
        [UnresolvedScenario(scenario="ambiguous_stress_convention", path="electronic.stress")],
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert result.canonical is not None
    resolved = result.canonical
    assert resolved.frames[0].electronic.stress is not None
    assert resolved.frames[1].electronic.stress is None
    buf = io.BytesIO()
    _exporter(reg).export(resolved, buf)
    reparsed = _reparse(reg, buf.getvalue())
    raw = reparsed.user_metadata.custom_per_frame["extxyz:stress"]
    assert isinstance(raw, list) and len(raw) == 2
    assert raw[1] is None  # per-frame association kept (Part 2 §6.1): frame 1 never carried it
    canonical = np.asarray(resolved.frames[0].electronic.stress)
    assert np.allclose(
        np.asarray(voigt_6_to_full_3x3_stress(np.asarray(raw[0], dtype=float))), -canonical
    )


# --- the write declaration obliges writing (Part 3 §4.2 contract) -----------------------


def test_write_declaration_is_partial_and_honest(reg: Registry) -> None:
    cap = _exporter(reg).capabilities().fields["electronic.stress"]
    assert cap.level is CapabilityLevel.PARTIAL
    assert cap.notes is not None
    # The note names both behaviours: the populated-field write (with the sign reversal) and the
    # verbatim carry fallback — never a claim the exporter cannot keep.
    assert "STRESS_SIGN_CONVENTION_CHANGED" in cap.notes
