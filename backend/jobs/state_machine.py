"""The job state machine — the one place the legal transitions live (MASTER_SPEC Part 6 §3.2).

The async job model's states and edges (`06 §3.2`, the state diagram) are encoded here as **data**,
not as conditionals scattered across handlers and the worker. Every state write in the service goes
through :func:`assert_transition` (via :meth:`Repository.transition_job`), so an illegal edge — a
``completed`` job dragged back to ``running``, a ``queued`` job jumped straight to ``completed`` —
is a loud :class:`InvalidTransition`, never a silently corrupted row. The done-means' "transition-
table test covering every legal and illegal edge" tests *this* module directly.

M22 drives only the pre-recovery subset (``queued→running``, ``queued→failed``,
``running→completed|failed``); the ``awaiting_recovery`` and ``cancelled`` edges belong to M23. But
the whole table lives here from the start, because the table is the contract the later milestones
attach to — they add *callers*, never new edges the module did not already know were legal (**P6**).
"""

from __future__ import annotations

#: Every job state (Part 6 §3.2). Mirrors ``backend.db.models.JOB_STATES`` — the ORM stores the
#: string, this module governs the moves between them. Kept in sync by :func:`_assert_states_match`.
STATES: frozenset[str] = frozenset(
    {
        "queued",
        "running",
        "awaiting_recovery",
        "completed",
        "failed",
        "cancelled",
        "expired",
    }
)

#: The terminal states: a job that reaches one never transitions again (the ``409
#: JOB_ALREADY_TERMINAL`` wall M23's cancel endpoint enforces sits on this set).
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled", "expired"})

#: The legal transition table, exactly the edges of the Part 6 §3.2 state diagram. A transition is
#: legal iff its target is in ``LEGAL_TRANSITIONS[source]``. Terminal states map to the empty set.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"awaiting_recovery", "completed", "failed", "cancelled"}),
    "awaiting_recovery": frozenset({"running", "expired", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}


class InvalidTransition(Exception):
    """A state change the table forbids. Raised by :func:`assert_transition`.

    A programming error, not a client error: the API and worker only ever *attempt* legal edges, so
    this firing means a bug moved a job wrongly — it must surface loudly (a 500 via the unhandled-
    exception envelope), never be swallowed into a corrupt persisted state.
    """

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target
        super().__init__(f"illegal job transition {source!r} → {target!r}")


def is_terminal(state: str) -> bool:
    """Whether ``state`` is terminal (no further transition is legal from it)."""
    return state in TERMINAL_STATES


def is_legal(source: str, target: str) -> bool:
    """Whether ``source → target`` is a transition the table permits."""
    return target in LEGAL_TRANSITIONS.get(source, frozenset())


def assert_transition(source: str, target: str) -> None:
    """Raise :class:`InvalidTransition` unless ``source → target`` is legal (else return ``None``).

    Rejects unknown states too: a ``source``/``target`` outside :data:`STATES` can never be legal,
    so a typo'd state string fails here rather than persisting an off-vocabulary row.
    """
    if source not in STATES or target not in STATES or not is_legal(source, target):
        raise InvalidTransition(source, target)
