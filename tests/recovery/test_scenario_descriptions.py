"""Every registered recovery scenario and every offered choice has a plain-language description.

The CLI (Q1) prints these when a conversion refuses or pauses, and ``xtalate scenarios`` lists
them, so a scenario/choice without text would print an empty line where the user needs to be told
what is being asked. Coupling the catalog to this test means a new scenario (A2, H5MD, a later
format) cannot ship without its explanation.
"""

from __future__ import annotations

import itertools

from xtalate.recovery.scenarios import (
    CHOICE_DESCRIPTIONS,
    SCENARIO_DESCRIPTIONS,
    SCENARIO_HAZARD,
    available_options,
    describe_choice,
    describe_scenario,
)


def _all_choices(scenario: str) -> set[str]:
    # Union the offered list over every flag combination, exactly as backend/vocabulary.py does.
    found: set[str] = set()
    for a, b, c, d in itertools.product([False, True], repeat=4):
        found.update(
            available_options(
                scenario,
                target_can_be_nonperiodic=a,
                target_supports_multifile=b,
                target_field_optional=c,
                permissive_mode=d,
            )
        )
    return found


def test_every_scenario_has_a_description() -> None:
    assert set(SCENARIO_DESCRIPTIONS) == set(SCENARIO_HAZARD)
    assert all(text.strip() for text in SCENARIO_DESCRIPTIONS.values())


def test_every_offerable_choice_has_a_description() -> None:
    missing = [
        (scenario, choice)
        for scenario in SCENARIO_HAZARD
        for choice in sorted(_all_choices(scenario))
        if (scenario, choice) not in CHOICE_DESCRIPTIONS
    ]
    assert missing == []


def test_no_orphan_choice_descriptions() -> None:
    orphans = [
        key
        for key in CHOICE_DESCRIPTIONS
        if key[0] not in SCENARIO_HAZARD or key[1] not in _all_choices(key[0])
    ]
    assert orphans == []


def test_describe_helpers_fall_back_instead_of_raising() -> None:
    assert describe_scenario("not_a_scenario")
    assert describe_choice("not_a_scenario", "nope")
    assert describe_scenario("missing_lattice") == SCENARIO_DESCRIPTIONS["missing_lattice"]
    assert (
        describe_choice("missing_lattice", "bounding_box")
        == CHOICE_DESCRIPTIONS[("missing_lattice", "bounding_box")]
    )
