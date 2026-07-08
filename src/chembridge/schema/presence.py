"""Field-presence introspection: ``field_presence()`` and ``PresenceMap`` (Part 2 §3.11).

Presence is the load-bearing *derived* view of a Canonical Object — consumed by the
Information Discovery Engine (Part 3 §6), the Conversion Engine's pre-flight diff and
completeness invariant (Part 4 §2), and two Validation checks (Part 5 §2). Per the
philosophy (§2 rule 5) it is **computed on demand** from the ``None``/populated state of
the object, never stored in a parallel structure that could drift.

Granularity rules (§3.11):

1. Root-level paths (``trajectory.*``, ``simulation.*``, ``user_metadata.*``) are
   ``present`` or ``absent`` — never ``mixed``.
2. Per-frame paths (everything under ``Frame``) are evaluated across *all* frames:
   uniformly populated -> ``present``; uniformly ``None`` -> ``absent``; populated in some
   frames only -> ``mixed``, with ``present_frames`` listing the indices.
3. Presence, not validity — this reports what exists, never whether it is correct.

Provenance is intentionally excluded: it is ChemBridge's own always-populated record
(§3.9), not discoverable *source* information, so it carries no ✓/✗ signal.
"""

from __future__ import annotations

from collections.abc import Callable, Sized
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from chembridge.schema.models import CanonicalObject, Frame

Status = Literal["present", "absent", "mixed"]


class PathPresence(BaseModel):
    path: str  # A canonical field path, e.g. "dynamics.velocities".
    status: Status
    # For per-frame paths: the frame indices where the field is present. None for
    # root-level paths and for uniformly present/absent per-frame paths.
    present_frames: list[int] | None = None


class PresenceMap(BaseModel):
    """Return type of ``CanonicalObject.field_presence()``. One entry per classified
    canonical path, in a stable schema-declaration order."""

    schema_version: str
    entries: list[PathPresence]

    def status_of(self, path: str) -> Status:
        for entry in self.entries:
            if entry.path == path:
                return entry.status
        return "absent"

    def present_paths(self) -> list[str]:
        """Paths with status ``present`` or ``mixed``."""
        return [e.path for e in self.entries if e.status in ("present", "mixed")]


def _present(value: Any) -> bool:
    """Presence for a *value*: ``None`` is absent; an empty container is absent; a number
    (including ``0``/``0.0``) or non-empty value is present. Zero is data (§2 rule 3)."""
    if value is None:
        return False
    if isinstance(value, Sized) and not isinstance(value, str):
        return len(value) > 0
    if isinstance(value, str):
        return len(value) > 0
    return True


# Per-frame paths in schema-declaration order (§3.5 -> §3.3 -> §3.4 -> §3.6 -> §3.7).
# Each getter returns the field value (or None) for one frame; presence is "is not None"
# so that a scientifically meaningful empty value — e.g. constraints=[] "explicitly
# unconstrained" (§3.6) — still counts as present.
_PER_FRAME: tuple[tuple[str, Callable[[Frame], Any]], ...] = (
    ("frame.time", lambda f: f.time),
    ("atoms.symbols", lambda f: f.atoms.symbols),
    ("atoms.atomic_numbers", lambda f: f.atoms.atomic_numbers),
    ("atoms.positions", lambda f: f.atoms.positions),
    ("atoms.masses", lambda f: f.atoms.masses),
    ("cell.lattice_vectors", lambda f: f.cell.lattice_vectors if f.cell else None),
    ("cell.pbc", lambda f: f.cell.pbc if f.cell else None),
    ("cell.space_group", lambda f: f.cell.space_group if f.cell else None),
    ("dynamics.velocities", lambda f: f.dynamics.velocities),
    ("dynamics.forces", lambda f: f.dynamics.forces),
    ("dynamics.constraints", lambda f: f.dynamics.constraints),
    ("electronic.total_energy", lambda f: f.electronic.total_energy),
    ("electronic.stress", lambda f: f.electronic.stress),
    ("electronic.charges", lambda f: f.electronic.charges),
    ("electronic.magnetic_moments", lambda f: f.electronic.magnetic_moments),
    ("electronic.total_spin", lambda f: f.electronic.total_spin),
)

# Root-level scalar/container paths (§3.5, §3.8, §3.10). Presence uses _present (empty
# container == absent). custom_* keys are enumerated dynamically per object below.
_ROOT: tuple[tuple[str, Callable[[CanonicalObject], Any]], ...] = (
    ("trajectory.timestep", lambda o: o.trajectory.timestep if o.trajectory else None),
    ("simulation.source_code", lambda o: o.simulation.source_code if o.simulation else None),
    ("simulation.calculator", lambda o: o.simulation.calculator if o.simulation else None),
    ("simulation.xc_functional", lambda o: o.simulation.xc_functional if o.simulation else None),
    (
        "simulation.pseudopotentials",
        lambda o: o.simulation.pseudopotentials if o.simulation else None,
    ),
    ("simulation.thermostat", lambda o: o.simulation.thermostat if o.simulation else None),
    ("simulation.md_ensemble", lambda o: o.simulation.md_ensemble if o.simulation else None),
    ("simulation.temperature", lambda o: o.simulation.temperature if o.simulation else None),
    ("simulation.extra", lambda o: o.simulation.extra if o.simulation else None),
    ("user_metadata.tags", lambda o: o.user_metadata.tags),
    ("user_metadata.annotations", lambda o: o.user_metadata.annotations),
)


def _classify_per_frame(frames: list[Frame], getter: Callable[[Frame], Any]) -> PathPresence:
    present_frames = [f.index for f in frames if getter(f) is not None]
    n = len(frames)
    if len(present_frames) == n:
        return PathPresence(path="", status="present")
    if not present_frames:
        return PathPresence(path="", status="absent")
    return PathPresence(path="", status="mixed", present_frames=present_frames)


def compute_field_presence(obj: CanonicalObject) -> PresenceMap:
    """Walk the schema once and classify every canonical field path (§3.11)."""
    entries: list[PathPresence] = []

    for path, getter in _PER_FRAME:
        entry = _classify_per_frame(obj.frames, getter)
        entries.append(entry.model_copy(update={"path": path}))

    for path, root_getter in _ROOT:
        status: Status = "present" if _present(root_getter(obj)) else "absent"
        entries.append(PathPresence(path=path, status=status))

    # Dynamic custom paths — per-file keys that vary and so are not enumerable in the
    # schema (§6). Each present key becomes its own root-level entry.
    um = obj.user_metadata
    for key in um.custom_global:
        entries.append(PathPresence(path=f"user_metadata.custom_global['{key}']", status="present"))
    for key in um.custom_per_atom:
        entries.append(
            PathPresence(path=f"user_metadata.custom_per_atom['{key}']", status="present")
        )
    for key in um.custom_per_frame:
        entries.append(
            PathPresence(path=f"user_metadata.custom_per_frame['{key}']", status="present")
        )

    return PresenceMap(schema_version=obj.schema_version, entries=entries)
