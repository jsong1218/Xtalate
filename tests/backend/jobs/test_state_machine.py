"""The transition-table test — every legal *and* illegal edge (M22 done-means).

The state machine is the single source of truth for job lifecycle moves, so it earns an exhaustive
test: for every ordered pair of states, the module must agree exactly with the Part 6 §3.2 diagram
on whether the edge is legal. This is the test the plan's done-means names by that phrase.
"""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from backend.jobs import state_machine as sm  # noqa: E402

# The edges of the Part 6 §3.2 state diagram, transcribed independently of the module's own table so
# a typo in the source table is caught rather than mirrored.
_LEGAL_EDGES = {
    ("queued", "running"),
    ("queued", "failed"),
    ("queued", "cancelled"),
    ("running", "awaiting_recovery"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "cancelled"),
    ("awaiting_recovery", "running"),
    ("awaiting_recovery", "expired"),
    ("awaiting_recovery", "cancelled"),
}


def test_every_ordered_pair_matches_the_diagram() -> None:
    for source, target in itertools.product(sm.STATES, repeat=2):
        expected = (source, target) in _LEGAL_EDGES
        assert sm.is_legal(source, target) is expected, (source, target)


def test_assert_transition_raises_on_exactly_the_illegal_edges() -> None:
    for source, target in itertools.product(sm.STATES, repeat=2):
        if (source, target) in _LEGAL_EDGES:
            sm.assert_transition(source, target)  # must not raise
        else:
            with pytest.raises(sm.InvalidTransition):
                sm.assert_transition(source, target)


def test_terminal_states_have_no_outgoing_edges() -> None:
    for state in sm.TERMINAL_STATES:
        assert sm.is_terminal(state)
        assert sm.LEGAL_TRANSITIONS[state] == frozenset()
        for target in sm.STATES:
            assert not sm.is_legal(state, target)


def test_non_terminal_states_are_not_terminal() -> None:
    for state in sm.STATES - sm.TERMINAL_STATES:
        assert not sm.is_terminal(state)
        assert sm.LEGAL_TRANSITIONS[state] != frozenset()


def test_unknown_states_are_always_illegal() -> None:
    with pytest.raises(sm.InvalidTransition):
        sm.assert_transition("queued", "not_a_state")
    with pytest.raises(sm.InvalidTransition):
        sm.assert_transition("not_a_state", "running")
    assert not sm.is_legal("not_a_state", "running")


def test_states_match_the_orm_vocabulary() -> None:
    from backend.db.models import JOB_STATES

    assert sm.STATES == frozenset(JOB_STATES)
