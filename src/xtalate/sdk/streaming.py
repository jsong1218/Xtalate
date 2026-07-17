"""Streaming parse/export surface (MASTER_SPEC Part 3 §2; M12).

The additive interface that makes memory growth **sub-linear in frames** without a second
canonical path. A trajectory is split into two parts: an eager *header* (everything the source
declares once — provenance, trajectory/simulation metadata, and the frame-invariant user
metadata) and a lazy *frame stream* (one ``StreamFrame`` per source frame, yielded on demand).
A consumer iterates the stream exactly once, holding at most a chunk of frames resident, then
finalizes from accumulated state.

Design (DECISIONS.md D56, with the rejected alternative):

* **Header parsed eagerly, frames lazily.** ``StreamHeader`` carries the object-level fields
  (``provenance``, ``trajectory``, ``simulation``, and the frame-independent halves of
  ``user_metadata``: ``tags``/``annotations``/``custom_global``/``custom_per_atom``). Everything
  that is genuinely *per frame* — the scientific ``Frame`` plus its slice of ``custom_per_frame``
  — travels with the frame, so nothing that scales with frame count lands in the header.
* **Single-pass by contract.** ``FrameStream.frames()`` may be a one-shot generator over an open
  file; a consumer that needs two passes must materialize (``materialize``). Iterating twice is a
  programming error, not a supported mode.
* **Errors mid-stream honor the frozen contract (Part 3 §5).** A ``StreamFrame`` generator raises
  ``ParseError`` at the offending frame; warnings accumulate on the stream's ``issues`` list as
  frames are yielded (readable only *after* the frames that produced them). "Warnings accompany
  success; errors preclude it" holds identically to the whole-file path.
* **Materializing fallback, named.** ``ParserPlugin.parse_stream`` /
  ``ExporterPlugin.export_stream`` are optional (additive to the frozen contracts, like
  ``atom_permutation`` — DECISIONS.md D23/D38). A plugin that implements only the whole-file
  method is adapted by ``materialize`` / ``stream_of`` so every consumer can treat all plugins
  uniformly; that adapter *is* the current whole-file behavior, now a named fallback rather than
  the only path.

The **rejected alternative** was a lazy ``CanonicalObject`` whose ``frames`` is a generator: it
would have let existing code touch ``obj.frames`` unchanged, but a pydantic model that lies about
being a materialized value is exactly the "best-effort object presented as data" the project
forbids (P1) — every ``len(obj.frames)``, re-iteration, or validator would silently exhaust or
re-run the stream. Splitting header from frames makes the single-pass constraint explicit in the
type instead of hiding it inside a familiar one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from xtalate.schema import (
    CanonicalObject,
    Frame,
    Provenance,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.sdk.results import ParseIssue

if TYPE_CHECKING:
    from xtalate.sdk.plugins import ExporterPlugin, ParserPlugin


@dataclass
class StreamHeader:
    """Object-level metadata parsed eagerly, before any frame is streamed.

    Holds exactly the fields whose size does **not** grow with frame count: the always-present
    ``provenance`` and ``schema_version``, the optional ``trajectory``/``simulation`` containers,
    and the frame-independent parts of ``user_metadata``. ``custom_per_frame`` is intentionally
    absent — it is per-frame data and rides with each ``StreamFrame`` instead.
    """

    schema_version: str
    provenance: Provenance
    trajectory: TrajectoryMetadata | None = None
    simulation: SimulationMetadata | None = None
    tags: list[str] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)
    custom_global: dict[str, Any] = field(default_factory=dict)
    # First dim = N (atom count), frame-invariant by the canonical model (Part 2 §3.10).
    custom_per_atom: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_object(cls, obj: CanonicalObject) -> StreamHeader:
        """The header half of an already-materialized object — the basis of the ``stream_of``
        adapter that lets a whole-file parser masquerade as a streaming one."""
        um = obj.user_metadata
        return cls(
            schema_version=obj.schema_version,
            provenance=obj.provenance,
            trajectory=obj.trajectory,
            simulation=obj.simulation,
            tags=list(um.tags),
            annotations=dict(um.annotations),
            custom_global=dict(um.custom_global),
            custom_per_atom=dict(um.custom_per_atom),
        )


@dataclass
class StreamFrame:
    """One source frame plus its own slice of the object-level per-frame custom metadata.

    ``per_frame_custom`` maps each ``custom_per_frame`` key present *for this frame* to that
    frame's value (a JSON scalar or nested list). Keys absent for a frame are simply omitted;
    the materializer re-assembles the length-F lists (``None`` where a frame omitted a key) that
    ``UserMetadata.custom_per_frame`` stores, reproducing the whole-file representation exactly.
    """

    frame: Frame
    per_frame_custom: dict[str, Any] = field(default_factory=dict)


class FrameStream:
    """An eager header plus a single-pass iterator of ``StreamFrame`` (M12).

    ``issues`` collects warning-severity ``ParseIssue``s the frame generator emits as it runs;
    it is only complete once iteration is exhausted (a warning about frame *k* cannot exist before
    frame *k* is yielded). A ``ParseError`` raised by the generator propagates to the consumer
    unchanged, honoring the frozen error contract (Part 3 §5).
    """

    def __init__(
        self,
        header: StreamHeader,
        frame_iter: Iterator[StreamFrame],
        *,
        issues: list[ParseIssue] | None = None,
    ) -> None:
        self.header = header
        self.issues = issues if issues is not None else []
        self._frame_iter = frame_iter
        self._consumed = False

    def frames(self) -> Iterator[StreamFrame]:
        """Yield each ``StreamFrame`` once. Raises ``RuntimeError`` on a second traversal — the
        single-pass contract is enforced, not merely documented, so a consumer that needs two
        passes is forced to materialize rather than silently re-run (or exhaust) the source."""
        if self._consumed:
            raise RuntimeError(
                "FrameStream.frames() is single-pass; it was already consumed. Materialize the "
                "stream (sdk.streaming.materialize) if you need to iterate more than once."
            )
        self._consumed = True
        yield from self._frame_iter


def materialize(stream: FrameStream) -> tuple[CanonicalObject, list[ParseIssue]]:
    """Drain a ``FrameStream`` into a whole ``CanonicalObject`` (the named materializing fallback).

    Re-assembles the object-level ``custom_per_frame`` lists from the per-frame slices, so a
    round-trip ``obj -> stream_of -> materialize`` is the identity on the reconstructable content.
    Returns the object and the stream's accumulated warnings (now complete, iteration having run).
    """
    frames: list[Frame] = []
    per_frame_keys: list[str] = []  # union in first-seen order (matches whole-file parsers)
    per_frame_rows: list[dict[str, Any]] = []
    for sf in stream.frames():
        frames.append(sf.frame)
        for key in sf.per_frame_custom:
            if key not in per_frame_keys:
                per_frame_keys.append(key)
        per_frame_rows.append(sf.per_frame_custom)

    n_frames = len(frames)
    custom_per_frame: dict[str, Any] = {
        key: [row.get(key) for row in per_frame_rows] for key in per_frame_keys
    }
    h = stream.header
    user_metadata = UserMetadata(
        tags=list(h.tags),
        annotations=dict(h.annotations),
        custom_global=dict(h.custom_global),
        custom_per_atom=dict(h.custom_per_atom),
        custom_per_frame=custom_per_frame,
    )
    # A lone frame is a structure, not a trajectory (Part 2 §3.2): drop the trajectory container
    # so a materialized single-frame stream matches what a whole-file parser would have produced.
    trajectory = h.trajectory if n_frames > 1 else None
    obj = CanonicalObject(
        schema_version=h.schema_version,
        frames=frames,
        trajectory=trajectory,
        simulation=h.simulation,
        provenance=h.provenance,
        user_metadata=user_metadata,
    )
    return obj, list(stream.issues)


def stream_of(obj: CanonicalObject, issues: list[ParseIssue] | None = None) -> FrameStream:
    """Adapt an already-materialized ``CanonicalObject`` into a ``FrameStream`` (the fallback a
    non-streaming parser is wrapped in). The frames are yielded from the in-memory list — memory
    is *not* reduced here (the object is already whole); this adapter exists so every consumer can
    speak one interface regardless of whether the plugin streamed."""
    header = StreamHeader.from_object(obj)
    per_frame = obj.user_metadata.custom_per_frame

    def _iter() -> Iterator[StreamFrame]:
        for i, frame in enumerate(obj.frames):
            row = {
                key: (values[i] if i < len(values) else None)
                for key, values in per_frame.items()
                if (values[i] if i < len(values) else None) is not None
            }
            yield StreamFrame(frame=frame, per_frame_custom=row)

    return FrameStream(header, _iter(), issues=issues)


def parse_as_stream(parser: ParserPlugin, data: bytes, *, filename: str | None) -> FrameStream:
    """Obtain a ``FrameStream`` for ``data`` from any parser — the streaming one if it implements
    ``parse_stream``, otherwise the whole-file ``parse`` adapted through ``stream_of``. This is the
    single seam the registry/engine call so that streaming is transparent to the caller."""
    import io

    if parser.supports_streaming():
        return parser.parse_stream(io.BytesIO(data), filename=filename)
    result = parser.parse(io.BytesIO(data), filename=filename)
    return stream_of(result.canonical, issues=list(result.issues))


def export_stream(
    exporter: ExporterPlugin, header: StreamHeader, frames: Iterator[StreamFrame], out: BinaryIO
) -> None:
    """Write a frame stream through any exporter — the streaming path if it implements
    ``export_stream``, otherwise materialize and hand the whole object to ``export``. Mirror of
    ``parse_as_stream`` on the write side."""
    if exporter.supports_streaming():
        exporter.export_stream(header, frames, out)
        return
    obj, _ = materialize(FrameStream(header, frames))
    exporter.export(obj, out)


__all__ = [
    "FrameStream",
    "StreamFrame",
    "StreamHeader",
    "export_stream",
    "materialize",
    "parse_as_stream",
    "stream_of",
]
