"""The single exception-to-response path (MASTER_SPEC Part 6 §6).

Every non-2xx response — a deliberately raised :class:`ApiError`, a request-validation failure,
an unmatched route, or an unexpected crash — is rendered through one :class:`ErrorEnvelope`. This
is implemented once, here, and installed on the app before any router, because retrofitting an
envelope under thirty endpoints is precisely the rewrite M21 exists to avoid (Part 6 §6, the plan's
"envelope-first rule"). Adding an endpoint therefore costs zero error-handling code: raise an
:class:`ApiError` (or let an exception escape) and the shape is guaranteed.

**A refusal is not an error.** A conversion the engine declines is a *completed* job with
``ConversionReport.status == "refused"`` at HTTP 200 (Part 6 preamble) — it never reaches this
module. This path is for transport failures only: bad input, missing resources, server faults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.models import ErrorBody, ErrorEnvelope

if TYPE_CHECKING:
    from backend.config import Settings


class ApiError(Exception):
    """A transport failure to be rendered as the error envelope.

    Handlers and routers raise this instead of returning ad-hoc responses; the registered handler
    turns it into an :class:`ErrorEnvelope` at ``status_code``. ``code`` is the stable machine
    string a client branches on; ``message`` is human-readable; ``details`` carries structured
    specifics (allowed values, the offending field) a client can act on without scraping prose.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, object] = details or {}


def _request_id(request: Request) -> str:
    """The current request's id, set by the request-id middleware (falls back to ``"unknown"``)."""
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else "unknown"


def _documentation_url(request: Request, code: str) -> str:
    """Deep link to the reference entry for ``code``, built from ``docs_base_url`` (Part 6 §6)."""
    settings: Settings = request.app.state.settings
    return f"{settings.docs_base_url}#{code.lower()}"


def _envelope(request: Request, status_code: int, error: ApiError) -> JSONResponse:
    """Render an :class:`ApiError` as the envelope, echoing the request id in the header too."""
    body = ErrorEnvelope(
        error=ErrorBody(
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=_request_id(request),
            documentation_url=_documentation_url(request, error.code),
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": _request_id(request)},
    )


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _envelope(request, exc.status_code, exc)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI request-validation failures → a ``400 INVALID_REQUEST`` envelope.

    The raw pydantic error list is surfaced under ``details.errors`` so a client sees exactly which
    field failed and why — without the default FastAPI shape, which is *not* our envelope.
    """
    api = ApiError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="INVALID_REQUEST",
        message="The request could not be validated.",
        details={"errors": exc.errors()},
    )
    return _envelope(request, api.status_code, api)


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Framework/Starlette HTTP errors (404 for an unmatched route, 405, …) → the envelope.

    Without this, an unknown path would return Starlette's default ``{"detail": ...}`` body and
    break the one-shape contract. The status code maps to a stable ``code`` a client can branch on.
    """
    code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    api = ApiError(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail) if exc.detail else code.replace("_", " ").title(),
    )
    return _envelope(request, exc.status_code, api)


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """The backstop: any exception not otherwise handled → ``500 INTERNAL_ERROR``.

    The exception text is deliberately *not* leaked to the client (it may quote file content, which
    logs must never carry — Part 9 §6.1); the ``request_id`` is the bridge to the server-side log
    where the detail lives.
    """
    api = ApiError(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred. Quote the request_id when reporting it.",
    )
    return _envelope(request, api.status_code, api)


#: Stable machine ``code`` for the framework HTTP statuses the envelope maps.
_HTTP_STATUS_CODES: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    422: "INVALID_REQUEST",  # literal, not status.HTTP_422_* (the constant is deprecated upstream)
}


def install_error_handlers(app: FastAPI) -> None:
    """Register the four handlers that make the envelope the *only* non-2xx shape.

    Order of specificity, not registration, decides which handler runs; all four are installed so
    no path can escape the envelope. Called by the app factory before any router is included.
    """
    app.add_exception_handler(ApiError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
