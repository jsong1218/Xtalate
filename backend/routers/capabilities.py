"""``GET /v1/capabilities`` — the Capability Matrix, straight from the registry (Part 6).

The service holds **no** format knowledge of its own (Part 1 §2): it asks the ``xtalate`` registry
for its capability matrix and dumps the library's ``FormatCapabilities`` models verbatim — no DTO,
no reshaping (Part 6 preamble). The seven Phase-1 formats therefore appear here with zero API-side
work, and a plugin that adds an eighth appears the moment it is installed. The payload is
byte-for-byte the CLI's ``xtalate capabilities --json`` (the same construction), which the M21
done-means asserts as a test.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from backend.deps import get_registry
from backend.errors import ApiError
from xtalate.capabilities import Registry

router = APIRouter()

# The two conversion directions a format may declare, in the CLI's iteration order — so the
# JSON here matches `xtalate capabilities --json` exactly (M21 done-means).
_DIRECTIONS = ("read", "write")


def _declarations(registry: Registry, format_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Build ``{format_id: {direction: capabilities}}`` — the CLI's exact shape."""
    matrix = registry.capability_matrix()
    out: dict[str, dict[str, Any]] = {}
    for fid in format_ids:
        directions: dict[str, Any] = {}
        for direction in _DIRECTIONS:
            try:
                directions[direction] = matrix.get(fid, direction).model_dump(mode="json")
            except KeyError:
                continue
        out[fid] = directions
    return out


def _known_format_ids(registry: Registry) -> set[str]:
    return {p.format_id for p in registry.parsers()} | {e.format_id for e in registry.exporters()}


@router.get("/capabilities", tags=["capabilities"])
def capabilities(registry: Registry = Depends(get_registry)) -> dict[str, dict[str, Any]]:
    """Every format's read/write capability declaration (equals ``xtalate capabilities --json``)."""
    return _declarations(registry, _known_format_ids(registry))


@router.get("/capabilities/{format_id}", tags=["capabilities"])
def capabilities_for_format(
    format_id: str, registry: Registry = Depends(get_registry)
) -> dict[str, dict[str, Any]]:
    """One format's declaration as ``{format_id: {...}}`` (matches ``capabilities <id> --json``)."""
    known = _known_format_ids(registry)
    if format_id not in known:
        # FORMAT_NOT_FOUND — the 404 for an unknown ``format_id`` in the Part 6 §2 endpoint table.
        # (Distinct from the 422 UNKNOWN_FORMAT a *conversion* raises when a file cannot be sniffed;
        # here the caller named a format id that simply is not registered.)
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="FORMAT_NOT_FOUND",
            message=f"Unknown format {format_id!r}.",
            details={"known_formats": sorted(known)},
        )
    return _declarations(registry, {format_id})
