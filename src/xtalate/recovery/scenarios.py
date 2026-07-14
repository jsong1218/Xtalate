"""Recovery scenario catalog: hazard classes and per-scenario option computation (Part 4 §3).

Every conversion hazard the pre-flight diff detects (Part 3 §4.3) falls into exactly one of
three hazard classes (Part 4 §3.1), and the class governs what the Recovery Engine may do:

* **bulk reductive** — information the target cannot carry is dropped wholesale; no scientific
  choice selects *which* survives. Never a recovery scenario: it is reported as ``removed`` and
  (in permissive mode) proceeds without a choice.
* **selective reductive** — data is dropped but *which subset is kept changes the scientific
  meaning*; Xtalate will not choose unrecorded. Requires an explicit choice, records an
  ``Assumption``, produces **no** ``supplied`` entry (the kept data is genuine source data).
* **fabricative** — information required/offered by the target does not exist in the source; it
  must be *created*. Requires an explicit choice, records an ``Assumption`` **and** a ``supplied``
  entry. Never automatic in any mode (**P4**).

The bright line is deliberately discrete (a three-value enum, not a risk scale) so no mode or
future convenience can make Xtalate invent scientific data or silently choose which real data
to discard (Part 4 §3.1, "Alternative rejected: a single risk-level scale").

**v0.2 scope (M7 — scenario catalog completion).** The full Part 4 §3.3 catalog of eight scenarios
is registered and hazard-classified here, so classification and the honest-option-list rule are
complete. Which *choices resolve* depends on whether a trigger exists for the four v0.1 formats and
on the milestone:

* ``missing_lattice`` (fabricative) resolves with ``manual_input``/``bounding_box`` (Slice 1) and
  ``upload_reference`` (Slice 2 — lattice read from a second structure, atom-count-checked).
* ``frame_selection`` (selective reductive) resolves with ``first``/``last``/``index`` (Slice 1) and
  ``split_all`` (Slice 2 — one output file per frame; offered when ``target_supports_multifile``).
* ``constraint_representation`` (selective reductive) resolves in Slice 1: ``project``/``drop_all``.
* ``missing_species`` (fabricative) and ``truncate_corrupt_tail`` (selective reductive) are
  *parse-time* scenarios (they fire when a parser raises a recoverable ``ParseError``, not from the
  pre-flight diff). Their resolvers are the Slice-2 parse-time-recovery mechanism, applied by the
  parser's ``parse_recover`` hook rather than by ``RecoveryEngine.resolve``; the offered lists
  (``species_map``/``upload_reference``; ``truncate``/``abort``) are computed here so the refusal
  path can show them.
* ``non_periodic`` (for ``missing_lattice``) is ✳-conditional: offered only when
  ``target_can_be_nonperiodic`` (extXYZ yes; never POSCAR).
* ``missing_velocities``/``missing_masses`` register with their classification and refuse until M8;
  their fabricative choices land there (their only four-format trigger, the POSCAR velocity block).
* ``missing_energy`` is deliberately **optionless** in v0.1's formats (no target requires per-frame
  energy, so no ``upload_reference`` trigger arises) — there is no scientifically defensible
  synthetic energy, so it always refuses without a preset.

Option lists are **computed**, not static (Part 4 §3.3): a choice not scientifically coherent for
the concrete source/target pair, or not implemented in this version, is honestly absent from the
offered list rather than offered and then refused. The offered list is carried on each detected
``UnresolvedScenario`` (computed at detection time, when the pair is known) so the engine validates
choices against, and the refusal report echoes, exactly the same list (**P5**).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass
class UnresolvedScenario:
    """A recovery the pre-flight diff detected but has not resolved (Part 4 §3).

    Emitted by ``conversion.preflight`` (conversion → recovery is a legal downward import) and
    consumed by ``RecoveryEngine.resolve``; it lives here, in the recovery layer, so both sides
    share one descriptor. ``path`` is the canonical field a *fabricative* scenario would supply
    (``None`` for a selective-reductive one like ``frame_selection``).

    ``options`` is the honest, *pair-specific* list of ``choice`` codes offered for this concrete
    source/target (Part 4 §3.3) — computed at detection time and carried here so the engine
    validates against, and the refusal report shows, one list (no drift). ``params`` carries
    scenario-specific detection context the resolver needs (e.g. ``representable_kinds`` for
    ``constraint_representation``)."""

    scenario: str  # e.g. "missing_lattice" | "frame_selection" | "constraint_representation".
    path: str | None = None
    detail: str | None = None
    options: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


class HazardClass(StrEnum):
    """The three-way classification of Part 4 §3.1. Discrete by design."""

    BULK_REDUCTIVE = "bulk_reductive"
    SELECTIVE_REDUCTIVE = "selective_reductive"
    FABRICATIVE = "fabricative"


# The full Part 4 §3.3 catalog with its hazard class (Part 4 §3.1). Every scenario the engine can
# see is registered here; a scenario absent from this map is one the Recovery Engine does not know
# and refuses (Part 4 §3.2). Classification is complete in M7 even where a *resolver* lands later
# (M8 for the velocity family; v0.2 Slice 2 for the parse-time scenarios).
SCENARIO_HAZARD: dict[str, HazardClass] = {
    "missing_lattice": HazardClass.FABRICATIVE,
    "missing_species": HazardClass.FABRICATIVE,
    "missing_velocities": HazardClass.FABRICATIVE,
    "missing_masses": HazardClass.FABRICATIVE,
    "missing_energy": HazardClass.FABRICATIVE,
    "frame_selection": HazardClass.SELECTIVE_REDUCTIVE,
    "truncate_corrupt_tail": HazardClass.SELECTIVE_REDUCTIVE,
    "constraint_representation": HazardClass.SELECTIVE_REDUCTIVE,
}


def available_options(
    scenario: str,
    *,
    target_can_be_nonperiodic: bool = False,
    target_supports_multifile: bool = False,
    target_field_optional: bool = False,
    permissive_mode: bool = False,
) -> list[str]:
    """The *computed* option list for ``scenario`` (Part 4 §3.3), honestly excluding choices not
    offered for this pair or not implemented in this version.

    ``missing_lattice``: ``manual_input`` (user supplies a 3×3 lattice) and ``bounding_box``
    (axis-aligned box of the selected frame's positions + ``padding_ang``). ``non_periodic`` is
    offered only when ``target_can_be_nonperiodic`` — i.e. the target can express ``pbc=(F,F,F)``
    (extXYZ yes; never POSCAR, whose cell is fully periodic, Part 3 §4.2). ``upload_reference``
    (lattice from a second file) is the v0.2 Slice-2 second-file mechanism, so it is not listed yet.

    ``frame_selection``: ``first`` / ``last`` / ``index``. ``split_all`` (one file per frame) needs
    a multi-file output mode absent from the v0.1 library API (the M7 cut line), so it is offered
    only when ``target_supports_multifile`` — which no v0.1 format sets.

    ``constraint_representation``: ``project`` (map to the target's representable subset, remainder
    to ``removed``) / ``drop_all``.

    ``missing_velocities`` (M8): ``zero_init`` / ``maxwell_boltzmann`` / ``upload_reference``, plus
    ✳``omit`` only when ``target_field_optional and permissive_mode`` (the catalog footnote — the
    resolver applies ``omit`` under exactly those conditions, so honesty requires offering it only
    then). ``missing_masses`` (M8): ``standard_masses`` / ``manual_input``.

    Every other registered scenario returns ``[]`` in this version: ``missing_energy`` (deliberately
    optionless — no synthetic energy exists), and the parse-time ``missing_species`` /
    ``truncate_corrupt_tail`` (Slice-2 resolver, applied via ``parse_recover``). ``[]`` means "no
    preset can resolve this here" — the scenario refuses.
    """
    if scenario == "missing_lattice":
        # `upload_reference` (lattice taken from a second structure, atom-count-checked) lands in
        # Slice 2, so it now joins the offered list. Order matches Part 4 §3.3.
        options = ["manual_input", "upload_reference", "bounding_box"]
        if target_can_be_nonperiodic:
            options.append("non_periodic")
        return options
    if scenario == "frame_selection":
        options = ["first", "last", "index"]
        if target_supports_multifile:
            options.append("split_all")
        return options
    if scenario == "constraint_representation":
        return ["project", "drop_all"]
    if scenario == "missing_velocities":
        # M8: a target that can hold velocities but has none on the source (opt-in emission).
        # `omit` (leave velocities absent) is offered only when the target field is optional *and*
        # the mode is permissive — the catalog's own ✳ footnote (Part 4 §3.3); in strict mode, or
        # for a field the target requires, it is absent so naming it refuses.
        options = ["zero_init", "maxwell_boltzmann", "upload_reference"]
        if target_field_optional and permissive_mode:
            options.append("omit")
        return options
    if scenario == "missing_masses":
        # M8: IUPAC standard atomic weights (a reported default) or a caller-supplied list.
        return ["standard_masses", "manual_input"]
    if scenario == "missing_species":
        # Parse-time scenario, resolved in Slice 2: an ordered symbol / type→element map, or the
        # symbols read from a matching reference structure (Part 4 §3.3).
        return ["species_map", "upload_reference"]
    if scenario == "truncate_corrupt_tail":
        # Parse-time scenario, resolved in Slice 2: keep frames 0…k and discard the corrupt tail,
        # or abort (Part 4 §3.3).
        return ["truncate", "abort"]
    return []
