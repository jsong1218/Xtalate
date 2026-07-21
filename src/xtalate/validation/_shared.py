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


#: Paths whose values are *lengths in ångström*, and whose representational bound is therefore
#: expressed in a unit that depends on the format's coordinate system.
_LENGTH_PATHS = ("atoms.positions", "cell.lattice_vectors")


def require_supported_precision(
    format_id: str, precision: dict[str, int | None], native_coordinate_system: str
) -> dict[str, int | None]:
    """The exporter's ``numeric_precision``, refused if validation cannot honour it correctly.

    ``_representational_bound`` turns a declared decimal count *d* into ``0.5·10⁻ᵈ`` in the field's
    own units. For a Cartesian format those units are ångström and the checks compare ångström, so
    the bound is right. For a **fractional** format the decimals are fractional units, and Part 5
    §4.2's ``× max‖Lᵢ‖`` scaling is what converts them — machinery that does not exist, because no
    Phase 1 exporter declares reduced precision (all write full round-trip precision, so every
    bound is 0.0 and the question never arises).

    That makes this an easy trap to walk into: a future fractional exporter declaring four-decimal
    coordinates would get a tolerance ~|L| times too tight, silently, and its round-trips would
    start failing for a reason nobody would look for in the tolerance model. So the unimplemented
    case refuses instead — a validation engine that cannot judge a field correctly must say so
    rather than judge it wrongly. Implementing the scaling means threading the lattice to the bound
    computation and deleting this guard.
    """
    unsupported = [p for p in _LENGTH_PATHS if precision.get(p) is not None]
    if native_coordinate_system == "fractional" and unsupported:
        raise NotImplementedError(
            f"exporter {format_id!r} is fractional-native and declares numeric_precision for "
            f"{unsupported}, but the Part 5 §4.2 lattice scaling (x max||L_i||) that converts a "
            "fractional decimal count into an angstrom bound is not implemented. Validating it "
            "with the unscaled bound would apply a tolerance roughly |L| times too tight"
        )
    return precision
