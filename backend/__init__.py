"""Xtalate Service — the FastAPI presentation layer over the library (MASTER_SPEC Part 6, v0.5).

**Thin by law (Part 1 §2).** This package validates requests, manages jobs and storage, and
delegates *every* scientific decision to ``xtalate`` — the library five versions have hardened.
Nothing here parses a format, computes a loss, or defaults an absent field; it renders the
library's reports verbatim (Part 6 preamble) and enforces the transport rules the spec makes
binding (refusals are HTTP 200, expiry resolves to refusal, never a default).

The dependency direction is one-way and lint-enforced: ``backend`` imports ``xtalate``; nothing
in ``xtalate`` imports ``backend`` (the import-linter contract added in v0.5 M21). A parser bug
fix must never require the service to be installed, so the service ships as the ``service`` extra,
not a core dependency — ``pip install xtalate`` remains the pure library + CLI (Part 9 §1.1).

M21 lands the skeleton: the app factory, environment-only settings, the single error-envelope
path, and the three *stateless* endpoints (``/v1/health``, ``/v1/capabilities``, ``/v1/limits``).
Persistence adapters, the relational model, and the async job machinery arrive in M22–M25.
"""

from __future__ import annotations

from backend.app import create_app

__all__ = ["create_app"]
