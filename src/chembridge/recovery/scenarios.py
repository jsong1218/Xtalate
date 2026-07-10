"""Recovery scenario catalog: hazard classes and per-scenario option computation (Part 4 §3).

Every conversion hazard the pre-flight diff detects (Part 3 §4.3) falls into exactly one of
three hazard classes (Part 4 §3.1), and the class governs what the Recovery Engine may do:

* **bulk reductive** — information the target cannot carry is dropped wholesale; no scientific
  choice selects *which* survives. Never a recovery scenario: it is reported as ``removed`` and
  (in permissive mode) proceeds without a choice.
* **selective reductive** — data is dropped but *which subset is kept changes the scientific
  meaning*; ChemBridge will not choose unrecorded. Requires an explicit choice, records an
  ``Assumption``, produces **no** ``supplied`` entry (the kept data is genuine source data).
* **fabricative** — information required/offered by the target does not exist in the source; it
  must be *created*. Requires an explicit choice, records an ``Assumption`` **and** a ``supplied``
  entry. Never automatic in any mode (**P4**).

The bright line is deliberately discrete (a three-value enum, not a risk scale) so no mode or
future convenience can make ChemBridge invent scientific data or silently choose which real data
to discard (Part 4 §3.1, "Alternative rejected: a single risk-level scale").

**v0.1 scope (review §4.4 trim).** Two scenarios resolve: ``missing_lattice`` (fabricative) and
``frame_selection`` (selective reductive), preset-only. Option lists are **computed**, not static
(Part 4 §3.3): a choice that is not scientifically coherent for the concrete source/target pair,
or not implemented in v0.1, is honestly absent from ``available_options`` rather than offered and
then refused. ``missing_species``/``missing_velocities``/``missing_masses``/``missing_energy``/
``truncate_corrupt_tail``/``constraint_representation`` are catalogued in the spec but not
triggered by any v0.1 (source, target) pair; they attach at this same seam later (**P6**).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass
class UnresolvedScenario:
    """A recovery the pre-flight diff detected but has not resolved (Part 4 §3).

    Emitted by ``conversion.preflight`` (conversion → recovery is a legal downward import) and
    consumed by ``RecoveryEngine.resolve``; it lives here, in the recovery layer, so both sides
    share one descriptor. ``path`` is the canonical field a *fabricative* scenario would supply
    (``None`` for a selective-reductive one like ``frame_selection``)."""

    scenario: str  # e.g. "missing_lattice" | "frame_selection".
    path: str | None = None
    detail: str | None = None


class HazardClass(StrEnum):
    """The three-way classification of Part 4 §3.1. Discrete by design."""

    BULK_REDUCTIVE = "bulk_reductive"
    SELECTIVE_REDUCTIVE = "selective_reductive"
    FABRICATIVE = "fabricative"


# The v0.1 resolvable scenarios and their hazard class. A scenario absent here is not one the
# Recovery Engine resolves in v0.1 (it either does not arise for the implemented formats, or is a
# bulk-reductive drop handled by the mode table, not by a choice).
SCENARIO_HAZARD: dict[str, HazardClass] = {
    "frame_selection": HazardClass.SELECTIVE_REDUCTIVE,
    "missing_lattice": HazardClass.FABRICATIVE,
}


def available_options(scenario: str, *, target_can_be_nonperiodic: bool = False) -> list[str]:
    """The *computed* option list for ``scenario`` (Part 4 §3.3), honestly excluding choices not
    offered for this pair or not implemented in v0.1.

    ``missing_lattice``: ``manual_input`` (user supplies a 3×3 lattice) and ``bounding_box``
    (axis-aligned box of the selected frame's positions + ``padding_ang``). ``non_periodic`` is
    offered only when the target can express ``pbc=(F,F,F)`` — never for POSCAR, whose ``cell.pbc``
    is PARTIAL/fully-periodic-only (Part 3 §4.2). ``upload_reference`` (lattice from a second file)
    needs a second input stream and is out of v0.1 scope, so it is honestly not listed.

    ``frame_selection``: ``first`` / ``last`` / ``index``. ``split_all`` (one file per frame)
    needs a multi-file output mode absent from the v0.1 library API, so it is not listed.
    """
    if scenario == "missing_lattice":
        options = ["manual_input", "bounding_box"]
        if target_can_be_nonperiodic:
            options.append("non_periodic")
        return options
    if scenario == "frame_selection":
        return ["first", "last", "index"]
    return []
