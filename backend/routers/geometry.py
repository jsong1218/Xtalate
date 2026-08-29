"""Read-only geometry endpoints — canonical geometry to the browser (v1.6 M59-S1, D232).

``GET /v1/files/{file_id}/geometry`` and ``GET /v1/conversions/{conversion_id}/geometry``
(with ``?side=source|output``) serve the **canonical geometry** of the underlying bytes as JSON —
species, an optional cell, and ranged frame positions — riding the **existing streaming parse seam**
(:func:`xtalate.sdk.parse_as_stream` / ``FrameStream.frames()``), never re-implementing parsing or
scientific logic (the thin-API-by-law rule, extended to geometry; Part 6 §7 additive read-only
routes). Load-bearing constraints, each enforced here and pinned by
``tests/backend/test_geometry.py``:

* **Consumer of the streaming seam, never a second parse path.** A ranged request streams through
  the ordinary ``FrameStream``; frames outside the requested ``[start, end)`` window are counted and
  discarded, never held, so a 10⁴-frame trajectory is **never materialized whole on the server** —
  the S3 spike proves memory stays bounded per-range.
* **Absence renders as absence (P3).** A ``cell = None`` source answers ``cell: null``; a per-frame
  cell the source did not declare is ``null`` too. Nothing is zero-filled or fabricated.
* **Expiry-with-bytes, exactly like downloads.** The endpoints serve geometry only while the source
  / output bytes are live: an expired upload is ``410 FILE_EXPIRED`` and an expired output is
  ``410 OUTPUT_EXPIRED`` — modelled on ``downloads.py``'s ``_output_expired_error`` — while the
  conversion **record and its reports still resolve** (reports-outlive-bytes).
* **No bonds, no hidden export.** The Canonical Object holds no bonds, so this projection never
  returns a bond list (D234 — bonds are a display heuristic). The viewer is fed **this JSON**
  directly; nothing here writes a PDB/mmCIF or any intermediate format (P1).

Serving strategy (D232, rejected alternatives there): each request re-parses through the proven
streaming engine on demand, **behind a bounded server-side LRU** (:class:`GeometryCache`) keyed by
``(file_id | conversion_id+side)`` so a viewer that scrubs across ranges does not re-parse per
request while memory stays flat. The cache is byte-bounded: an object whose projected geometry
alone exceeds the bound is never cached, so a genuinely huge trajectory is streamed per request
(the bounded-memory posture the S3 spike measures), while the common single-structure viewer case
is served from cache after its first read.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, Query, status

from backend.config import Settings
from backend.db import Repository
from backend.deps import (
    get_geometry_cache,
    get_object_store,
    get_registry,
    get_repository,
    get_settings,
)
from backend.errors import ApiError
from backend.models import GeometryFrame, GeometryResponse, GeometrySource
from backend.records import output_bytes_expired, report_retention_expired
from backend.routers.jobs import _require_live_upload
from backend.storage import ObjectStore
from xtalate.capabilities import Registry
from xtalate.discovery import Sniffer
from xtalate.sdk import ParseError, ParserPlugin, parse_as_stream

if TYPE_CHECKING:
    from backend.db.models import Upload
    from xtalate.schema import Frame
    from xtalate.sdk import FrameStream

router = APIRouter()

#: The ``?frames=start:end`` parameter is half-open (``[start, end)``), 0-based — the streaming
#: convention (frame indices are their 0-based trajectory positions, Part 2 §3.5). There is no other
#: ``frames=`` range on the wire to conflict with, so ``start:end`` is chosen here and made
#: normative.
_FRAMES_RE = re.compile(r"^(?P<start>\d+):(?P<end>\d+)$")

#: Default request: no ``frames`` param returns only frame 0 (the structure), bounded by
#: construction — a consumer of the endpoint never materializes a whole trajectory unless it asks
#: for it explicitly.
_DEFAULT_FRAME_RANGE = (0, 1)

#: Rough per-projected-frame byte estimate (nested-list floats as 8-byte placeholders + a constant).
_EST_CELL_FLOATS = 9
_EST_FRAME_OVERHEAD = 128


class GeometryCache:
    """A bounded LRU of projected geometry keyed by ``(file_id | conversion_id+side)`` (D232).

    The cache holds the **fully projected** frame list for an object (species + cell + whole frame
    set), so a later ranged request slices any window from cache without re-reading or re-parsing
    the source. It is bounded in **bytes**, not just count: the LRU evicts oldest-first until the
    total projected size is under :attr:`max_bytes`, and an object whose projected size **alone**
    exceeds
    the cap is never cached at all — that object streams per request, keeping server memory bounded
    per range (the S3 spike records the figure). Small objects (the common single-structure viewer
    case) fit and are served from cache thereafter.

    This is a pure in-memory cache; it is keyed off live storage identifiers and never outlives the
    process. It is built once on ``app.state`` by the factory (never a module global) so a test gets
    an isolated instance via dependency injection.
    """

    __slots__ = ("max_bytes", "_data", "_bytes")

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        #: Ordered map ``key -> (entry, entry_bytes)``; iteration order is access (LRU) order.
        self._data: OrderedDict[tuple[str, ...], tuple[dict[str, Any], int]] = OrderedDict()
        self._bytes = 0

    def get(self, key: tuple[str, ...]) -> dict[str, Any] | None:
        """Cached projected geometry for ``key``, or None (bumping it to LRU-most-recent)."""
        hit = self._data.pop(key, None)
        if hit is None:
            return None
        self._data[key] = hit  # move_to_end: this key is now most-recent
        return hit[0]

    def set(self, key: tuple[str, ...], entry: dict[str, Any]) -> None:
        """Cache ``entry`` (an object whose ``frames`` is the full projection), evicting as needed.

        A single entry larger than the whole budget is dropped outright — with the budget full it
        can never fit, and caching it would exceed the bound on every future request until evicted.
        """
        entry_bytes = _estimate_geometry_bytes(entry["frames"])
        if entry_bytes > self.max_bytes:
            return
        old = self._data.pop(key, None)
        if old is not None:
            self._bytes -= old[1]
        self._data[key] = (entry, entry_bytes)
        self._bytes += entry_bytes
        while self._bytes > self.max_bytes and self._data:
            _, (_, evicted_bytes) = self._data.popitem(last=False)  # evict least-recent
            self._bytes -= evicted_bytes


def _estimate_geometry_bytes(frames: list[GeometryFrame]) -> int:
    """A conservative byte estimate of a projected frame list, for the cache bound."""
    total = 0
    for frame in frames:
        floats = sum(len(row) for row in frame.positions)
        if frame.cell is not None:
            floats += _EST_CELL_FLOATS
        total += floats * 8 + _EST_FRAME_OVERHEAD
    return total


def _lattice_or_none(cell: Any) -> list[list[float]] | None:
    """A frame's ``(3, 3)`` lattice as a nested list, or ``None`` when the source had none."""
    if cell is None:
        return None
    return cast(list[list[float]], cell.lattice_vectors.tolist())


