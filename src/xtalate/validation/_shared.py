"""Status-precedence and numeric-field tables shared across the validation package.

Both the Validation Engine (which *measures* a conversion) and the re-thresholder (which *re-judges*
already-stored measurements under a new profile) need the same aggregate-status precedence and the
same ``numeric_field_fidelity`` catalog. Defining them **once** here removes the drift hazard of two
hand-synchronised copies — a field added to the fidelity check in one module but not the other would
otherwise silently mis-threshold on offline re-threshold. ``NUMERIC_QUANTITY`` is *derived* from
``NUMERIC_FIELDS`` for the same reason: one catalog, two views.
"""

from __future__ import annotations

# Aggregate-status precedence: the worst individual check wins (Part 5 §3). `skipped` does not
# worsen the aggregate (a legitimately-inapplicable check is not a defect).
RANK = {"pass": 0, "skipped": 0, "warn": 1, "fail": 2}
AGGREGATE = {0: "passed", 1: "passed_with_warnings", 2: "failed"}

# The `numeric_field_fidelity` catalog (Part 5 §2): canonical path -> (quantity, kind). `per_atom`
# fields are reordered by the exporter's permutation map before comparison; `scalar`/`array` fields
# are not. `atoms.masses` and `frame.time` round out the eight fields the check names.
NUMERIC_FIELDS: list[tuple[str, str, str]] = [
    ("dynamics.velocities", "velocities", "per_atom"),
    ("dynamics.forces", "forces", "per_atom"),
    ("electronic.total_energy", "energy", "scalar"),
    ("electronic.stress", "stress", "array"),
    ("electronic.charges", "charges", "per_atom"),
    ("electronic.magnetic_moments", "magnetic_moments", "per_atom"),
    ("atoms.masses", "masses", "per_atom"),
    ("frame.time", "time", "scalar"),
]

# Canonical path -> tolerance quantity, derived from the single catalog above. The re-thresholder
# needs only this view (it judges stored per-path measurements, not their `per_atom`/`scalar` kind).
NUMERIC_QUANTITY: dict[str, str] = {path: quantity for path, quantity, _kind in NUMERIC_FIELDS}
