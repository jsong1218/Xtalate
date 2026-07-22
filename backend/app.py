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
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from backend.config import Settings, get_settings
from backend.errors import install_error_handlers
from backend.readiness import ReadinessProbe
from backend.routers import capabilities, health, limits
from xtalate.registry import default_registry

#: Accepted shape for a client-supplied ``X-Request-ID`` (ASCII id chars, bounded length). Anything
#: else is replaced with a fresh id so a caller cannot inject newlines/control chars into logs.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id_from(header_value: str | None) -> str:
    """Honour a well-formed client ``X-Request-ID``; otherwise mint one (log-injection safe)."""
    if header_value and _REQUEST_ID_RE.match(header_value):
        return header_value
    return uuid.uuid4().hex


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and wire the service app. Pass ``settings`` to override the environment (tests)."""
    settings = settings or get_settings()

    app = FastAPI(
        title="Xtalate Service",
        summary="Loss-aware chemistry file conversion over HTTP.",
        description=(
            "The trusted translation layer between computational-chemistry file formats, "
            "exposed as a REST API. Reports embed verbatim; refusals are HTTP 200 completed jobs."
        ),
        version=_api_version(),
    )

    app.state.settings = settings
    # Built once and shared: capability/format knowledge is read-only, and this is the service's
    # only door into the library (Part 1 §2). Includes any installed entry-point plugins.
    app.state.registry = default_registry()
    # Populated in M24 with the database and object-storage probes; empty now (readiness is green).
    readiness_checks: dict[str, ReadinessProbe] = {}
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

    return app


def _api_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("xtalate")
    except PackageNotFoundError:  # pragma: no cover - non-installed tree only
        return "0.0.0"
