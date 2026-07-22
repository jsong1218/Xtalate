"""FastAPI dependency accessors for the shared, request-independent app state.

The app factory builds the :class:`~backend.config.Settings` and the ``xtalate`` registry **once**
and stashes them on ``app.state``; these thin accessors hand them to route functions via
``Depends``. Reading them through ``Request.app.state`` (not module globals) is what lets a test
build an isolated app with overridden settings — there is no hidden process-wide singleton a route
reaches around the factory to find.
"""

from __future__ import annotations

from fastapi import Request

from backend.config import Settings
from xtalate.capabilities import Registry


def get_settings(request: Request) -> Settings:
    """The app's :class:`Settings` snapshot (built by the factory, shared across requests)."""
    settings: Settings = request.app.state.settings
    return settings


def get_registry(request: Request) -> Registry:
    """The app's ``xtalate`` :class:`Registry` — built-ins + any entry-point plugins.

    Built once at startup and shared: capability queries are read-only, so the same instance
    serves every request. This is the *only* door the service has into the library's format
    knowledge — the API holds none of its own (Part 1 §2).
    """
    registry: Registry = request.app.state.registry
    return registry
