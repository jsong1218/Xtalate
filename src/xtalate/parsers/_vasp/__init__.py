"""Shared VASP label-extraction core (v1.2 M42-S2; DECISIONS.md D160).

Pure mapping functions from *parsed VASP values* → canonical fields, with **no XML or
text knowledge** — so both vasprun.xml (M42-S2) and OUTCAR (M43) feed it, and two parsers
reading one run cannot co-discover divergent mappings (the divergence risk the shared core
exists to prevent). It is a mapping layer, not a reader: it imports only ``xtalate.schema``
(and numpy), never an XML/text module, never another parser (P2).

The core owns the mapping *decisions* so they are pinned in exactly one place:

* **Energy** — ``electronic.total_energy`` is the VASP ``e_0_energy`` tag (the energy
  extrapolated to zero smearing width, VASP's ``energy(sigma->0)`` in OUTCAR), not the free
  energy ``e_fr_energy`` (TOTEN, which includes the finite-smearing entropy term).
* **Positions** — vasprun.xml declares its positions in direct (fractional) coordinates,
  converted to Cartesian at the parser boundary using *that step's* lattice; a
  ``mode="cartesian"`` varray is read as-is.
* **Forces** — verbatim eV/Å (VASP already writes canonical units).
* **Cell** — the ``<crystal>`` basis rows assemble ``cell.lattice_vectors``; ``pbc`` is
  (T,T,T) by format definition (VASP is always fully periodic).
* **Species** — derived from the ``atominfo`` species table's atomic numbers (Z), in
  declared species order, one symbol per atom.

**Stress (M42-S3)** — VASP declares its convention, so the mapping is deterministic and
recorded, never asked: the kBar tensor is sign-flipped (VASP is compression-positive,
canonical tension-positive) and divided by the exact factor ``K_BAR_PER_EV_A3``; the
VASP Voigt-6 → 3×3 helper uses VASP ordering ``[XX, YY, ZZ, XY, YZ, ZX]`` and is
**deliberately not** ASE's ordering (the off-diagonal transpose hazard, D161).
"""

from __future__ import annotations

from xtalate.parsers._vasp.labels import (
    K_BAR_PER_EV_A3,
    TOTAL_ENERGY_TAG,
    build_cell,
    coordinate_parse_note,
    energy_parse_note,
    forces,
    lattice_vectors,
    parse_notes_for,
    positions,
    source_code_parse_note,
    stress_from_vasp_kbar,
    stress_parse_note,
    stress_voigt6_vasp_to_full,
    symbols_from_species,
    symbols_from_symbol_counts,
    total_energy,
)

__all__ = [
    "K_BAR_PER_EV_A3",
    "TOTAL_ENERGY_TAG",
    "build_cell",
    "coordinate_parse_note",
    "energy_parse_note",
    "forces",
    "lattice_vectors",
    "parse_notes_for",
    "positions",
    "source_code_parse_note",
    "stress_from_vasp_kbar",
    "stress_parse_note",
    "stress_voigt6_vasp_to_full",
    "symbols_from_species",
    "symbols_from_symbol_counts",
    "total_energy",
]
