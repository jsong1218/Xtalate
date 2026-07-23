"""The FastAPI application factory (MASTER_SPEC Part 6; Part 9 §2).

:func:`create_app` builds a fully wired app: it reads settings once, builds the ``xtalate``
registry once, installs the single error-envelope path *before* any router, attaches the
request-id middleware, and mounts the ``/v1`` routers. A factory (not a module-level ``app``
global) is what lets a test spin up an isolated app with overridden :class:`Settings` — there is
no hidden singleton. The ASGI entry point for servers is :mod:`backend.asgi`, which calls this once.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, Response
from sqlalchemy import Engine

from backend.config import Settings, get_settings
from backend.db import Repository, build_engine, build_sessionmaker
from backend.errors import install_error_handlers
from backend.jobs.queue import create_job_queue
from backend.jobs.runner import execute_job
from backend.readiness import ReadinessProbe, database_probe, object_store_probe
from backend.routers import capabilities, downloads, health, jobs, limits, uploads
from backend.storage import create_object_store
from xtalate.registry import default_registry

#: Accepted shape for a client-supplied ``X-Request-ID`` (ASCII id chars, bounded length). Anything
#: else is replaced with a fresh id so a caller cannot inject newlines/control chars into logs.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id_from(header_value: str | None) -> str:
    """Honour a well-formed client ``X-Request-ID``; otherwise mint one (log-injection safe)."""
    if header_value and _REQUEST_ID_RE.match(header_value):
        return header_value
    return uuid.uuid4().hex


def _lifespan(engine: Engine) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """A lifespan that disposes the engine's connection pool on shutdown (no leaked connections)."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and wire the service app. Pass ``settings`` to override the environment (tests)."""
    settings = settings or get_settings()

    # The persistence adapters, built once from settings and shared. The engine is lazy (no
    # connection until a probe or a request opens one), so a stateless-endpoint request never
    # touches the database; the object store's root is created eagerly by its constructor. Both
    # backends are chosen by configuration alone (Tier 0 SQLite + filesystem, Tier 1 Postgres +
    # MinIO) — Part 9 §1.1. M22 reaches for ``app.state.repository`` to run jobs. Built before the
    # app so the lifespan can dispose the engine's pool on shutdown.
    engine = build_engine(settings)
    object_store = create_object_store(settings)

    app = FastAPI(
        title="Xtalate Service",
        summary="Loss-aware chemistry file conversion over HTTP.",
        description=(
            "The trusted translation layer between computational-chemistry file formats, "
            "exposed as a REST API. Reports embed verbatim; refusals are HTTP 200 completed jobs."
        ),
        version=_api_version(),
        lifespan=_lifespan(engine),
    )

    app.state.settings = settings
    # Built once and shared: capability/format knowledge is read-only, and this is the service's
    # only door into the library (Part 1 §2). Includes any installed entry-point plugins.
    registry = default_registry()
    repository = Repository(build_sessionmaker(engine))
    app.state.registry = registry
    app.state.engine = engine
    app.state.repository = repository
    app.state.object_store = object_store

    # The job queue (M22): inline (Tier 0, runs jobs here) or RQ (Tier 1, hands them to the worker).
    # The inline backend's runner closes over the app's shared adapters, so a job it runs in-process
    # uses the same repository/store/registry as the request that submitted it. The RQ backend
    # ignores this closure — its worker rebuilds the adapters from the environment (Part 9 §2).
    def _run_job(job_id: str) -> None:
        execute_job(
            job_id,
            repository=repository,
            object_store=object_store,
            registry=registry,
            settings=settings,
        )

    app.state.job_queue = create_job_queue(settings, runner=_run_job)

    # The readiness probes for those two dependencies, so ``/v1/health?ready=true`` is green under
    # ``docker compose up`` (M21 done-means). Registered here, run by the health endpoint — the seam
    # that lets M24 add further probes (e.g. the queue) without touching that handler.
    readiness_checks: dict[str, ReadinessProbe] = {
        "database": database_probe(engine),
        "object_store": object_store_probe(object_store, settings.object_store_backend),
    }
    app.state.readiness_checks = readiness_checks

    install_error_handlers(app)

    @app.middleware("http")
    async def _request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id_from(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router, prefix="/v1")
    app.include_router(capabilities.router, prefix="/v1")
    app.include_router(limits.router, prefix="/v1")
    app.include_router(uploads.router, prefix="/v1")
    app.include_router(jobs.router, prefix="/v1")
    app.include_router(downloads.router, prefix="/v1")

    return app


def _api_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("xtalate")
    except PackageNotFoundError:  # pragma: no cover - non-installed tree only
        return "0.0.0"
