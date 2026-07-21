"""Scientific invariants: physics-derived quantities computed from a Canonical Object.

MASTER_SPEC Part 8 §1.3. Structural equality proves *fields survived*; it does not prove the
object describes the same physical system. These helpers compute quantities that are sensitive
exactly where a field diff is blind, and they are deliberately **independent re-derivations** —
nothing here imports the parser code path it is used to check, so an invariant and the
implementation cannot agree by construction.

The v0.4 caller is the CIF golden suite (M18 deliverable 5), where symmetry expansion makes the
atom set itself a computed thing. The three invariants below are the ones an expansion bug
cannot hide from:

* **Stoichiometry** — the element multiset against the published formula-unit count Z. A dropped
  operation yields a fraction of the atoms; an over-generating one yields a multiple. Both change
  this multiset, and neither changes any *field* that a structural diff inspects.
* **Cell volume** — computed from the constructed ``lattice_vectors`` and cross-checked against
  the volume implied by the source's own cell *parameters*. CIF is the one Phase 1 format that
  declares a, b, c, α, β, γ rather than vectors, so this pair of derivations is genuinely
  independent and catches a row/column transposition in the construction that element-wise
  comparison against a symmetric test cell would pass.
* **Minimum interatomic distance** — the sharpest expansion check there is. A special-position
  merge that failed to fire leaves two atoms at essentially zero separation, which no count-based
  assertion notices when the operation list is symmetric enough for the totals to look plausible.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from itertools import product

import numpy as np
import numpy.typing as npt

# The canonical model stores positions and lattice vectors as numpy arrays, but these helpers
# are also handed plain nested lists by tests that construct a case inline. Accepting ArrayLike
# keeps one implementation for both rather than a conversion dance at every call site.
Lattice = npt.ArrayLike
Positions = npt.ArrayLike


def stoichiometry(symbols: Sequence[str]) -> Counter[str]:
    """The element multiset — order-independent, so an atom reordering never registers here."""
    return Counter(symbols)


def formula_unit_multiple(symbols: Sequence[str], unit: dict[str, int]) -> float:
    """How many times ``unit`` divides the structure's element multiset — the observed Z.

    Returns a float so a *non-integral* result (the signature of a partially expanded cell)
    surfaces as a wrong number rather than being rounded into a plausible-looking one. Raises
    if an element appears that the formula unit does not mention, since that is a species bug
    rather than a count bug and deserves its own failure.
    """
    counts = stoichiometry(symbols)
    unexpected = set(counts) - set(unit)
    if unexpected:
        raise AssertionError(
            f"element(s) absent from the formula unit {unit}: {sorted(unexpected)}"
        )
    ratios = {element: counts.get(element, 0) / n for element, n in unit.items()}
    if len(set(ratios.values())) != 1:
        raise AssertionError(
            f"element counts are not a whole-structure multiple of {unit}: {dict(counts)} "
            f"gives per-element multiples {ratios} — the structure is not this compound"
        )
    return next(iter(ratios.values()))


def cell_volume(lattice: Lattice) -> float:
    """|det| of the 3×3 lattice matrix, in Å³ — rows-are-vectors, the canonical convention."""
    return abs(float(np.linalg.det(np.asarray(lattice, dtype=float))))


def volume_from_parameters(
    a: float, b: float, c: float, alpha: float, beta: float, gamma: float
) -> float:
    """Cell volume from the six crystallographic parameters, angles in degrees.

    V = abc·√(1 − cos²α − cos²β − cos²γ + 2·cosα·cosβ·cosγ). This is the *source's* statement of
    the cell, computed without touching the lattice-vector construction, which is what makes it
    an independent check of that construction rather than a restatement of it.
    """
    ca, cb, cg = (math.cos(math.radians(x)) for x in (alpha, beta, gamma))
    return a * b * c * math.sqrt(1 - ca * ca - cb * cb - cg * cg + 2 * ca * cb * cg)


def minimum_interatomic_distance(positions: Positions, lattice: Lattice | None) -> float:
    """The shortest distance between any two atoms, in Å, under the minimum-image convention.

    With ``lattice`` given, each pair is compared against its images in the 27 cells of the
    3×3×3 neighbourhood. That is exact for the near-orthogonal cells this suite uses and for any
    cell whose reduction is not severely skewed; it is *not* a general minimum-image routine, and
    is not offered as one — a badly skewed cell would need a full Minkowski reduction, which no
    fixture here requires.

    No wrapping is applied to the input (parsers and exporters must never wrap, Part 2 §4); the
    periodicity lives in the image search, not in the coordinates.
    """
    coordinates = np.asarray(positions, dtype=float)
    if len(coordinates) < 2:
        raise AssertionError("a minimum interatomic distance needs at least two atoms")

    deltas = coordinates[:, None, :] - coordinates[None, :, :]
    pairs = np.triu_indices(len(coordinates), k=1)
    separations = deltas[pairs]

    if lattice is None:
        return float(np.min(np.linalg.norm(separations, axis=1)))

    cell = np.asarray(lattice, dtype=float)
    offsets = np.asarray(list(product((-1, 0, 1), repeat=3)), dtype=float)
    shifts = offsets @ cell
    candidates = np.linalg.norm(separations[:, None, :] + shifts[None, :, :], axis=2)

    # An atom and its *own* image in a neighbouring cell are two distinct atoms of the crystal,
    # so the shortest contact in a small cell is often this self-pair (in a 2-atom cell it
    # usually is — the a-axis repeat). Excluding it would report a "nearest-neighbour distance"
    # no diffractionist would recognise. The zero shift is dropped for these pairs only, since
    # an atom is not its own neighbour at distance 0.
    nonzero = shifts[np.any(offsets != 0, axis=1)]
    self_images = np.linalg.norm(nonzero, axis=1)

    return float(min(np.min(candidates), np.min(self_images)))