def _cache_key(*parts: str) -> tuple[str, ...]:
    """The cache key tuple for a geometry source — ``(kind, id[, side])``."""
    return parts


def _project(frame: Frame) -> GeometryFrame:
    """Project one parsed ``Frame`` onto the wire geometry shape (absent cell → ``null``)."""
    lattice = _lattice_or_none(frame.cell)
    return GeometryFrame(
        index=frame.index,
        positions=frame.atoms.positions.tolist(),
        cell=lattice,
    )


def _collect_geometry(
    stream: FrameStream, start: int, end: int, cache: GeometryCache
) -> dict[str, Any]:
    """Stream once and return ``{species, cell, frame_count, frames}`` for ``[start, end)``.

    One pass over ``FrameStream.frames()``. Every frame is counted (for the exact ``frame_count``)
    and, until the cache budget is exhausted, accumulated into an evictable full projection (the
    cache candidate); frames inside the requested window are collected into ``wanted``. A frame
    outside the window is **discarded after counting** — server memory stays bounded by the window
    plus the (bounded) cache candidate, which is exactly the "never materialize the whole
    trajectory" guarantee the S3 spike measures. ``species``/``cell`` are the frame-0 object shape.
    """
    total = 0
    species: list[str] = []
    cell: list[list[float]] | None = None
    wanted: list[GeometryFrame] = []
    candidate: list[GeometryFrame] | None = []
    candidate_bytes = 0
    for stream_frame in stream.frames():
        frame = stream_frame.frame
        if total == 0:
            species = list(frame.atoms.symbols)
            cell = _lattice_or_none(frame.cell)
        total += 1
        if candidate is not None:
            gf = _project(frame)
            candidate.append(gf)
            candidate_bytes += _estimate_single(gf)
            if candidate_bytes > cache.max_bytes:
                candidate = None  # too large to ever cache — stop accumulating, keep counting
        if start <= frame.index < end:
            wanted.append(_project(frame))
    return {
        "species": species,
        "cell": cell,
        "frame_count": total,
        "frames": wanted,
        # The full projection, present only when it stayed within the cache budget.
        "_candidate": None if candidate is None else {"frames": candidate},
    }


