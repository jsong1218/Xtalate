"""Numerical tolerance strategy for validation (MASTER_SPEC Part 5 §4).

The problem (§4.1): formats disagree about decimal precision, so a fixed universal tolerance
either false-fails legitimate low-precision conversions (CIF's 4-decimal fractional coordinates)
or waves through genuine corruption in high-precision formats. The solution (§4.2): a per-quantity
**base** tolerance, floored up by the field's declared **representational bound**:

    effective_warn(field) = max( base_warn(field),  k_warn × representational_bound(field) )
    effective_fail(field) = max( base_fail(field),  k_fail × representational_bound(field) )

with ``k_warn = 2``, ``k_fail = 10`` (headroom over the theoretical bound). Both the base and the
effective values in force are recorded in the Validation Report's ``tolerance_applied`` so a reader
can always see *why* a deviation passed (§4.2).

**v0.1 profiles are named-only** (``default`` / ``strict`` / ``loose``, review §4.4): ``strict``
tightens the bases 100×, ``loose`` relaxes them 100×. Two rules are never configurable (§4.4):
discrete quantities (counts, species, ``pbc``, presence) stay exact, and the representational-bound
floor cannot be disabled — a profile stricter than the format's precision simply *fails* the
representational error, and the report says so. Custom tables are the v0.2 seam (**P6**).

Layering: ``validation`` sits above ``sdk``/``schema`` and below nothing it imports here; this
module depends only on the stdlib, so the tolerance policy is independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass

# Headroom multipliers over the theoretical representational bound (Part 5 §4.2).
K_WARN = 2
K_FAIL = 10


@dataclass(frozen=True)
class Bounds:
    """A (warn, fail) threshold pair for one quantity, in that quantity's canonical unit."""

    warn: float
    fail: float


# Per-quantity base tolerances (Part 5 §4.3, "default" profile). Keys are the *quantity* names the
# check catalog groups canonical fields under — positions/lattice from `positions_rmsd`/
# `lattice_consistency`, the rest from `numeric_field_fidelity` (§2). `masses` is not in the §4.3
# table (no v0.1 conversion writes it through validation), so it is given the forces/velocities
# base as the nearest-precision analogue and recorded as DECISIONS.md D25 — never `atom_count`/
# species/absence, which stay exact regardless (§4.4).
_BASES: dict[str, Bounds] = {
    "positions": Bounds(1e-5, 1e-3),
    "lattice": Bounds(1e-5, 1e-3),
    "velocities": Bounds(1e-6, 1e-4),
    "forces": Bounds(1e-6, 1e-4),
    "energy": Bounds(1e-6, 1e-4),
    "stress": Bounds(1e-8, 1e-6),
    "charges": Bounds(1e-4, 1e-2),
    "magnetic_moments": Bounds(1e-4, 1e-2),
    "masses": Bounds(1e-6, 1e-4),
    "time": Bounds(1e-6, 1e-3),
}

# The named profiles (§4.4): a uniform scale on every base. `default` is 1×; `strict` tightens 100×
# (round-trip regression hunting); `loose` relaxes 100× (knowingly low-precision workflows).
_SCALES: dict[str, float] = {"default": 1.0, "strict": 0.01, "loose": 100.0}


