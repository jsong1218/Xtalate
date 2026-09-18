"""xtalate-toyanalysis — a third-party analysis plugin, written from the docs alone.

The point of this fixture is *provenance*: it was built from ``docs/DEVELOPER_GUIDE.md`` §8
("Writing an analysis plugin") without copying the first-party reference plugin
(``xtalate-analysis-composition``), importing only the frozen public SDK
(``xtalate.sdk``) and schema (``xtalate.schema``) — exactly the surface §8.4 promises a third
party. It is deliberately dependency-free beyond the SDK: the one bit of arithmetic (a 3×3
determinant for cell volume) is done by hand rather than pulling in numpy, so the "a third party
can do this in an afternoon" claim (§8.1) is literal.

The science is trivial by design (§8.5: first-party analysis stops at one reference plugin;
anything real is a third party's to build). What it *does* exercise is the two things the docs
say a plugin must get right:

* the namespace rule (§8.2) — every key is ``"toyanalysis:"``-prefixed, so ``run_analysis``
  merges it whole; and
* absence honesty (§8.3, P3/P4) — ``cell_volume_a3`` is reported only when the source actually
  carries a cell, and its absence is stated in a plain-language ``*_note`` sibling rather than
  faked, mirroring the reference plugin's ``density_note``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from xtalate.schema import CanonicalObject
from xtalate.sdk import AnalysisPlugin

__all__ = ["ToyAnalysis", "cell_volume_a3"]


def cell_volume_a3(lattice_vectors: Sequence[Sequence[float]]) -> float:
    """|det| of the 3×3 lattice-vector matrix (rows a, b, c) in Å³.

    Expanded by hand along the first row so the fixture needs no numpy — the same determinant the
    reference plugin gets from ``np.linalg.det``, but dependency-free (§8.1).
    """
    m = [[float(x) for x in row] for row in lattice_vectors]
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    return abs(det)


class ToyAnalysis(AnalysisPlugin):
    """Trivial, absence-honest metrics — a third-party analysis plugin built from the docs."""

    name = "toyanalysis"
    version = "1.0.0"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        frame = canonical.frames[0]
        # `sorted(set(...))` is a list[str]; JsonValue's array branch is the invariant
        # list[JsonValue], so — exactly like the dict trap in §8.2 — a comprehension with the
        # declared target re-types each str against JsonValue (str ⊆ JsonValue) and passes.
        distinct: list[JsonValue] = [s for s in sorted(set(frame.atoms.symbols))]
        volume, note = _volume(canonical)
        return {
            "toyanalysis:frame_count": len(canonical.frames),
            "toyanalysis:atom_count": len(frame.atoms.symbols),
            "toyanalysis:distinct_elements": distinct,
            "toyanalysis:cell_volume_a3": volume,
            "toyanalysis:cell_volume_note": note,
        }


def _volume(canonical: CanonicalObject) -> tuple[float | None, str]:
    """Cell volume of frame 0 in Å³, or ``None`` with a stated reason (§8.3, P3/P4).

    Reported on frame 0 only, to keep this reference-of-a-reference trivial. The cell is never
    fabricated: a cell-less source has no volume, and that is *information*, not a gap to fill.
    """
    frame = canonical.frames[0]
    if frame.cell is None:
        return None, "cell volume not computed: no simulation cell declared in the source (P3)"
    # ``lattice_vectors`` is the schema's in-memory numpy array; take it to plain nested floats at
    # the seam so the arithmetic below (and this fixture's types) stay dependency-free.
    rows = [[float(x) for x in row] for row in frame.cell.lattice_vectors]
    volume = cell_volume_a3(rows)
    if volume == 0.0:
        return None, "cell volume not computed: the declared cell is degenerate (zero volume)"
    return volume, "cell volume computed on frame 0 from |det(lattice_vectors)|"
