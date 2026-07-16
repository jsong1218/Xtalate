"""Canonical Model — the single in-memory/serialized representation (MASTER_SPEC Part 2).

Depends on nothing else in the package (lowest layer of the P2 dependency graph, Part 1
§5.1). Implemented in M1.
"""

from xtalate.schema.models import (
    SCHEMA_VERSION,
    AtomsBlock,
    CanonicalObject,
    Cell,
    Constraint,
    ConversionRecord,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.schema.presence import PathPresence, PresenceAccumulator, PresenceMap

__all__ = [
    "SCHEMA_VERSION",
    "AtomsBlock",
    "CanonicalObject",
    "Cell",
    "Constraint",
    "ConversionRecord",
    "Dynamics",
    "Electronic",
    "Frame",
    "PathPresence",
    "PresenceAccumulator",
    "PresenceMap",
    "Provenance",
    "SimulationMetadata",
    "TrajectoryMetadata",
    "UserMetadata",
]