def _estimate_single(frame: GeometryFrame) -> int:
    floats = sum(len(row) for row in frame.positions)
    if frame.cell is not None:
        floats += _EST_CELL_FLOATS
    return floats * 8 + _EST_FRAME_OVERHEAD


def _parse_range(spec: str | None) -> tuple[int, int]:
    """Interpret the ``?frames=start:end`` parameter as a half-open ``[start, end)`` range."""
    if spec is None:
        return _DEFAULT_FRAME_RANGE
    match = _FRAMES_RE.match(spec)
    if match is None:
        raise ApiError(
            status_code=400,  # literal — the parameter is malformed, a client error (Part 6 §6)
            code="INVALID_FRAME_RANGE",
            message=(
                "The 'frames' parameter must be 'start:end' of non-negative integers "
                "(0-based, half-open). A reversed or overlapping range is rejected."
            ),
        )
    start = int(match.group("start"))
    end = int(match.group("end"))
    if start >= end:
        raise ApiError(
            status_code=400,
            code="INVALID_FRAME_RANGE",
            message=(
                "The 'frames' range must satisfy start < end (a half-open [start, end) window "
                "cannot be empty or reversed)."
            ),
        )
    return start, end


def _parse_into_read(
    data: bytes,
    filename: str | None,
    format_id: str,
    registry: Registry,
    start: int,
    end: int,
    cache: GeometryCache,
    key: tuple[str, ...],
) -> dict[str, Any] | None:
    """Stream ``data`` via the SDK seam for ``format_id`` and return the projected read.

    Returns ``None`` only when no parser is registered for ``format_id`` (the caller surfaces a
    ``422 UNKNOWN_FORMAT``). Streams once through ``parse_as_stream``, stores the budget-permitted
    full projection in the cache for ``key``, and returns the ``[start, end)`` window (plus
    ``format_id``, ``species``, ``cell``, and the whole object's ``frame_count``).
    """
    parser = registry_parser_or_none(registry, format_id)
    if parser is None:
        return None
    stream = parse_as_stream(parser, data, filename=filename)
    read = _collect_geometry(stream, start, end, cache)
    candidate = read.pop("_candidate", None)
    read["format_id"] = format_id
    if candidate is not None:
        cache.set(
            key,
            {
                "format_id": format_id,
                "species": read["species"],
                "cell": read["cell"],
                "frames": candidate["frames"],
            },
        )
    return read


def _serve_cached(
    cached: dict[str, Any], source: GeometrySource, start: int, end: int
) -> GeometryResponse:
    """Slice the requested ``[start, end)`` window from a cached full projection.

    A cache entry holds the whole object's projected frames from index 0; ``frame.index ==
    position`` (Part 2 §3.5), so slicing by absolute index yields the requested window. The window
    is clamped to the object's own total; ``frame_count`` reports that total.
    """
    full: list[GeometryFrame] = cached["frames"]
    total = len(full)
    effective_end = min(end, total)
    return GeometryResponse(
        source=source,
        species=cached["species"],
        cell=cached["cell"],
        frame_index_base=start,
        frame_count=total,
        frames=full[start:effective_end],
    )


