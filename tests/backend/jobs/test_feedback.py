"""The recovery feedback aggregation (Part 5 §7; M25) — read-only, metadata-only.

Seeds convert jobs whose requests carry recovery choices, plus their conversions' validation
outcomes, and asserts the ``(scenario, choice, parameters) → validation status`` grouping. Proves
the bright line by construction where it can: the aggregation reads only the request choices and the
denormalized validation status, never a report body — and it returns data, it never writes.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.db import Repository
from backend.db.models import Conversion, Job
from backend.jobs.feedback import UNVALIDATED, aggregate_recovery_feedback


def _seed_convert(
    repository: Repository,
    *,
    recovery_choices: dict[str, dict[str, Any]],
    validation_status: str | None,
) -> None:
    """Persist a convert job (with its recovery choices) and its conversion's validation outcome."""
    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(
            job_id=job_id,
            kind="convert",
            state="completed",
            request={"options": {"recovery_choices": recovery_choices}},
        )
    )
    repository.add_conversion(
        Conversion(
            conversion_id=f"cnv-{uuid.uuid4().hex}",
            job_id=job_id,
            target_format="poscar",
            conversion_status="completed",
            validation_status=validation_status,
        )
    )


def test_empty_store_yields_no_feedback(repository: Repository) -> None:
    assert aggregate_recovery_feedback(repository) == []


def test_groups_by_scenario_choice_parameters_and_counts_outcomes(
    repository: Repository,
) -> None:
    # Three converts that chose bounding_box for missing_lattice: two passed, one failed.
    for status in ("passed", "passed", "failed"):
        _seed_convert(
            repository,
            recovery_choices={"missing_lattice": {"choice": "bounding_box"}},
            validation_status=status,
        )
    # One that chose the same scenario but a different choice (manual_input with parameters).
    _seed_convert(
        repository,
        recovery_choices={"missing_lattice": {"choice": "manual_input", "parameters": {"a": 5.6}}},
        validation_status="passed",
    )

    entries = aggregate_recovery_feedback(repository)
    assert len(entries) == 2
    # Most-made decision first: bounding_box (3) before manual_input (1).
    top = entries[0]
    assert (top.scenario, top.choice) == ("missing_lattice", "bounding_box")
    assert top.total == 3
    assert top.outcomes == {"passed": 2, "failed": 1}

    second = entries[1]
    assert second.choice == "manual_input"
    assert second.parameters == {"a": 5.6}
    assert second.outcomes == {"passed": 1}


def test_same_choice_different_parameters_are_distinct_groups(repository: Repository) -> None:
    _seed_convert(
        repository,
        recovery_choices={"missing_lattice": {"choice": "manual_input", "parameters": {"a": 5.0}}},
        validation_status="passed",
    )
    _seed_convert(
        repository,
        recovery_choices={"missing_lattice": {"choice": "manual_input", "parameters": {"a": 6.0}}},
        validation_status="failed",
    )
    entries = aggregate_recovery_feedback(repository)
    assert len(entries) == 2
    assert {frozenset(e.parameters.items()) for e in entries} == {
        frozenset({("a", 5.0)}),
        frozenset({("a", 6.0)}),
    }


def test_missing_validation_status_lands_in_the_unvalidated_bucket(
    repository: Repository,
) -> None:
    _seed_convert(
        repository,
        recovery_choices={"frame_selection": {"choice": "last"}},
        validation_status=None,
    )
    (entry,) = aggregate_recovery_feedback(repository)
    assert entry.outcomes == {UNVALIDATED: 1}
    assert entry.total == 1


def test_converts_without_recovery_choices_contribute_nothing(repository: Repository) -> None:
    _seed_convert(repository, recovery_choices={}, validation_status="passed")
    assert aggregate_recovery_feedback(repository) == []
