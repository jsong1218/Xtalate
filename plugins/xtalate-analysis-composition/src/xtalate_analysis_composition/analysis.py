"""xtalate-analysis-composition — the reference analysis plugin (M69).

Deliberately trivial science, deliberately exemplary honesty: element counts, a reduced Hill
formula, and mass density — with density reported **only** when the source actually carries a
cell and masses, and its absence stated in plain language otherwise (P3, P4). The plugin never
fabricates masses; filling absent data is recovery's job, and recovery is explicit.

Imports only the frozen public SDK (``xtalate.sdk``) and schema (``xtalate.schema``), exactly as a
third-party plugin must — an import-linter contract in the parent repo proves it.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from pydantic import JsonValue

from xtalate.schema import CanonicalObject
from xtalate.sdk import AnalysisPlugin

__all__ = ["CompositionAnalysis", "element_counts", "hill_formula"]

# CODATA unified atomic mass unit in grams: 1 u = 1.66053906660e-24 g. With cell volume in Å³
# (1 Å³ = 1e-24 cm³), the 1e-24 cancels, leaving this single dimensionless factor in g/cm³.
_U_IN_GRAMS_TIMES_CM3_PER_A3 = 1.66053906660


def element_counts(symbols: list[str]) -> dict[str, int]:
    """Per-element atom counts, insertion-ordered by first appearance."""
    counts: dict[str, int] = {}
    for s in symbols:
        counts[s] = counts.get(s, 0) + 1
    return counts


def hill_formula(counts: Mapping[str, int]) -> str:
    """Reduced empirical formula in Hill notation.

    Carbon first, hydrogen second, then all remaining elements alphabetical; when no carbon is
    present, every element (hydrogen included) is alphabetical. A count of 1 is written bare.
    """

    def term(symbol: str) -> str:
        n = counts[symbol]
        return symbol if n == 1 else f"{symbol}{n}"

    others = sorted(s for s in counts if s not in ("C", "H"))
    if "C" in counts:
        ordered = ["C"] + (["H"] if "H" in counts else []) + others
    else:
        ordered = sorted(counts)
    return "".join(term(s) for s in ordered)


class CompositionAnalysis(AnalysisPlugin):
    """Element counts, reduced formula, and mass density — the reference analysis plugin."""

    name = "composition"
    version = "1.0.0"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        frame = canonical.frames[0]
        counts = element_counts(frame.atoms.symbols)
        density, note = _density(canonical)
        # `counts` is a dict[str, int]; JsonValue's object branch is the invariant dict[str,
        # JsonValue], so a plain dict[str, int] is not assignable to it. A comprehension with the
        # declared target type re-types each int against JsonValue (int ⊆ JsonValue) and passes.
        counts_json: dict[str, JsonValue] = {sym: n for sym, n in counts.items()}
        return {
            "composition:formula": hill_formula(counts),
            "composition:element_counts": counts_json,
            "composition:atom_count": len(frame.atoms.symbols),
            "composition:mass_density_g_per_cm3": density,
            "composition:density_note": note,
        }


def _density(canonical: CanonicalObject) -> tuple[float | None, str]:
    """Mass density of frame 0 in g/cm³, or ``None`` with a stated reason (P3/P4).

    Reported on frame 0 only: element counts are constant across frames (constant-N), and a single
    representative density keeps this reference plugin trivial by design. Requires both a cell and
    masses; neither is ever fabricated.
    """
    frame = canonical.frames[0]
    if frame.cell is None:
        return None, "mass density not computed: no simulation cell declared in the source"
    if frame.atoms.masses is None:
        return None, (
            "mass density not computed: the source declared no atomic masses, and this plugin "
            "never fills them (filling is recovery's job, and recovery is explicit — P4)"
        )
    volume_a3 = abs(float(np.linalg.det(np.asarray(frame.cell.lattice_vectors, dtype=float))))
    if volume_a3 == 0.0:
        return None, "mass density not computed: the declared cell has zero volume"
    total_mass_u = float(np.sum(frame.atoms.masses))
    density = total_mass_u / volume_a3 * _U_IN_GRAMS_TIMES_CM3_PER_A3
    return density, "mass density computed on frame 0 from total atomic mass / cell volume"
