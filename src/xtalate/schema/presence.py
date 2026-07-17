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

Provenance is intentionally excluded: it is Xtalate's own always-populated record
(§3.9), not discoverable *source* information, so it carries no ✓/✗ signal.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sized
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel

if TYPE_CHECKING:
    from xtalate.schema.models import (
        CanonicalObject,
        Frame,
        SimulationMetadata,
        TrajectoryMetadata,
    )

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


class PresenceAccumulator:
    """Single-pass field-presence computation over a *streamed* trajectory (§3.11; M12).

    The streaming twin of ``compute_field_presence``: it reproduces that function's exact
    ``PresenceMap`` — same per-frame ``present``/``absent``/``mixed`` trichotomy, same root-level
    classification, same entry order — without ever holding all frames in memory. It reuses the
    *identical* ``_PER_FRAME``/``_ROOT`` getters so a streamed and a materialized object can never
    disagree about presence (standing rule 3: any such divergence is a stop-the-line bug).

    Usage is header-then-frames-then-result: ``observe_header`` once (root-level fields and the
    frame-invariant custom keys), ``observe_frame`` per streamed frame (accumulating per-frame
    present counts and the union of per-frame custom keys), then ``result()``.
    """

    def __init__(self, schema_version: str) -> None:
        self._schema_version = schema_version
        self._n_frames = 0
        # For each per-frame path: the frame indices where it is present (Part 2 §3.11 rule 2).
        self._present_frames: dict[str, list[int]] = {path: [] for path, _ in _PER_FRAME}
        self._root_status: dict[str, Status] = {path: "absent" for path, _ in _ROOT}
        self._custom_global_keys: list[str] = []
        self._custom_per_atom_keys: list[str] = []
        self._custom_per_frame_keys: list[str] = []  # union in first-seen order
        self._header_seen = False

    def observe_header(
        self,
        *,
        trajectory: TrajectoryMetadata | None,
        simulation: SimulationMetadata | None,
        tags: Iterable[str],
        annotations: dict[str, str],
        custom_global: Iterable[str],
        custom_per_atom: Iterable[str],
    ) -> None:
        """Classify the object-level (root) paths from the eager stream header, once.

        Mirrors the ``_ROOT`` sweep and the custom-key enumeration of ``compute_field_presence``,
        but reads the header's already-separated pieces rather than a whole object."""
        # Reconstruct the minimal shape the _ROOT getters expect: a lightweight stand-in exposing
        # `.trajectory`, `.simulation`, and `.user_metadata` (tags/annotations only — the two
        # enumerated non-custom user-metadata roots). Custom keys are handled separately below.
        view = _RootView(trajectory, simulation, list(tags), dict(annotations))
        stub = cast("CanonicalObject", view)
        for path, getter in _ROOT:
            self._root_status[path] = "present" if _present(getter(stub)) else "absent"
        self._custom_global_keys = list(custom_global)
        self._custom_per_atom_keys = list(custom_per_atom)
        self._header_seen = True

    @property
    def frame_count(self) -> int:
        """Number of frames folded in so far — the streaming analogue of
        ``CanonicalObject.frame_count`` for a consumer (e.g. the ``frame_count`` validation check)
        that needs the total without a materialized object."""
        return self._n_frames

    def observe_frame(self, frame: Frame, per_frame_custom_keys: Iterable[str] = ()) -> None:
        """Fold one streamed frame into the per-frame present counts and the per-frame custom-key
        union. ``per_frame_custom_keys`` names the ``custom_per_frame`` keys this frame carries a
        non-``None`` value for; their union across frames becomes the present custom entries."""
        idx = frame.index
        for path, getter in _PER_FRAME:
            if getter(frame) is not None:
                self._present_frames[path].append(idx)
        for key in per_frame_custom_keys:
            if key not in self._custom_per_frame_keys:
                self._custom_per_frame_keys.append(key)
        self._n_frames += 1

    def result(self) -> PresenceMap:
        """Assemble the ``PresenceMap``, entry-for-entry identical to ``compute_field_presence`` on
        the equivalent materialized object."""
        entries: list[PathPresence] = []
        n = self._n_frames
        for path, _ in _PER_FRAME:
            present = self._present_frames[path]
            if present and len(present) == n:
                entries.append(PathPresence(path=path, status="present"))
            elif not present:
                entries.append(PathPresence(path=path, status="absent"))
            else:
                entries.append(PathPresence(path=path, status="mixed", present_frames=present))
        for path, _ in _ROOT:
            entries.append(PathPresence(path=path, status=self._root_status[path]))
        for key in self._custom_global_keys:
            entries.append(
                PathPresence(path=f"user_metadata.custom_global['{key}']", status="present")
            )
        for key in self._custom_per_atom_keys:
            entries.append(
                PathPresence(path=f"user_metadata.custom_per_atom['{key}']", status="present")
            )
        for key in self._custom_per_frame_keys:
            entries.append(
                PathPresence(path=f"user_metadata.custom_per_frame['{key}']", status="present")
            )
        return PresenceMap(schema_version=self._schema_version, entries=entries)


class _RootView:
    """Adapter presenting the ``.trajectory``/``.simulation``/``.user_metadata`` attributes the
    ``_ROOT`` getters read, backed by a stream header's separated pieces. Only the two enumerated
    non-custom user-metadata roots (``tags``, ``annotations``) need to be exposed here; custom keys
    are classified directly from the header's key lists."""

    def __init__(
        self,
        trajectory: TrajectoryMetadata | None,
        simulation: SimulationMetadata | None,
        tags: list[str],
        annotations: dict[str, str],
    ) -> None:
        self.trajectory = trajectory
        self.simulation = simulation
        self.user_metadata = _UserMetadataView(tags, annotations)


class _UserMetadataView:
    def __init__(self, tags: list[str], annotations: dict[str, str]) -> None:
        self.tags = tags
        self.annotations = annotations
