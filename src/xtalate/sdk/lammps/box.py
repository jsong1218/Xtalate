"""Triclinic box-bounds ↔ lattice-vectors mapping (M46; the shared `_lammps` core).

LAMMPS dump files write the box on three ``ITEM: BOX BOUNDS`` rows: for an orthogonal
box just ``xlo xhi`` / ``ylo yhi`` / ``zlo zhi``; for a restricted triclinic box the
header line gains ``xy xz yz`` and each row carries the tilt of its trailing dimension.

**The bound-vs-edge subtlety (verified against LAMMPS's "Triclinic (non-orthogonal)
simulation boxes" howto, https://docs.lammps.org/Howto_triclinic.html, accessed
2026-08).** The restricted triclinic box is defined by its *edge* parameters
``(xlo, xhi, ylo, yhi, zlo, zhi, xy, xz, yz)`` with edge vectors

    a = (xhi−xlo, 0, 0),  b = (xy, yhi−ylo, 0),  c = (xz, yz, zhi−zlo),

but a dump file does **not** write those bounds directly: it writes the *axis-aligned
bounding box* that encloses the tilted cell, computed from the restricted parameters as

    xlo_bound = xlo + MIN(0, xy, xz, xy+xz)      xhi_bound = xhi + MAX(0, xy, xz, xy+xz)
    ylo_bound = ylo + MIN(0, yz)                 yhi_bound = yhi + MAX(0, yz)
    zlo_bound = zlo                              zhi_bound = zhi

(the doc's exact formulas, under "Output of restricted and general triclinic boxes in a
dump file"). A naive ``a = (xhi_bound − xlo_bound, …)`` therefore builds the wrong cell
whenever any tilt is non-zero — the *edge* length is recovered by inverting the
bounding-box formulas first:

    xlo = xlo_bound − MIN(0, xy, xz, xy+xz)      xhi = xhi_bound − MAX(0, xy, xz, xy+xz)
    ylo = ylo_bound − MIN(0, yz)                 yhi = yhi_bound − MAX(0, yz)

The orthogonal box is the tilt=0 special case: the inversion is the identity and the
three edge vectors are diagonal.

Scaled (``xs``/``ys``/``zs``) coordinates are fractional in the tilted box, so the
scaled→Cartesian helper mapping is ``r = origin + frac·lattice`` where ``origin = (xlo, ylo,
zlo)`` — the same mapping LAMMPS itself uses (``x = xlo + sx·lx + sy·xy + sz·xz`` etc.,
per the howto's general-to-restricted discussion). The LAMMPS dump parser subtracts that origin
after using this helper because canonical dump positions are expressed relative to the lower box
corner, matching its unscaled-coordinate branch and the exporter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Box:
    """A LAMMPS box in canonical form: an explicit lattice plus its origin (Å).

    ``lattice`` holds the edge vectors as rows (``a``, ``b``, ``c``), so the
    scaled→Cartesian mapping is the single matrix multiply ``frac @ lattice + origin``. The
    dump parser removes ``origin`` after this absolute helper mapping when constructing canonical
    positions; data-file coordinates remain absolute as written.
    """

    lattice: np.ndarray  # 3×3, row vectors (Å)
    origin: np.ndarray  # (xlo, ylo, zlo) (Å)


def box_from_bounds(
    xlo: float,
    xhi: float,
    ylo: float,
    yhi: float,
    zlo: float,
    zhi: float,
    *,
    xy: float = 0.0,
    xz: float = 0.0,
    yz: float = 0.0,
) -> Box:
    """Build the canonical box from a dump's ``ITEM: BOX BOUNDS`` rows.

    The six bounds are whatever the dump row states — for a triclinic box these are the
    *bounding-box* values ``xlo_bound … zhi_bound``, which are inverted to the restricted
    edge parameters before the edge vectors are formed (the bound-vs-edge subtlety
    above). ``xy``/``xz``/``yz`` default to zero, which makes the orthogonal
    ``ITEM: BOX BOUNDS`` (two-column rows) the tilt=0 special case with no extra call.
    """

    # Invert the bounding-box formulas (Howto_triclinic, "Output of … dump file").
    xlo_restricted = xlo - min(0.0, xy, xz, xy + xz)
    xhi_restricted = xhi - max(0.0, xy, xz, xy + xz)
    ylo_restricted = ylo - min(0.0, yz)
    yhi_restricted = yhi - max(0.0, yz)
    lx = xhi_restricted - xlo_restricted
    ly = yhi_restricted - ylo_restricted
    lz = zhi - zlo
    lattice = np.array([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]], dtype=np.float64)
    return Box(
        lattice=lattice,
        origin=np.array([xlo_restricted, ylo_restricted, zlo], dtype=np.float64),
    )


def box_from_edges(
    xlo: float,
    xhi: float,
    ylo: float,
    yhi: float,
    zlo: float,
    zhi: float,
    *,
    xy: float = 0.0,
    xz: float = 0.0,
    yz: float = 0.0,
) -> Box:
    """Build the canonical box from a LAMMPS **data** file's box header (M48).

    Unlike a dump (:func:`box_from_bounds`), a data file writes the *restricted edge
    parameters directly* — ``xlo xhi`` / ``ylo yhi`` / ``zlo zhi`` and the optional
    ``xy xz yz`` line are the edge lengths and tilts themselves, **not** the axis-aligned
    bounding box (LAMMPS "read_data" / "write_data" command docs,
    https://docs.lammps.org/read_data.html, accessed 2026-08). So no bound-vs-edge
    inversion is applied: the edge vectors are formed straight from the parameters,

        a = (xhi−xlo, 0, 0),  b = (xy, yhi−ylo, 0),  c = (xz, yz, zhi−zlo),

    with ``origin = (xlo, ylo, zlo)``. The orthogonal box is the tilt=0 special case
    (a data file with no ``xy xz yz`` line), where this and :func:`box_from_bounds`
    coincide; they diverge only when a tilt is non-zero — which is exactly why the two
    conventions are separate helpers rather than one, so neither format silently reads
    the other's box.
    """
    lx = xhi - xlo
    ly = yhi - ylo
    lz = zhi - zlo
    lattice = np.array([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]], dtype=np.float64)
    return Box(lattice=lattice, origin=np.array([xlo, ylo, zlo], dtype=np.float64))


def edges_from_box(
    lattice: np.ndarray,
) -> tuple[float, float, float, float, float, float]:
    """The inverse of :func:`box_from_edges` (M48-S2): a restricted triclinic lattice → a data
    file's edge parameters ``(lx, ly, lz, xy, xz, yz)``.

    A data file writes edge lengths and tilts *directly* — not the dump's axis-aligned bounding
    box — so the inverse is a plain read-off of the restricted lattice rows: ``lx = a_x``,
    ``ly = b_y``, ``lz = c_z``, ``xy = b_x``, ``xz = c_x``, ``yz = c_y``. There is deliberately
    **no** inverse for the origin: the parser drops the source box origin (canonical positions are
    absolute Cartesian), so the exporter writes a zero-origin box — ``xlo=0, xhi=lx`` … — which
    preserves every inter-atomic distance and the cell shape exactly. A lattice outside the
    restricted form is refused upstream (``unrepresentable``), never silently rotated here; this is
    the write-side twin of ``box_from_edges``, kept separate from :func:`box_from_bounds`'s
    bounding-box convention so neither format writes the other's box.
    """
    lx = float(lattice[0, 0])
    ly = float(lattice[1, 1])
    lz = float(lattice[2, 2])
    xy = float(lattice[1, 0])
    xz = float(lattice[2, 0])
    yz = float(lattice[2, 1])
    return lx, ly, lz, xy, xz, yz


def scaled_to_cartesian(scaled: np.ndarray, box: Box) -> np.ndarray:
    """Convert ``(N, 3)`` scaled (``xs``/``ys``/``zs``) coordinates to Cartesian Å.

    Scaled coordinates are fractional in the tilted box (0..1 in each direction), so the
    conversion is the single affine map ``r = frac·lattice + origin`` — exactly the
    mapping LAMMPS applies for its restricted triclinic box (the howto's
    ``x = xlo + sx·lx + sy·xy + sz·xz`` …).
    """
    result: np.ndarray = scaled @ box.lattice + box.origin
    return result
