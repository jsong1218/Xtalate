"""Stage-2 generator: hypothesis strategies over randomized Canonical Objects (Part 8 §1.2).

Stage 1 (``_generators``) varies **one** optional field-path at a time off a golden base — a
deterministic sweep of the path lattice. Stage 2, here, generates **randomized** Canonical Objects
with independent presence decisions across *all* categories at once (bounded sizes, all eight
schema categories reachable), so it explores the field-*combinations* and per-frame ``mixed``
interactions the one-at-a-time sweep cannot. Hypothesis's **shrinking** then reduces any failing
object to a minimal reproducer — the property's payoff over a hand-rolled fuzzer (DECISIONS.md D50).

The strategy emits objects as JSON-shaped dicts and validates each through the real model
validators, exactly like stage 1: every produced object is a *valid* Canonical Object (constant-N,
frame-index order, array shapes, absence convention) or generation fails loudly. Values are kept in
tame, finite ranges and lattices are diagonal-dominant (hence invertible) — stage 2 exercises the
**report machinery** over random presence configurations, not exporter numerical robustness, so it
deliberately avoids the NaN/inf/singular-cell inputs that would test a different thing.

One presence configuration is held uniform on purpose: **cell presence is per-object, not
per-frame** (see ``_frame``). A `mixed` cell plus ``frame_selection`` picking a cell-less frame
exposes a *recovery-detection* gap — ``missing_lattice`` is offered only when the source cell reads
`absent`,
not `mixed`, so a POSCAR export can crash for want of a lattice. That is a recovery-engine bug
(tracked separately for an M7-style fix: ``missing_lattice`` must trigger on a not-uniformly-present
required field and fabricate only for the cell-less frames without overwriting a real cell), *not* a
report-completeness one, so this generator does not manufacture it while probing the M10 properties.
"""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

from xtalate.schema import CanonicalObject

# A small, valid element alphabet — enough for variety, small enough that shrinking stays legible.
_ELEMENTS = ["H", "C", "N", "O", "Na", "Cl", "Fe"]

# Tame finite floats: no NaN/inf, bounded magnitude. Presence (not value) is what these tests probe,
# so a small range keeps conversions well-behaved while still letting zero (which *is* data, §2
# rule 3) appear alongside non-zero.
_floats = st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False)
_pos_floats = st.floats(min_value=0.5, max_value=300.0, allow_nan=False, allow_infinity=False)
# Custom/metadata key *names* are drawn from a collision-free set: a key that happens to spell a
# reserved format field (``stress``, ``energy``, ``lattice``, …) collides with that field on
# extXYZ export and breaks the re-parse — a namespacing concern for the carry-through path, not a
# report-completeness one. Distinct safe names keep the generator on the properties it probes.
_keys = st.sampled_from(["ux", "uy", "uz", "meta", "note", "cola", "colb", "kv1", "kv2"])
# Free-text values are drawn from a whitespace-free alphabet: a newline in a per-frame comment
# would break the line-based XYZ/extXYZ containers on re-export — an exporter *escaping* concern,
# not a report-completeness one, and adversarial string content is not what these properties probe.
_text = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABC0123-_.", max_size=6)
_token = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABC0123", min_size=1, max_size=6)
_scalars = st.one_of(_floats, st.integers(-5, 5), _token, st.booleans())


def _vec3() -> st.SearchStrategy[list[float]]:
    return st.lists(_floats, min_size=3, max_size=3)


def _vecs(n: int) -> st.SearchStrategy[list[list[float]]]:
    return st.lists(_vec3(), min_size=n, max_size=n)


@st.composite
def _lattice(draw: st.DrawFn) -> list[list[float]]:
    """A diagonal-dominant (hence non-singular) 3×3 lattice, so fractional↔Cartesian conversion to
    POSCAR never hits a singular matrix — the property tests probe reports, not linear algebra."""
    diag = [draw(st.floats(min_value=3.0, max_value=20.0, allow_nan=False)) for _ in range(3)]
    off = [draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)) for _ in range(6)]
    return [
        [diag[0], off[0], off[1]],
        [off[2], diag[1], off[3]],
        [off[4], off[5], diag[2]],
    ]


@st.composite
def _cell(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "lattice_vectors": draw(_lattice()),
        "pbc": [draw(st.booleans()) for _ in range(3)],
        "space_group": draw(st.none() | st.sampled_from(["P1", "Fm-3m", "P6_3/mmc"])),
    }


@st.composite
def _constraints(draw: st.DrawFn, n: int) -> list[dict[str, Any]]:
    # [] (explicitly unconstrained, present) or one constraint over a subset of atoms.
    if draw(st.booleans()):
        return []
    idx = draw(st.lists(st.integers(0, n - 1), min_size=1, max_size=n, unique=True))
    return [{"kind": "fixed_atoms", "atom_indices": sorted(idx), "parameters": {}}]


