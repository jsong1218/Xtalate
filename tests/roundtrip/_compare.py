"""Subspace-restricted Canonical comparison for the three-hop suite (not a test module).

The two-hop suite reuses the Validation Engine for its diff (it already compares a re-parsed output
against the write-plan projection under a tolerance profile, and asserts removed paths absent). The
three-hop suite returns all the way to format A, so it needs to diff two *whole* Canonical Objects
— the golden-anchored original and the `A → B → A` result — but only over the comparable subspace
the Capability Matrix says both formats round-trip fully (Part 8 §2.3). Hence a dedicated comparator
(DECISIONS.md D49): arrays within the strict profile's per-quantity ``fail`` bound, everything else
exact.
"""

from __future__ import annotations

import numpy as np

from xtalate.schema import CanonicalObject, Frame
from xtalate.validation._shared import NUMERIC_QUANTITY as _FIDELITY_QUANTITY
from xtalate.validation.tolerance import ToleranceProfile

# Leaf path -> the tolerance quantity its numeric comparison uses. The fidelity fields are taken
# from the Validation Engine's single catalog (`validation._shared`), so a field added there is
# compared here too rather than silently skipped. The whole-object three-hop comparator additionally
# diffs `atoms.positions`/`cell.lattice_vectors` as arrays (the engine handles those via its
# dedicated `positions_rmsd`/`lattice_consistency` checks, so they are not in the shared catalog).
# Paths absent here are compared exactly (symbols, pbc — discrete, no tolerance ever).
_NUMERIC_QUANTITY: dict[str, str] = {
    **_FIDELITY_QUANTITY,
    "atoms.positions": "positions",
    "cell.lattice_vectors": "lattice",
}


def _leaf_value(frame: Frame, path: str) -> object:
    """Fetch a leaf path's value from one frame, or ``None`` if the containing block is absent."""
    if path == "frame.time":
        return frame.time
    if path == "atoms.positions":
        return frame.atoms.positions
    if path == "atoms.symbols":
        return list(frame.atoms.symbols)
    if path == "atoms.masses":
        return frame.atoms.masses
    group, _, name = path.partition(".")
    block = {"cell": frame.cell, "dynamics": frame.dynamics, "electronic": frame.electronic}.get(
        group
    )
    return getattr(block, name, None) if block is not None else None


def assert_equal_over_subspace(
    a: CanonicalObject, b: CanonicalObject, paths: set[str], profile: ToleranceProfile
) -> None:
    """Assert ``a`` and ``b`` agree on every leaf in ``paths``, frame by frame, under ``profile``.

    Numeric leaves are compared with ``np.allclose`` at the quantity's ``fail`` bound (the strict
    profile's bound in the round-trip suite); symbols and other discrete values must match exactly.
    A frame-count mismatch or a value present on one side but absent on the other is a failure."""
    assert a.frame_count == b.frame_count, (
        f"frame count diverged over the round-trip: {a.frame_count} != {b.frame_count}"
    )
    for i in range(a.frame_count):
        fa, fb = a.frames[i], b.frames[i]
        for path in sorted(paths):
            va, vb = _leaf_value(fa, path), _leaf_value(fb, path)
            if va is None and vb is None:
                continue
            assert va is not None and vb is not None, (
                f"frame {i}, {path}: present on one side only "
                f"(a={'absent' if va is None else 'present'}, "
                f"b={'absent' if vb is None else 'present'})"
            )
            quantity = _NUMERIC_QUANTITY.get(path)
            if quantity is None:
                assert va == vb, f"frame {i}, {path}: {va!r} != {vb!r}"
                continue
            atol = profile.effective(quantity).fail
            arr_a = np.asarray(va, dtype=float)
            arr_b = np.asarray(vb, dtype=float)
            assert arr_a.shape == arr_b.shape, (
                f"frame {i}, {path}: shape {arr_a.shape} != {arr_b.shape}"
            )
            assert np.allclose(arr_a, arr_b, atol=atol, rtol=0.0), (
                f"frame {i}, {path}: max |Δ| {np.abs(arr_a - arr_b).max():.3e} exceeds strict "
                f"tolerance {atol:.3e}"
            )