def registry_parser_or_none(registry: Registry, format_id: str) -> ParserPlugin | None:
    """The registered parser for ``format_id``, or ``None`` if no parser can read that format."""
    try:
        return registry.get_parser(format_id)
    except KeyError:
        return None


def _source_of(upload: Upload, format_id: str) -> GeometrySource:
    return GeometrySource(format_id=format_id, filename=upload.filename)


def _read_bytes(object_store: ObjectStore, key: str) -> bytes:
    with object_store.open(key) as chunks:
        return b"".join(chunks)


def _parse_error(exc: ParseError) -> ApiError:
    codes = {issue.code for issue in exc.issues if issue.severity == "error"}
    code = "UNKNOWN_FORMAT" if codes == {"UNKNOWN_FORMAT"} else "PARSE_ERROR"
    message = "; ".join(i.message for i in exc.issues) or "The file could not be parsed."
    return ApiError(
        status_code=422,  # literal — a genuine parse taxonomy, not one of the deprecated constants
        code=code,
        message=message,
        details={"issues": [{"code": i.code, "message": i.message} for i in exc.issues]},
    )


def _resolve_file_geometry(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    cache: GeometryCache,
    *,
    file_id: str,
    frames: str | None,
) -> GeometryResponse:
    _require_live_upload(repository, file_id)
    upload = repository.get_upload(file_id)
    if upload is None:  # pragma: no cover - _require_live_upload verified it exists.
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "FILE_NOT_FOUND", f"No uploaded file {file_id!r}."
        )
    start, end = _parse_range(frames)
    key = _cache_key("file", file_id)
    cached = cache.get(key)
    if cached is not None:
        return _serve_cached(cached, _source_of(upload, cached["format_id"]), start, end)
    data = _read_bytes(object_store, upload.storage_key)
    override = upload.format_override
    if override is not None:
        format_id: str | None = override
    else:
        format_id = Sniffer(registry).sniff(data, upload.filename).format_id
    if format_id is None:
        raise ApiError(
            status_code=422,
            code="UNKNOWN_FORMAT",
            message=(
                "The file's format could not be identified; pass an explicit format override."
            ),
        )
    read = _parse_into_read(data, upload.filename, format_id, registry, start, end, cache, key)
    if read is None:
        raise ApiError(
            status_code=422,
            code="UNKNOWN_FORMAT",
            message=f"No parser is registered for format {format_id!r}.",
        )
    return _response(read, _source_of(upload, format_id), start)


