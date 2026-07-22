"""``GET /v1/health`` — liveness always, readiness on demand (MASTER_SPEC Part 6).

Liveness (the bare call) proves the process is up and answers immediately with no dependency
touched. Readiness (``?ready=true``) runs every probe registered on ``app.state.readiness_checks``
(:mod:`backend.readiness`) and is green only when all pass; on any failure the response is
``503`` so an orchestrator's readiness probe removes the instance from rotation. In M21 the probe
registry is empty, so readiness is trivially green — the database and object-storage probes join
it in M24 without changing this handler.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Query, Request, Response, status

from backend.config import Settings
from backend.models import HealthResponse, ReadinessCheck
from backend.readiness import ReadinessProbe

router = APIRouter()


def _xtalate_version() -> str:
    try:
        return version("xtalate")
    except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
        return "unknown"


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(
    request: Request,
    response: Response,
    ready: bool = Query(
        default=False,
        description="Run dependency readiness probes; 503 if any fail.",
    ),
) -> HealthResponse:
    settings: Settings = request.app.state.settings
    checks: dict[str, ReadinessCheck] = {}

    if ready:
        probes: dict[str, ReadinessProbe] = request.app.state.readiness_checks
        for name, probe in probes.items():
            checks[name] = await probe()

    degraded = any(not check.ok for check in checks.values())
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="degraded" if degraded else "ok",
        environment=settings.environment,
        version=_xtalate_version(),
        checks=checks,
    )