class ToleranceProfile:
    """A named tolerance profile: per-quantity bases plus the representational-bound formula (§4).

    Construct via :meth:`named`; instances are immutable in effect (the base map is not mutated).
    :meth:`effective` applies the §4.2 formula for one quantity given that field's representational
    bound (0.0 for a full-precision field, e.g. every v0.1 exporter — see ``numeric_precision``)."""

    def __init__(self, name: str, bases: dict[str, Bounds]) -> None:
        self.name = name
        self._bases = bases

    @classmethod
    def named(cls, name: str) -> ToleranceProfile:
        """The profile called ``name`` (``default``/``strict``/``loose``). Unknown names raise —
        a typo is a caller error, not a silent fallback to default (which would validate under a bar
        the caller did not ask for). Custom tables come from :meth:`from_mapping` (Part 5 §4.4)."""
        try:
            scale = _SCALES[name]
        except KeyError:
            raise ValueError(
                f"unknown tolerance profile {name!r}; named profiles are {sorted(_SCALES)!r} "
                "(or pass a custom tolerance-table file)"
            ) from None
        bases = {q: Bounds(b.warn * scale, b.fail * scale) for q, b in _BASES.items()}
        return cls(name, bases)

    @classmethod
    def from_mapping(cls, name: str, mapping: dict[str, object]) -> ToleranceProfile:
        """A custom profile from a parsed tolerance-table mapping (Part 5 §4.4, the v0.2 seam).

        The mapping is the deserialized custom table (from a YAML/JSON file; the file I/O and format
        parsing belong to the caller — the CLI — so this stays a pure, independently-testable
        validator). Shape::

            name: my-tight-forces          # optional; overrides the passed-in ``name``
            quantities:
              positions: { warn: 1.0e-6, fail: 1.0e-4 }
              forces:    { warn: 1.0e-8, fail: 1.0e-6 }
              # any omitted quantity inherits the ``default`` base

        Only the §4.3 per-quantity bases are configurable. The two §4.4 rules that are *never*
        configurable are enforced by rejection, not silent acceptance: the ``k_warn``/``k_fail``
        multipliers and the representational-bound floor are fixed, and discrete checks (counts,
        species, ``pbc``, presence) admit no tolerance — a table naming any of those, or an unknown
        quantity, raises with an actionable message rather than being ignored.
        """
        if not isinstance(mapping, dict):
            raise ValueError(
                "tolerance table must be a mapping (an object with a 'quantities' key), "
                f"got {type(mapping).__name__}"
            )
        unknown_top = set(mapping) - {"name", "quantities"}
        if unknown_top:
            # `k_warn`/`k_fail`/`representational_bound_floor` are the non-configurable knobs of
            # §4.4; naming them (or anything else at top level) is rejected, not quietly dropped.
            raise ValueError(
                f"unknown top-level key(s) in tolerance table: {sorted(unknown_top)}; only 'name' "
                "and 'quantities' are configurable (the k_warn/k_fail multipliers and the "
                "representational-bound floor are fixed per Part 5 §4.4)"
            )
        profile_name = mapping.get("name", name)
        if not isinstance(profile_name, str):
            raise ValueError(f"tolerance table 'name' must be a string, got {profile_name!r}")

        quantities = mapping.get("quantities", {})
        if not isinstance(quantities, dict):
            raise ValueError("tolerance table 'quantities' must be a mapping")
        valid = sorted(_BASES)
        bases = dict(_BASES)  # omitted quantities inherit the default base.
        for quantity, pair in quantities.items():
            if quantity not in _BASES:
                raise ValueError(
                    f"unknown tolerance quantity {quantity!r}; configurable quantities are {valid} "
                    "(discrete checks — counts, species, pbc, presence — admit no tolerance, "
                    "Part 5 §4.4)"
                )
            if not isinstance(pair, dict) or set(pair) != {"warn", "fail"}:
                raise ValueError(
                    f"quantity {quantity!r} must map to exactly {{warn, fail}}, got {pair!r}"
                )
            warn = _as_positive(quantity, "warn", pair.get("warn"))
            fail = _as_positive(quantity, "fail", pair.get("fail"))
            if warn > fail:
                raise ValueError(
                    f"quantity {quantity!r}: warn ({warn:g}) must not exceed fail ({fail:g})"
                )
            bases[quantity] = Bounds(warn, fail)
        return cls(profile_name, bases)

    def quantities(self) -> list[str]:
        return list(self._bases)

    def base(self, quantity: str) -> Bounds:
        return self._bases[quantity]

    def effective(self, quantity: str, representational_bound: float = 0.0) -> Bounds:
        """Effective (warn, fail) for ``quantity`` under this profile and a field's representational
        bound (Part 5 §4.2). The bound floor is never disabled: even a ``strict`` profile cannot
        demand agreement tighter than ``k × representational_bound``."""
        b = self._bases[quantity]
        return Bounds(
            warn=max(b.warn, K_WARN * representational_bound),
            fail=max(b.fail, K_FAIL * representational_bound),
        )

    def as_dict(self) -> dict[str, object]:
        """The full profile in force, embedded verbatim in the Validation Report so it is
        self-contained and re-thresholdable later (§3, §4.4). Mirrors the worked example's shape
        (Part 5 §6): named positions/lattice keys plus every other quantity's base pair, the
        ``k_*`` multipliers, and the non-disable-able floor flag."""
        out: dict[str, object] = {"name": self.name}
        out["positions_warn_ang"] = self._bases["positions"].warn
        out["positions_fail_ang"] = self._bases["positions"].fail
        out["lattice_warn_ang"] = self._bases["lattice"].warn
        out["lattice_fail_ang"] = self._bases["lattice"].fail
        for quantity, b in self._bases.items():
            if quantity in ("positions", "lattice"):
                continue
            out[f"{quantity}_warn"] = b.warn
            out[f"{quantity}_fail"] = b.fail
        out["k_warn"] = K_WARN
        out["k_fail"] = K_FAIL
        out["representational_bound_floor"] = "enabled"
        return out


def _as_positive(quantity: str, field: str, value: object) -> float:
    """Coerce a tolerance-table threshold to a non-negative float, or raise an actionable error.
    Bools are rejected explicitly (``True``/``False`` are ``int`` subclasses in Python)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"quantity {quantity!r}: {field!r} must be a number, got {value!r}")
    if value < 0:
        raise ValueError(f"quantity {quantity!r}: {field!r} must be non-negative, got {value:g}")
    return float(value)
