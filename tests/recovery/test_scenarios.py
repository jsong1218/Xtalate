"""Recovery scenario catalog tests (MASTER_SPEC Part 4 §3.1, §3.3).

Covers the three-way hazard classification of the *full* catalog (M7 — eight scenarios) and the
*computed* option lists — in particular the honest exclusions the catalog requires: ``non_periodic``
only when the target can express an open cell (never for POSCAR); ``split_all`` only when the target
supports multi-file output (no v0.1 format does); and the deliberately empty lists for the scenarios
whose choices land later (M8 velocity family, Slice-2 parse-time scenarios) or never
(``missing_energy`` — no synthetic energy exists).
"""

from __future__ import annotations

import pytest

from xtalate.recovery import SCENARIO_HAZARD, HazardClass, available_options

# The full Part 4 §3.3 catalog and its §3.1 hazard class.
_EXPECTED_CLASSES = {
    "missing_lattice": HazardClass.FABRICATIVE,
    "missing_species": HazardClass.FABRICATIVE,
    "missing_velocities": HazardClass.FABRICATIVE,
    "missing_masses": HazardClass.FABRICATIVE,
    "missing_energy": HazardClass.FABRICATIVE,
    "frame_selection": HazardClass.SELECTIVE_REDUCTIVE,
    "truncate_corrupt_tail": HazardClass.SELECTIVE_REDUCTIVE,
    "constraint_representation": HazardClass.SELECTIVE_REDUCTIVE,
}


def test_catalog_is_complete_and_classified() -> None:
    # Every §3.3 scenario is registered with exactly its §3.1 class — no more, no fewer.
    assert SCENARIO_HAZARD == _EXPECTED_CLASSES


@pytest.mark.parametrize(("scenario", "hazard"), list(_EXPECTED_CLASSES.items()))
def test_each_scenario_has_its_hazard_class(scenario: str, hazard: HazardClass) -> None:
    assert SCENARIO_HAZARD[scenario] == hazard


# --- missing_lattice: non_periodic is ✳-conditional (Part 4 §3.3) --------------------------------


def test_missing_lattice_excludes_non_periodic_for_periodic_only_targets() -> None:
    # POSCAR cannot express pbc=(F,F,F), so non_periodic is honestly not offered.
    assert available_options("missing_lattice") == ["manual_input", "bounding_box"]


def test_missing_lattice_offers_non_periodic_only_when_target_supports_it() -> None:
    opts = available_options("missing_lattice", target_can_be_nonperiodic=True)
    assert opts == ["manual_input", "bounding_box", "non_periodic"]


# --- frame_selection: split_all is ✳-conditional (needs multi-file output) -----------------------


def test_frame_selection_excludes_split_all_without_multifile_output() -> None:
    assert available_options("frame_selection") == ["first", "last", "index"]


def test_frame_selection_offers_split_all_only_with_multifile_output() -> None:
    opts = available_options("frame_selection", target_supports_multifile=True)
    assert opts == ["first", "last", "index", "split_all"]


# --- constraint_representation ------------------------------------------------------------------


def test_constraint_representation_options() -> None:
    assert available_options("constraint_representation") == ["project", "drop_all"]


# --- scenarios that refuse in this version (empty offered list) ----------------------------------


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_velocities",  # choices land in M8
        "missing_masses",  # choices land in M8
        "missing_energy",  # deliberately optionless — no synthetic energy exists (Part 4 §3.3)
        "missing_species",  # parse-time resolver — v0.2 Slice 2
        "truncate_corrupt_tail",  # parse-time resolver — v0.2 Slice 2
    ],
)
def test_scenario_offers_no_options_in_this_version(scenario: str) -> None:
    # An empty offered list means "no preset can resolve this here" — the scenario refuses,
    # honestly, rather than offering a choice the version cannot honor.
    assert available_options(scenario) == []


def test_unknown_scenario_has_no_options() -> None:
    assert available_options("not_a_scenario") == []