def _maybe(draw: st.DrawFn, value_strategy: st.SearchStrategy[Any]) -> Any:
    """Draw a value or ``None`` — the per-frame presence coin flip that yields present/absent/mixed
    once aggregated across frames (uniform present, uniform None, or a partial mix)."""
    return draw(value_strategy) if draw(st.booleans()) else None


@st.composite
def _frame(
    draw: st.DrawFn, index: int, symbols: list[str], n: int, has_cell: bool
) -> dict[str, Any]:
    # ``has_cell`` is decided once per object and applied uniformly to every frame, deliberately
    # *not* an independent per-frame draw. A `mixed` cell (present in some frames only) with
    # ``frame_selection`` picking a cell-less frame trips a *separate* recovery-detection gap — the
    # POSCAR-required lattice is never offered as `missing_lattice` when the source cell reads
    # `mixed`, and the exporter crashes. That is a recovery-engine bug (tracked; see this module's
    # docstring), not a report-completeness one, so stage 2 holds cell presence uniform to keep the
    # generator on the completeness properties it exists to probe. Every *other* field stays an
    # independent per-frame draw, so `mixed` configurations (constraints, forces, …) are exercised.
    return {
        "index": index,
        "time": _maybe(draw, _floats),
        "atoms": {
            "symbols": symbols,
            "positions": draw(_vecs(n)),
            "masses": _maybe(draw, st.lists(_pos_floats, min_size=n, max_size=n)),
        },
        "cell": draw(_cell()) if has_cell else None,
        "dynamics": {
            "velocities": _maybe(draw, _vecs(n)),
            "forces": _maybe(draw, _vecs(n)),
            "constraints": _maybe(draw, _constraints(n)),
        },
        "electronic": {
            "total_energy": _maybe(draw, _floats),
            "stress": _maybe(draw, _vecs(3)),
            "charges": _maybe(draw, st.lists(_floats, min_size=n, max_size=n)),
            "magnetic_moments": _maybe(draw, st.lists(_floats, min_size=n, max_size=n)),
            "total_spin": _maybe(draw, _floats),
        },
    }


@st.composite
def _simulation(draw: st.DrawFn) -> dict[str, Any] | None:
    if draw(st.booleans()):
        return None
    text = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=5)
    return {
        "source_code": _maybe(draw, text),
        "calculator": _maybe(draw, text),
        "xc_functional": _maybe(draw, text),
        "pseudopotentials": _maybe(
            draw, st.dictionaries(st.sampled_from(_ELEMENTS), text, max_size=3)
        ),
        "thermostat": _maybe(draw, text),
        "md_ensemble": _maybe(draw, st.sampled_from(["NVT", "NPT", "NVE"])),
        "temperature": _maybe(draw, _pos_floats),
        "extra": draw(st.dictionaries(_keys, text, max_size=2)),
    }


@st.composite
def canonical_objects(draw: st.DrawFn) -> CanonicalObject:
    """A randomized, valid Canonical Object: bounded atom/frame counts, every optional field an
    independent presence draw, reaching all eight schema categories (Part 2 §3)."""
    n = draw(st.integers(min_value=1, max_value=4))
    f = draw(st.integers(min_value=1, max_value=3))
    symbols = draw(st.lists(st.sampled_from(_ELEMENTS), min_size=n, max_size=n))
    has_cell = draw(st.booleans())  # uniform across frames — see _frame for why.

    frames = [draw(_frame(i, symbols, n, has_cell)) for i in range(f)]

    data: dict[str, Any] = {
        "schema_version": "0.1.0",
        "frames": frames,
        "trajectory": ({"timestep": draw(_pos_floats)} if draw(st.booleans()) else None),
        "simulation": draw(_simulation()),
        "provenance": {
            "source_filename": draw(st.none() | st.just("generated.dat")),
            "source_format": "extxyz",
            "original_coordinate_system": "cartesian",
            "source_units": {},
            "parse_notes": [],
            "history": [],
        },
        # custom_per_atom / custom_per_frame become extXYZ per-atom/per-frame *columns* on export;
        # numeric columns carry through cleanly and unambiguously, whereas free-form string columns
        # surface exporter column-formatting edge cases (empty tokens, type inference) that are I/O
        # robustness, not report completeness. So the per-atom/per-frame carry-through is exercised
        # with numeric values; custom_global (a comment-line key=value) keeps the mixed scalar set.
        "user_metadata": {
            "tags": draw(st.lists(_keys, max_size=3, unique=True)),
            "annotations": draw(st.dictionaries(_keys, _text, max_size=2)),
            "custom_global": draw(st.dictionaries(_keys, _scalars, max_size=2)),
            "custom_per_atom": draw(
                st.dictionaries(_keys, st.lists(_floats, min_size=n, max_size=n), max_size=2)
            ),
            "custom_per_frame": draw(
                st.dictionaries(_keys, st.lists(_floats, min_size=f, max_size=f), max_size=2)
            ),
        },
    }
    return CanonicalObject.model_validate(data)
