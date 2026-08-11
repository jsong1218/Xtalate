"""The error-code reference must cover every code the envelope can emit (M34-S1).

Since v0.5 every non-2xx response carries a ``documentation_url`` of the form
``{docs_base_url}#{code.lower()}`` (Part 6 §6), and the Web UI renders it as a clickable link
(``ErrorEnvelope.tsx``). M34 makes those links *resolve*: one reference section per code, anchored
at ``code.lower()``. This module is the authority side of that promise —
:data:`backend.error_codes.ERROR_CODES` — and it must not drift from the codes the backend actually
raises, or a real ``documentation_url`` would point at an anchor that does not exist.

Two guards, mirroring the OpenAPI and vocabulary drift tests:

* **Drift** — ``docs/error_codes.json`` equals a fresh export, byte for byte, so the frontend
  link-check (which reads that artifact) can never be checking a stale set.
* **Completeness** — the registry equals the set of codes the source can actually emit, scanned from
  the ``code="…"`` raise sites plus the two non-literal seams (the framework status map and the
  worker's ``_failure_body``). A new code with no registry entry fails here; a phantom entry the
  backend never raises fails here too.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.error_codes import ARTIFACT_PATH, ERROR_CODES, build_error_codes, serialize
from backend.errors import _HTTP_STATUS_CODES

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent / "backend"

#: Codes the backend emits *without* a ``code="…"`` keyword literal, so the source scan below cannot
#: see them. Each is justified against its single raise site; adding a new one of these is the one
#: case that also needs a line here (the documented seam for dynamically-chosen codes).
#:   - ``HTTP_ERROR``     — the ``_http_exception_handler`` fallback for an unmapped Starlette code.
#:   - ``PARSE_ERROR``    — ``jobs/runner.py`` ``_failure_body`` (positional, not ``code=``).
#:   - ``VALIDATION_UNAVAILABLE`` — ditto, the revalidate-failure branch of ``_failure_body``.
#:   - ``FRAME_LIMIT_EXCEEDED`` — ditto, the frame-cap branch of ``_failure_body`` (M39-S3, F1).
_DYNAMIC_CODES = {"HTTP_ERROR", "PARSE_ERROR", "VALIDATION_UNAVAILABLE", "FRAME_LIMIT_EXCEEDED"}

_CODE_LITERAL = re.compile(r'code="([A-Z][A-Z_]*)"')


def _scan_emitted_codes() -> set[str]:
    """Every code the backend can put on an error envelope, gathered from the source itself."""
    literals: set[str] = set()
    for path in _BACKEND_ROOT.rglob("*.py"):
        literals |= set(_CODE_LITERAL.findall(path.read_text(encoding="utf-8")))
    # The two non-``code="…"`` seams: the framework status→code map, and the dynamic worker codes.
    return literals | set(_HTTP_STATUS_CODES.values()) | _DYNAMIC_CODES


def test_committed_error_codes_matches_the_registry() -> None:
    """``docs/error_codes.json`` equals a freshly generated export — regenerate it if this fails."""
    committed = ARTIFACT_PATH.read_text(encoding="utf-8")
    regenerated = serialize(build_error_codes())
    assert committed == regenerated, (
        "The committed error-code artifact is stale. Run `python -m backend.error_codes` and "
        "commit docs/error_codes.json — then add the matching section in docs/errors.md."
    )


def test_registry_covers_exactly_the_emitted_codes() -> None:
    """The registry is neither missing an emittable code nor carrying one that is never raised."""
    registry = {spec.code for spec in ERROR_CODES}
    emitted = _scan_emitted_codes()

    missing = emitted - registry
    assert not missing, (
        f"These codes are raised by the backend but absent from ERROR_CODES (so their "
        f"documentation_url would not resolve): {sorted(missing)}"
    )
    phantom = registry - emitted
    assert not phantom, (
        f"These codes are in ERROR_CODES but never raised by the backend (remove them or the scan "
        f"missed a new seam): {sorted(phantom)}"
    )


def test_every_code_has_a_nonempty_summary() -> None:
    """A sanity floor: the reference is only useful if each code carries a one-line explanation."""
    assert ERROR_CODES, "ERROR_CODES must not be empty"
    for spec in ERROR_CODES:
        assert spec.summary.strip(), f"{spec.code} needs a one-line summary"
