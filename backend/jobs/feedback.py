"""The recovery feedback loop: ``(scenario, choice, parameters) → validation status`` (Part 5 §7).

Now that reports and their outcomes persist in the relational store (from M22), the v0.2-era
feedback-loop item on the Part 10 roadmap becomes possible: aggregate, across all conversions, how
each recovery decision a caller made correlated with whether the resulting conversion **validated**.
That signal is what a future advisory surface would use to tell a user "callers who chose
``bounding_box`` here mostly validated" — but this module is **logging/aggregation only**:

* **It changes nothing.** No default is ever adjusted because of these statistics — the bright line
  that recovery is explicit and never inferred (P4) is untouchable by construction, because this is
  a read-only query with no write path back into the engine.
* **Surfacing is deferred.** Rendering this to a user is UI work (v0.6+); v0.5 ships the query and
  its meaning, documented and tested, so the data is trustworthy when a surface is built on it.
* **Metadata only, never file contents.** The only inputs are the recovery *choices* a caller made
  (scenario, choice, and the choice's parameters — e.g. ``bounding_box`` vs a manual lattice) and
  the conversion's pass/fail validation status. No atom coordinate, no filename's contents, no
  report body is read (:meth:`Repository.convert_recovery_outcomes` selects only those two columns).

**Realized as a Python aggregation, not a SQL view.** The recovery choices live inside a JSON
``request`` column, and the one query that would express this as a database view would need JSON
functions that differ between SQLite (Tier 0) and PostgreSQL (Tier 1) — breaking the backend parity
the whole persistence layer is built to preserve (the parity suite). Grouping in Python over the two
plain columns the repository already returns keeps the aggregation identical on both tiers; the cost
is trivial at the scale a feedback digest runs (a periodic/offline job, not a per-request path).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.db import Repository

#: Bucket for a conversion whose validation status is absent — a refused conversion, or one whose
#: outcome was never recorded. Kept as an explicit bucket rather than dropped, so a reader can see
#: how many decisions have no validation signal at all (no silent loss, even in a statistic).
UNVALIDATED = "unvalidated"


class RecoveryFeedbackEntry(BaseModel):
    """One ``(scenario, choice, parameters)`` group and how its conversions validated.

    ``outcomes`` maps a validation status (e.g. ``"passed"``/``"failed"``, or :data:`UNVALIDATED`)
    to the number of conversions that made this exact decision and reached that outcome. ``total``
    is their sum — the number of times this decision was made.
    """

    scenario: str
    choice: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    outcomes: dict[str, int] = Field(default_factory=dict)
    total: int = 0


def _canonical_parameters(parameters: Any) -> str:
    """A stable grouping key for a choice's parameters (order-independent JSON, or ``{}``)."""
    if not isinstance(parameters, dict):
        return "{}"
    return json.dumps(parameters, sort_keys=True)


def aggregate_recovery_feedback(repository: Repository) -> list[RecoveryFeedbackEntry]:
    """Aggregate recovery decisions against validation outcomes across every convert (Part 5 §7).

    Groups on ``(scenario, choice, parameters)`` and counts the validation statuses within each
    group. Deterministically ordered — most-made decision first, then by scenario/choice — so a
    digest is stable across runs. Returns an empty list when nothing has been converted yet.
    """
    # (scenario, choice, canonical-parameters) -> (parameters, {status: count})
    buckets: dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, int]]] = {}
    for request, validation_status in repository.convert_recovery_outcomes():
        options = request.get("options") if isinstance(request, dict) else None
        choices = options.get("recovery_choices") if isinstance(options, dict) else None
        if not isinstance(choices, dict):
            continue
        status = validation_status or UNVALIDATED
        for scenario, decision in choices.items():
            if not isinstance(decision, dict):
                continue
            choice = decision.get("choice")
            if not isinstance(choice, str):
                continue
            parameters = decision.get("parameters") or {}
            key = (scenario, choice, _canonical_parameters(parameters))
            params, counts = buckets.setdefault(
                key, (parameters if isinstance(parameters, dict) else {}, {})
            )
            counts[status] = counts.get(status, 0) + 1

    entries = [
        RecoveryFeedbackEntry(
            scenario=scenario,
            choice=choice,
            parameters=params,
            outcomes=dict(counts),
            total=sum(counts.values()),
        )
        for (scenario, choice, _params_key), (params, counts) in buckets.items()
    ]
    entries.sort(key=lambda e: (-e.total, e.scenario, e.choice))
    return entries
