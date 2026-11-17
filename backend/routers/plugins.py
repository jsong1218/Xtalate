"""``GET /v1/plugins`` — one inventory of installed parsers, exporters, and analysis plugins.

The service holds **no** plugin knowledge of its own (Part 1 §2): it asks the ``xtalate`` registry
and lists what is installed. A client asking "what can this instance do" gets one answer across all
three plugin kinds — the "future plugin-listing endpoint" Part 7 §6 names, generalized from
analysis alone to every plugin kind so a single call enumerates the whole surface. Format plugins
already have ``/v1/capabilities`` for their per-field declarations; this endpoint is the flat roster
(kind, name, version) that the Analysis tab reads to offer the installed analysis plugins, and that
a human reads to see, at a glance, everything an instance can do.
"""

from __future__ import annotations

import weakref
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from backend.deps import get_registry
from backend.http_cache import etag_response
from xtalate.capabilities import Registry

router = APIRouter()


def _inventory(registry: Registry) -> list[dict[str, Any]]:
    """The flat, sorted roster of every installed plugin (parsers, exporters, analysis)."""
    rows: list[dict[str, Any]] = []
    for parser in registry.parsers():
        rows.append(
            {
                "kind": "parser",
                "name": parser.format_id,
                "version": parser.version,
                "format_name": parser.format_name,
            }
        )
    for exporter in registry.exporters():
        rows.append(
            {
                "kind": "exporter",
                "name": exporter.format_id,
                "version": exporter.version,
                "format_name": exporter.format_name,
            }
        )
    for analysis in registry.analysis_plugins():
        # Analysis plugins carry no format: their namespace is ``name``, and there is no format id.
        rows.append(
            {
                "kind": "analysis",
                "name": analysis.name,
                "version": analysis.version,
                "format_name": None,
            }
        )
    # Deterministic order — the artifact/UI never depends on registration order (D89 spirit).
    rows.sort(key=lambda row: (row["kind"], row["name"]))
    return rows


_Body = dict[str, list[dict[str, Any]]]
_PLUGINS_CACHE: weakref.WeakKeyDictionary[Registry, tuple[tuple[int, ...], _Body]] = (
    weakref.WeakKeyDictionary()
)


def plugins_body(registry: Registry) -> dict[str, list[dict[str, Any]]]:
    """The full ``/v1/plugins`` payload, built once per plugin set. Treat as read-only."""
    token = (
        tuple(id(p) for p in registry.parsers())
        + tuple(id(e) for e in registry.exporters())
        + tuple(id(a) for a in registry.analysis_plugins())
    )
    cached = _PLUGINS_CACHE.get(registry)
    if cached is not None and cached[0] == token:
        return cached[1]
    body: _Body = {"plugins": _inventory(registry)}
    _PLUGINS_CACHE[registry] = (token, body)
    return body


@router.get("/plugins", response_model=dict[str, list[dict[str, Any]]], tags=["plugins"])
def plugins(request: Request, registry: Registry = Depends(get_registry)) -> Response:
    """Every installed plugin's kind, name, and version (format plugins add ``format_name``)."""
    return etag_response(request, plugins_body(registry))
