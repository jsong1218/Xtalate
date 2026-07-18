"""Root test configuration: the PR-vs-nightly split (M15B; MASTER_SPEC Part 8 §2.4, §5).

The default run is the fast, curated PR gate; the exhaustive round-trip matrix and the extended
property-test budget are opt-in for the nightly workflow (M15C). This keeps a PR under the Part 8 §5
ten-minute cap **without ever dropping a check** — everything the PR skips still runs nightly, so no
coverage of the matrix is lost, only deferred.

Two coordinated switches, one purpose:

* The ``nightly`` marker (registered in ``pyproject.toml``) labels the checks only the nightly job
  runs — today, the full n×n two-hop pairs beyond the curated high-risk set (``test_two_hop``).
  ``XTALATE_FULL_MATRIX=1`` is the single switch that un-gates them; without it,
  :func:`pytest_collection_modifyitems` deselects every ``nightly`` item.
* The hypothesis example budget is a registered profile pair — ``pr`` (default) and ``nightly`` —
  selected by ``HYPOTHESIS_PROFILE``. The PR profile keeps the property suite cheap; the nightly
  profile widens the search. Registered here (not per-test) so the loaded profile is the single
  source of truth for ``max_examples`` — a property test carries no hard-coded budget.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

# --- Hypothesis budget profiles (Part 8 §2.4) --------------------------------------------------
# deadline=None because a full convert + re-parse per example is legitimately slow; too_slow is
# suppressed for the same reason. Only max_examples differs between the two profiles.
settings.register_profile(
    "pr", max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile(
    "nightly", max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "pr"))

# --- Full-matrix gate (Part 8 §2.4) ------------------------------------------------------------
_FULL_MATRIX = os.environ.get("XTALATE_FULL_MATRIX") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect ``nightly``-marked items unless ``XTALATE_FULL_MATRIX=1`` un-gates them.

    Deselection (not skip) keeps the PR summary clean — the nightly-only pairs are simply not part
    of the run rather than showing as skips — while the nightly workflow sets the env var to run the
    exhaustive set. No item is ever removed from the suite; the gate only chooses which run executes
    it."""
    if _FULL_MATRIX:
        return
    remaining: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        (deselected if item.get_closest_marker("nightly") else remaining).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
