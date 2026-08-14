"""``GET /v1/limits`` — the operational constraints, config-driven (MASTER_SPEC Part 6 §5).

A client reads the rules before it hits them. Every value comes straight from
:class:`~backend.config.Settings` (the environment), so a deployment tunes limits without a code
change and the advertised number is the same object the enforcing surfaces (M23/M24) read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.config import Settings
from backend.deps import get_settings
from backend.models import LimitsResponse

router = APIRouter()


@router.get("/limits", response_model=LimitsResponse, tags=["limits"])
def limits(settings: Settings = Depends(get_settings)) -> LimitsResponse:
    # The report window is advertised in whichever unit is actually active — hours when a sub-day
    # override is set (the demo), else days — so exactly one field is non-null (both null =
    # indefinite). A client renders the non-null one; the number it shows is the window the reads
    # and the sweep enforce.
    report_hours = settings.report_retention_hours
    report_days = None if report_hours is not None else settings.report_retention_days
    return LimitsResponse(
        max_upload_bytes=settings.max_upload_bytes,
        max_frames=settings.max_frames,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        upload_retention_hours=settings.upload_retention_hours,
        output_retention_hours=settings.output_retention_hours,
        awaiting_recovery_ttl_minutes=settings.awaiting_recovery_ttl_minutes,
        report_retention_days=report_days,
        report_retention_hours=report_hours,
    )
