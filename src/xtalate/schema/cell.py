"""Lattice geometry: cell parameters ↔ lattice vectors, and Cartesian ↔ fractional coordinates.

These live in ``schema`` because they are facts about the Canonical Model's cell, not about any
one format. "The lengths and angles of a lattice" and "the fractional coordinates of a Cartesian
position against it" are the same operations whichever grammar states them, and ``schema`` is the
one layer both ``parsers`` and ``exporters`` may import (Part 1 §5.1) — the same argument
``schema/paths.py`` already makes for ``OCCUPANCY_CUSTOM_KEY``.

They were previously three-way duplicated: ``lattice_from_parameters`` in the CIF *parser* and
``cell_parameters`` in the CIF *exporter* — a matched pair, in different layers, with no shared
exact-angle table — plus two verbatim copies of ``to_fractional`` in the CIF and XDATCAR
exporters. The split pair was not merely untidy: it is what let the write side lose the read
side's exactness guarantee for three milestones (D73). Two implementations of an inverse pair
will drift, and the drift is invisible in a diff of either one.

**Errors are ``ValueError``, not ``ParseError``.** ``schema`` sits below ``sdk``, where the parse
error contract lives, so an unrealizable cell is reported in the vocabulary this layer has and each
parser translates it into its own format-prefixed code. That is the correct direction anyway: the
geometry does not know it is being read from a file.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "ANGLE_SNAP_TOLERANCE_DEG",
    "EXACT_ANGLES_DEG",
    "cell_parameters",
    "cos_sin_deg",
    "lattice_from_parameters",
    "to_cartesian",
    "to_fractional",
]

_SQRT3_OVER_2 = math.sqrt(3.0) / 2.0

#: The cell angles crystallography states *exactly*: the right angle of every non-triclinic
#: system, and the 30/60/120/150° angles of the hexagonal and rhombohedral ones. libm evaluates
#: ``cos(radians(90))`` as 6.1e-17 rather than 0, so a lattice built through it is both spuriously
#: non-orthogonal — a 1e-16 tilt the source never declared, which P1 has no business inventing —
#: and machine-dependent in its last bit, since the platform's libm, not IEEE 754, decides that
#: digit. Both problems disappear by using the exact value the angle actually denotes.
_EXACT_COS_SIN_DEG: dict[float, tuple[float, float]] = {
    30.0: (_SQRT3_OVER_2, 0.5),
    60.0: (0.5, _SQRT3_OVER_2),
    90.0: (0.0, 1.0),
    120.0: (-0.5, _SQRT3_OVER_2),
    150.0: (-_SQRT3_OVER_2, 0.5),
}

#: The same angles, for the inverse direction. Keeping the table and its inverse in one module is
#: the whole point of this file: the forward map is worthless without the return, because an angle
#: that leaves as an exact 120.0 and comes back as 120.000000000000014 misses the table on the next
#: read and reintroduces exactly the tilt it exists to prevent (D73).
EXACT_ANGLES_DEG: tuple[float, ...] = tuple(sorted(_EXACT_COS_SIN_DEG))

#: 1e-9° is roughly five orders of magnitude below the precision CIF states angles to (1e-4°) and
#: five above the ~1e-14° error being absorbed, so it cannot reach a value a source really meant.
ANGLE_SNAP_TOLERANCE_DEG = 1e-9


def cos_sin_deg(degrees: float) -> tuple[float, float]:
    """``(cos, sin)`` of an angle in degrees, exact for the standard crystallographic angles."""
    exact = _EXACT_COS_SIN_DEG.get(degrees)
    if exact is not None:
        return exact
    radians = math.radians(degrees)
    return math.cos(radians), math.sin(radians)


def _snap_exact_angle(degrees: float) -> float:
    """A computed cell angle, snapped to the exact crystallographic value it is reproducing."""
    for exact in EXACT_ANGLES_DEG:
        if abs(degrees - exact) <= ANGLE_SNAP_TOLERANCE_DEG:
            return exact
    return degrees


def lattice_from_parameters(
    lengths: tuple[float, float, float], angles: tuple[float, float, float]
) -> np.ndarray:
    """Build the 3×3 lattice matrix (rows a, b, c, in Å) from cell parameters.

    CIF is the only Phase 1 format that states a cell as *parameters* rather than vectors, so an
    orientation convention has to be chosen; a≈+x with b in the xy half-plane is the
    crystallographic standard and is documented here because it is otherwise invisible. The choice
    is not observable in any physical quantity — lengths, angles, volume and all interatomic
    distances are rotation-invariant — but it *is* observable in the exported Cartesian
    coordinates, which is why it is pinned rather than left to floating-point luck.

    Raises ``ValueError`` if the angle triple describes no realizable cell.
    """
    a, b, c = lengths
    cos_alpha, _ = cos_sin_deg(angles[0])
    cos_beta, _ = cos_sin_deg(angles[1])
    cos_gamma, sin_gamma = cos_sin_deg(angles[2])

    cx = c * cos_beta
    cy = c * (cos_alpha - cos_beta * cos_gamma) / sin_gamma
    cz_squared = c * c - cx * cx - cy * cy
    if cz_squared <= 0.0:
        raise ValueError(
            f"cell angles alpha={angles[0]}, beta={angles[1]}, gamma={angles[2]} do not "
            "describe a realizable cell (the implied volume is zero or negative)"
        )
    return np.asarray(
        [
            [a, 0.0, 0.0],
            [b * cos_gamma, b * sin_gamma, 0.0],
            [cx, cy, math.sqrt(cz_squared)],
        ],
        dtype=float,
    )


def cell_parameters(
    lattice: np.ndarray,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Lattice vectors (rows a, b, c, Å) → ``((a, b, c), (alpha, beta, gamma))`` in Å and degrees.

    The exact inverse of :func:`lattice_from_parameters`, standard angles included, and the reason
    a round-trip holds regardless of orientation: lengths and angles are rotation-invariant, so a
    cell that was re-oriented on the way in (or arrived from a format that states vectors directly)
    comes back out with the parameters it always had. ``alpha`` is the angle between **b** and
    **c**, per the crystallographic convention that each angle is opposite its like-named axis.
    """
    a, b, c = (np.asarray(row, dtype=float) for row in lattice)
    la, lb, lc = (float(np.linalg.norm(v)) for v in (a, b, c))

    def angle(u: np.ndarray, v: np.ndarray, lu: float, lv: float) -> float:
        # Clamped because a floating-point dot product of near-parallel vectors can leave the
        # cosine a few ulp outside [-1, 1], where acos is a domain error rather than 0° or 180°.
        cosine = float(np.dot(u, v)) / (lu * lv)
        return _snap_exact_angle(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))

    return (la, lb, lc), (angle(b, c, lb, lc), angle(a, c, la, lc), angle(a, b, la, lb))


def to_fractional(positions: np.ndarray, lattice: np.ndarray) -> np.ndarray:
    """Cartesian Å → fractional against ``lattice`` (rows a, b, c).

    ``cart = frac @ lattice``, so ``frac`` solves ``lattice.T @ frac.T = cart.T``. Solved rather
    than multiplied by an explicit inverse: on the skewed cells low-symmetry crystals and MD cells
    routinely have, a solve is the better-conditioned of the two and keeps the inversion error at
    the ulp level the declared representational bound assumes.
    """
    return np.asarray(np.linalg.solve(lattice.T, positions.T).T)


def to_cartesian(fractional: np.ndarray, lattice: np.ndarray) -> np.ndarray:
    """Fractional → Cartesian Å against ``lattice`` (rows a, b, c).

    ``cart = fx·a + fy·b + fz·c``, which is the plain matrix product because the lattice rows *are*
    a, b, c. Trivial enough to inline, and named anyway so the rows-are-vectors convention is
    asserted in one place rather than restated in a comment at each call site — the convention is
    the part that is easy to get silently backwards.
    """
    return np.asarray(np.asarray(fractional, dtype=float) @ np.asarray(lattice, dtype=float))
