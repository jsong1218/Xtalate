"""Strong-ETag + Cache-Control + 304 for the registry/settings-derived, unauthenticated read
endpoints (capabilities, plugins, limits — QoL Q5).

The ETag is a hash of the **serialized body**, so it is correct however the router produced that
body: a different registry or different settings yield different bytes and therefore a different
tag, and a stale tag can never match. Errors are never routed through here (an error response is
not cacheable by this contract).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder


def _serialize(body: Any) -> bytes:
    if isinstance(body, bytes):
        return body
    # Sorted keys + compact separators: byte-stable for equal content.
    return json.dumps(
        jsonable_encoder(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _etag_of(payload: bytes) -> str:
    return '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    # Weak comparison (RFC 9110 8.8.3.2): list members compared with any W/ prefix removed.
    return any(candidate.strip().removeprefix("W/") == wanted for candidate in header.split(","))


def etag_response(request: Request, body: Any, *, max_age: int = 300) -> Response:
    """The 200 (``ETag`` + ``Cache-Control``) or, for a matching ``If-None-Match``, the 304."""
    payload = _serialize(body)
    etag = _etag_of(payload)
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)
