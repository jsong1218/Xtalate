"""The committed OpenAPI schema must not drift silently from the running app (MASTER_SPEC M25).

The v1.0 contract freeze diffs the then-current ``/v1`` schema against a checked-in baseline; that
baseline (``docs/openapi.json``) only means something if it is kept in lockstep with the code. This
test regenerates the schema and asserts byte-equality with the committed file, so any route, field,
or status-code change that is not accompanied by ``python -m backend.openapi`` fails the gate.

The schema is a pure function of the source (``info.version`` is pinned to ``xtalate.__version__``,
keys are sorted), so this comparison is deterministic across differently-stale editable installs.
"""

from __future__ import annotations

from backend.config import Settings
from backend.openapi import ARTIFACT_PATH, build_openapi_document, serialize


def test_committed_openapi_matches_the_app(settings: Settings) -> None:
    """``docs/openapi.json`` equals a freshly generated schema — regenerate it if this fails."""
    committed = ARTIFACT_PATH.read_text(encoding="utf-8")
    regenerated = serialize(build_openapi_document(settings))
    assert committed == regenerated, (
        "The committed OpenAPI artifact is stale. Run `python -m backend.openapi` and commit "
        "docs/openapi.json alongside the API change that caused this."
    )


def test_openapi_covers_the_whole_v1_surface(settings: Settings) -> None:
    """A sanity floor independent of the byte diff: every mounted ``/v1`` operation is present."""
    document = build_openapi_document(settings)
    paths = document["paths"]
    # Spot-check the load-bearing routes across every router group, so a dropped mount is caught
    # even in the unlikely event the artifact were regenerated against a broken app.
    for expected in (
        "/v1/health",
        "/v1/upload",
        "/v1/inspect",
        "/v1/convert",
        "/v1/validate",
        "/v1/jobs/{job_id}",
        "/v1/jobs/{job_id}/recovery",
        "/v1/jobs/{job_id}/cancel",
        "/v1/conversions/{conversion_id}",
        "/v1/download/{conversion_id}",
        "/v1/history",
        "/v1/limits",
        "/v1/capabilities",
    ):
        assert expected in paths, f"{expected} missing from the OpenAPI schema"
    assert document["info"]["version"] == __import__("xtalate").__version__
