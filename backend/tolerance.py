"""Resolve a request's ``tolerance_profile`` — a named profile or a custom table (Part 5 §4.4).

Two endpoints accept the same union: ``POST /v1/convert`` (``options.tolerance_profile``) and
``POST /v1/validate``. Either may name one of the built-in profiles (``default``/``strict``/
``loose``) or carry a whole custom tolerance table as an object. Both forms are resolved here, once,
so the convert and re-validate workers cannot disagree about what a request meant — the drift this
module exists to prevent was real: the re-validate worker handled the table form while the convert
worker passed it straight to :meth:`ToleranceProfile.named`, which raises on a mapping, so a
documented request shape ended as a ``500 INTERNAL_ERROR``.

The library owns every rule about what a valid table *is* (§4.4: only ``name``/``quantities`` are
configurable, discrete checks admit no tolerance, ``warn`` may not exceed ``fail``). This module
adds none of its own — it dispatches on the wire shape and lets the library's own actionable
``ValueError`` messages through. :func:`validate_tolerance_profile` is the request-time hook the
models use so a bad profile is a ``400 MALFORMED_REQUEST`` on submit, before a job exists, rather
than a failed job the caller has to poll for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xtalate.validation import ToleranceProfile


def resolve_tolerance_profile(value: str | dict[str, Any]) -> ToleranceProfile:
    """The :class:`ToleranceProfile` a request's ``tolerance_profile`` names or describes.

    A string selects a built-in profile; a mapping is a custom §4.4 tolerance table. Raises
    :class:`ValueError` (the library's own message) for an unknown name or a malformed table.
    """
    from xtalate.validation import ToleranceProfile

    if isinstance(value, str):
        return ToleranceProfile.named(value)
    return ToleranceProfile.from_mapping("custom", value)


def validate_tolerance_profile(value: str | dict[str, Any]) -> str | dict[str, Any]:
    """Validate a wire ``tolerance_profile`` and return it **unchanged** (a pydantic validator).

    The value is returned as it arrived, not as the resolved profile: the request is persisted on
    the job row as JSON and replayed by the worker, so what the caller sent is what the record
    keeps. Resolution happens again in the worker, from that stored value, via
    :func:`resolve_tolerance_profile`.
    """
    resolve_tolerance_profile(value)
    return value
