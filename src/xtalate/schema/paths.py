"""Canonical field-path authority (MASTER_SPEC Part 2 §3 / Part 3 §4.1).

Capability declarations (`FormatCapabilities.fields`, `required_fields`) key on canonical
field paths — dotted strings like ``"dynamics.velocities"`` or the wildcard ``"simulation.*"``.
This module is the single source of *which paths exist*, so the Capability Matrix and the
schema cannot drift apart (Part 3 §4.1: "the registry rejects declarations with unknown
paths ... which keeps the matrix and the schema from drifting").

The path set is **derived from the pydantic models**, not hand-listed, so a field added to
the schema is a valid capability path automatically. A path is ``"<category>.<field>"`` for
each per-frame / root sub-model, plus the one per-frame scalar (`frame.time`) that lives
directly on ``Frame`` rather than in a sub-model.
"""

from __future__ import annotations

from pydantic import BaseModel

from xtalate.schema.models import (
    AtomsBlock,
    Cell,
    Dynamics,
    Electronic,
    Provenance,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)

# Category prefix -> the model whose fields are that category's leaf paths.
_CATEGORY_MODELS: dict[str, type[BaseModel]] = {
    "atoms": AtomsBlock,
    "cell": Cell,
    "dynamics": Dynamics,
    "electronic": Electronic,
    "trajectory": TrajectoryMetadata,
    "simulation": SimulationMetadata,
    "user_metadata": UserMetadata,
    "provenance": Provenance,
}

# Per-frame scalars living directly on Frame (not inside a sub-model). `frame.index` and
# `frame.atoms` are not capability-declarable leaves; `frame.time` is the one that is.
_FRAME_LEAVES = frozenset({"frame.time"})


def _build_paths() -> frozenset[str]:
    paths = set(_FRAME_LEAVES)
    for category, model in _CATEGORY_MODELS.items():
        for field_name in model.model_fields:
            paths.add(f"{category}.{field_name}")
    return frozenset(paths)


#: Every valid concrete canonical field path (leaves + whole-container keys such as
#: ``user_metadata.custom_per_atom``, which Part 3 §4.1 permits as a container-level key).
CANONICAL_FIELD_PATHS: frozenset[str] = _build_paths()

#: Category prefixes that may precede ``.*`` in a wildcard capability path (Part 3 §4.1).
WILDCARD_PREFIXES: frozenset[str] = frozenset(_CATEGORY_MODELS) | {"frame"}

#: Paths that are a *derived mirror* of another field, which no format stores on its own:
#: ``atoms.atomic_numbers`` is computed from ``atoms.symbols`` (`AtomsBlock` cross-checks them).
#: The completeness invariant, the pre-flight diff, and the round-trip comparable subspace all
#: exclude these — a derived field is never "lost", it is recomputed — so the exclusion is a schema
#: fact defined once here. (The property harness keeps its own copy on purpose, D50: an independent
#: re-derivation of the invariant must not import the value it checks against.)
DERIVED_PATHS: frozenset[str] = frozenset({"atoms.atomic_numbers"})


def is_valid_path(path: str) -> bool:
    """True if ``path`` is a concrete canonical field path (no wildcard)."""
    return path in CANONICAL_FIELD_PATHS


def expand_capability_path(path: str) -> list[str]:
    """Resolve one capability-declaration key to the concrete leaf paths it covers.

    A trailing ``.*`` expands to every leaf under that category prefix (Part 3 §4.1); a
    plain path returns itself. Raises ``ValueError`` for an unknown path or unknown
    category prefix — the check the registry runs at load time.
    """
    if path.endswith(".*"):
        prefix = path[:-2]
        if prefix not in WILDCARD_PREFIXES:
            raise ValueError(
                f"unknown capability wildcard prefix {prefix!r} in {path!r}; "
                f"valid prefixes: {sorted(WILDCARD_PREFIXES)}"
            )
        leaves = sorted(p for p in CANONICAL_FIELD_PATHS if p.split(".", 1)[0] == prefix)
        if not leaves:
            raise ValueError(f"capability wildcard {path!r} expands to no canonical paths")
        return leaves
    if path not in CANONICAL_FIELD_PATHS:
        raise ValueError(f"unknown canonical field path {path!r} (Part 2 §3)")
    return [path]