def _resolve_conversion_geometry(
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
    cache: GeometryCache,
    *,
    conversion_id: str,
    side: str,
    frames: str | None,
) -> GeometryResponse:
    conversion = repository.get_conversion(conversion_id)
    if conversion is None or report_retention_expired(conversion, settings):
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "CONVERSION_NOT_FOUND",
            f"No conversion {conversion_id!r}.",
        )
    start, end = _parse_range(frames)
    key = _cache_key("conversion", conversion_id, side)
    # Both branches compute ``format_id``/``filename``; they are declared optional up front so the
    # output branch's ``str`` target_format and the source branch's ``str | None`` (sniffed-or-
    # recorded) share one variable without an incompatible-assignment error, and narrowed to str in
    # the shared tail below.
    format_id: str | None
    filename: str | None
    if side == "output":
        if output_bytes_expired(conversion) or conversion.output_storage_key is None:
            raise _output_expired_error(conversion_id)
        format_id = conversion.target_format
        # Output has no upload name; report the target format id as the filename stand-in.
        filename = conversion.target_format
        cached = cache.get(key)
        if cached is not None:
            return _serve_cached(
                cached, GeometrySource(format_id=cached["format_id"], filename=filename), start, end
            )
        data = _read_bytes(object_store, conversion.output_storage_key)
    else:  # side == "source"
        file_id = conversion.source_file_id
        if file_id is None:
            raise ApiError(
                status.HTTP_410_GONE,
                "FILE_EXPIRED",
                "The source upload for this conversion is gone; its geometry is unavailable while "
                "the record and reports remain readable.",
            )
        _require_live_upload(repository, file_id)
        upload = repository.get_upload(file_id)
        if upload is None:  # pragma: no cover - _require_live_upload verified it exists.
            raise ApiError(status.HTTP_404_NOT_FOUND, "FILE_NOT_FOUND", f"No file {file_id!r}.")
        cached = cache.get(key)
        if cached is not None:
            return _serve_cached(cached, _source_of(upload, cached["format_id"]), start, end)
        data = _read_bytes(object_store, upload.storage_key)
        format_id = (
            conversion.source_format
            or upload.format_override
            or Sniffer(registry).sniff(data, upload.filename).format_id
        )
        filename = upload.filename
        if format_id is None:
            raise ApiError(
                status_code=422,
                code="UNKNOWN_FORMAT",
                message="The source's format could not be identified.",
            )
    read = _parse_into_read(data, filename, format_id, registry, start, end, cache, key)
    if read is None:
        raise ApiError(
            status_code=422,
            code="UNKNOWN_FORMAT",
            message=f"No parser is registered for format {format_id!r}.",
        )
    return _response(read, GeometrySource(format_id=format_id, filename=filename), start)


def _output_expired_error(conversion_id: str) -> ApiError:
    """The downloads-style ``410 OUTPUT_EXPIRED`` envelope — the geometry twin of downloads."""
    return ApiError(
        status_code=status.HTTP_410_GONE,
        code="OUTPUT_EXPIRED",
        message=(
            f"The converted output for {conversion_id!r} is no longer available; "
            "its reports remain retrievable via GET /v1/conversions/{id}."
        ),
    )


def _response(read: dict[str, Any], source: GeometrySource, start: int) -> GeometryResponse:
    return GeometryResponse(
        source=source,
        species=read["species"],
        cell=read["cell"],
        frame_index_base=start,
        frame_count=read["frame_count"],
        frames=read["frames"],
    )


@router.get(
    "/files/{file_id}/geometry",
    response_model=GeometryResponse,
    tags=["files"],
)
def file_geometry(
    file_id: str,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    registry: Registry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
    cache: GeometryCache = Depends(get_geometry_cache),
    frames: str | None = Query(
        default=None,
        description=(
            "Half-open 0-based frame range 'start:end' (e.g. '0:100'); omitting it returns only "
            "frame 0 (the structure)."
        ),
    ),
) -> GeometryResponse:
    """Canonical geometry of an uploaded file (read-only, Part 6 §7)."""
    try:
        return _resolve_file_geometry(
            repository,
            object_store,
            registry,
            settings,
            cache,
            file_id=file_id,
            frames=frames,
        )
    except ParseError as exc:
        raise _parse_error(exc) from exc


@router.get(
    "/conversions/{conversion_id}/geometry",
    response_model=GeometryResponse,
    tags=["conversions"],
)
def conversion_geometry(
    conversion_id: str,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    registry: Registry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
    cache: GeometryCache = Depends(get_geometry_cache),
    side: str = Query(
        default="source",
        pattern="^(source|output)$",
        description="Which side's bytes to project: 'source' (the upload) or 'output'.",
    ),
    frames: str | None = Query(
        default=None,
        description=(
            "Half-open 0-based frame range 'start:end' (e.g. '0:100'); omitting it returns only "
            "frame 0 (the structure)."
        ),
    ),
) -> GeometryResponse:
    """Canonical geometry of a conversion's source or output bytes (read-only, Part 6 §7)."""
    try:
        return _resolve_conversion_geometry(
            repository,
            object_store,
            registry,
            settings,
            cache,
            conversion_id=conversion_id,
            side=side,
            frames=frames,
        )
    except ParseError as exc:
        raise _parse_error(exc) from exc
