"""Recovery scenario catalog tests (M5, MASTER_SPEC Part 4 §3.1, §3.3).

Covers the three-way hazard classification and the *computed* option lists — in particular the
honest exclusions the review §4.4 trim requires: ``non_periodic`` is offered only when the target
can express a non-periodic cell (never for POSCAR), and ``upload_reference``/``split_all`` are not
listed at all in v0.1.
"""

from __future__ import annotations

from xtalate.recovery import SCENARIO_HAZARD, HazardClass, available_options


def test_hazard_classes_are_the_three_way_split() -> None:
    assert SCENARIO_HAZARD["frame_selection"] == HazardClass.SELECTIVE_REDUCTIVE
    assert SCENARIO_HAZARD["missing_lattice"] == HazardClass.FABRICATIVE


def test_missing_lattice_options_exclude_non_periodic_for_periodic_only_targets() -> None:
    # POSCAR cannot express pbc=(F,F,F), so non_periodic is honestly not offered (Part 4 §3.3).
    assert available_options("missing_lattice") == ["manual_input", "bounding_box"]


def test_missing_lattice_offers_non_periodic_only_when_target_supports_it() -> None:
    opts = available_options("missing_lattice", target_can_be_nonperiodic=True)
    assert "non_periodic" in opts


def test_frame_selection_options() -> None:
    # split_all (one file per frame) needs a multi-file output mode absent in v0.1 -> not listed.
    assert available_options("frame_selection") == ["first", "last", "index"]


def test_unknown_scenario_has_no_options() -> None:
    assert available_options("missing_velocities") == []
