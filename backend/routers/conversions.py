"""``GET /v1/conversions/{id}`` and ``GET /v1/history`` — the durable records surface (M24 slice 3).

A conversion **record** outlives the bytes it produced (reports-outlive-bytes): long after the
output has been swept by its lifecycle rule, the record still serves both reports verbatim and tells
the client — via ``download.available`` — that the bytes themselves are gone. So these two endpoints
read *only* persisted rows; they never touch the source or output bytes to answer.

* ``GET /v1/conversions/{id}`` returns a :class:`~backend.models.ConversionRecordResponse`: the
  Conversion and Validation reports embedded verbatim, plus a :class:`~backend.models.DownloadInfo`
  computed from the record's own columns (``404 CONVERSION_NOT_FOUND`` when the record is unknown or
  has passed report retention).
* ``GET /v1/history`` returns a keyset-paginated page of :class:`~backend.models.HistoryItem`
  summaries — the source/target formats, the two statuses, and the ``summary_counts`` chips counted
  from each conversion report — newest first, with an opaque ``next_cursor``.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, status

from backend.db import Repository
from backend.deps import get_object_store, get_repository
from backend.errors import ApiError
from backend.models import (
    ConversionRecordResponse,
    HistoryItem,
    HistoryResponse,
)
from backend.records import build_download_info
from backend.storage import ObjectStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from backend.db.models import Conversion, Report

router = APIRouter()

#: Default / maximum ``GET /v1/history`` page size. History pagination richness is the M24 cut line,
#: so a plain keyset page with a bounded size is deliberate — not offset math, not filtering.
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


@router.get(
    "/conversions/{conversion_id}",
    response_model=ConversionRecordResponse,
    tags=["conversions"],
)
def get_conversion_record(
    conversion_id: str,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> ConversionRecordResponse:
    """The durable record for one conversion — both reports verbatim, byte availability computed."""
    conversion = repository.get_conversion(conversion_id)
    if conversion is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSION_NOT_FOUND",
            message=f"No conversion {conversion_id!r}.",
        )

    reports = repository.get_reports_for_conversion(conversion_id)
    conversion_report = _first(reports, "conversion")
    validation_report = _first(reports, "validation")
    body: dict[str, Any] = conversion_report.body if conversion_report is not None else {}

    return ConversionRecordResponse(
        conversion_id=conversion.conversion_id,
        created_at=_iso(conversion.created_at),
        source=_source_of(body, conversion.source_format),
        target=_target_of(body, conversion.target_format),
        conversion_report=body,
        validation_report=validation_report.body if validation_report is not None else None,
        download=build_download_info(conversion, repository, object_store),
    )


@router.get("/history", response_model=HistoryResponse, tags=["conversions"])
def get_history(
    limit: int = Query(
        default=_DEFAULT_PAGE_SIZE,
        ge=1,
        le=_MAX_PAGE_SIZE,
        description="Page size (newest first); capped at 100.",
    ),
    cursor: str | None = Query(
        default=None,
        description="Opaque next-page cursor from a previous response's next_cursor.",
    ),
    repository: Repository = Depends(get_repository),
) -> HistoryResponse:
    """A page of conversion summaries, newest first (Part 6 §4.4).

    Fetches one row beyond the page to decide whether a ``next_cursor`` is owed, then projects each
    conversion to a :class:`HistoryItem` — the source/target endpoints and ``summary_counts`` from
    its conversion report (fetched for the whole page in one query), and ``file_id`` only for the
    conversions whose source upload is still live (also one query).
    """
    before = _decode_cursor(cursor) if cursor is not None else None
    rows = repository.list_conversions(limit=limit + 1, before=before)
    page = list(rows[:limit])
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit and page else None

    reports = repository.get_conversion_reports([c.conversion_id for c in page])
    live_files = repository.live_upload_ids(
        c.source_file_id for c in page if c.source_file_id is not None
    )
    items = [_history_item(c, reports.get(c.conversion_id), live_files) for c in page]
    return HistoryResponse(items=items, next_cursor=next_cursor)


def _history_item(
    conversion: Conversion, report: Report | None, live_files: set[str]
) -> HistoryItem:
    """Project one conversion (+ its conversion report, if present) onto a :class:`HistoryItem`."""
    body: dict[str, Any] = report.body if report is not None else {}
    file_id = (
        conversion.source_file_id
        if conversion.source_file_id is not None and conversion.source_file_id in live_files
        else None
    )
    return HistoryItem(
        conversion_id=conversion.conversion_id,
        created_at=_iso(conversion.created_at),
        source=_source_of(body, conversion.source_format),
        target=_target_of(body, conversion.target_format),
        conversion_status=conversion.conversion_status,
        validation_status=conversion.validation_status,
        summary_counts=_summary_counts(body),
        file_id=file_id,
    )


def _summary_counts(report_body: dict[str, Any]) -> dict[str, int]:
    """The ``{preserved, removed, assumptions, warnings}`` chip counts (Part 6 §4.4, ``07 §4``)."""
    return {
        "preserved": len(report_body.get("preserved") or []),
        "removed": len(report_body.get("removed") or []),
        "assumptions": len(report_body.get("assumptions") or []),
        "warnings": len(report_body.get("warnings") or []),
    }


def _source_of(report_body: dict[str, Any], fallback_format_id: str | None) -> dict[str, Any]:
    """The source endpoint ``{format_id, filename}`` — from the report's ``source`` minus hashes."""
    return _endpoint(report_body.get("source"), fallback_format_id)


def _target_of(report_body: dict[str, Any], fallback_format_id: str | None) -> dict[str, Any]:
    """The target endpoint ``{format_id, filename}`` — from the report's ``target``."""
    return _endpoint(report_body.get("target"), fallback_format_id)


def _endpoint(raw: object, fallback_format_id: str | None) -> dict[str, Any]:
    """Reduce a report ``source``/``target`` dict to ``{format_id, filename}`` (no hashes).

    Falls back to the conversion record's denormalized format id when the report is absent — so a
    record whose report did not persist still names its formats rather than serving ``null``.
    """
    if isinstance(raw, dict):
        return {
            "format_id": raw.get("format_id", fallback_format_id),
            "filename": raw.get("filename"),
        }
    return {"format_id": fallback_format_id, "filename": None}


def _first(reports: Sequence[Report], kind: str) -> Report | None:
    return next((r for r in reports if r.kind == kind), None)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _encode_cursor(conversion: Conversion) -> str:
    """Encode a conversion's ``(created_at, conversion_id)`` keyset position as an opaque cursor."""
    raw = f"{conversion.created_at.isoformat()}|{conversion.conversion_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor back to its ``(created_at, conversion_id)`` position.

    A malformed cursor is a client error, not a server one: ``422 INVALID_CURSOR`` rather than a
    ``500`` from a decode fault — a client that hand-edits the opaque token learns it is invalid.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_str, conversion_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(created_str), conversion_id
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ApiError(
            status_code=422,  # literal, not status.HTTP_422_* (deprecated upstream; see errors.py)
            code="INVALID_CURSOR",
            message="The pagination cursor is malformed.",
        ) from exc
