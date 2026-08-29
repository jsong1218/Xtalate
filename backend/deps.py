"""FastAPI dependency accessors for the shared, request-independent app state.

The app factory builds the :class:`~backend.config.Settings` and the ``xtalate`` registry **once**
and stashes them on ``app.state``; these thin accessors hand them to route functions via
``Depends``. Reading them through ``Request.app.state`` (not module globals) is what lets a test
build an isolated app with overridden settings — there is no hidden process-wide singleton a route
reaches around the factory to find.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from backend.config import Settings
from xtalate.capabilities import Registry

if TYPE_CHECKING:
    from backend.db import Repository
    from backend.jobs.queue import JobQueue
    from backend.routers.geometry import GeometryCache
    from backend.storage import ObjectStore


def get_settings(request: Request) -> Settings:
    """The app's :class:`Settings` snapshot (built by the factory, shared across requests)."""
    settings: Settings = request.app.state.settings
    return settings


def get_repository(request: Request) -> Repository:
    """The app's :class:`~backend.db.Repository` — the one door into the relational store."""
    repository: Repository = request.app.state.repository
    return repository


def get_object_store(request: Request) -> ObjectStore:
    """The app's :class:`~backend.storage.ObjectStore` — uploaded input + converted output bytes."""
    object_store: ObjectStore = request.app.state.object_store
    return object_store


def get_job_queue(request: Request) -> JobQueue:
    """The app's :class:`~backend.jobs.queue.JobQueue` — inline (Tier 0) or RQ (Tier 1)."""
    job_queue: JobQueue = request.app.state.job_queue
    return job_queue


def get_geometry_cache(request: Request) -> GeometryCache:
    """The app's bounded geometry cache (v1.6 M59-S1, D232) — shared across requests.

    The parsed-geometry LRU lives on ``app.state`` beside the repository/store the publishers
    build, so the common viewer/scrub traffic rides it while memory stays flat. Reading it through
    ``Request.app.state`` (never a module global) keeps the test-isolation guarantee: a test builds
    an isolated app with its own bounded cache.
    """
    geometry_cache: GeometryCache = request.app.state.geometry_cache
    return geometry_cache


def get_registry(request: Request) -> Registry:
    """The app's ``xtalate`` :class:`Registry` — built-ins + any entry-point plugins.

    Built once at startup and shared: capability queries are read-only, so the same instance
    serves every request. This is the *only* door the service has into the library's format
    knowledge — the API holds none of its own (Part 1 §2).
    """
    registry: Registry = request.app.state.registry
    return registry
