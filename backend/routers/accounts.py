"""``/v1/auth/*`` and ``/v1/keys*`` — the account surface, disabled in v0.5 (Part 6 §4; M24).

Accounts, sessions, and per-user API keys are hosted-instance work, deferred with the hosted
instance itself. But the endpoint *paths* are part of the published contract, so a client that hits
them on a self-hosted anonymous instance must get the spec's honest answer — ``404 NOT_ENABLED`` —
rather than a bare framework 404 that reads as "wrong URL". This router reserves those paths and
answers every method on them with that one code, so no dormant account machinery ships in v0.5 while
the surface stays truthful about *why* it is absent.

Deliberately outside the request-policy dependency: these must answer ``NOT_ENABLED`` regardless of
whether a static API key is configured — a self-hoster asking about accounts should learn accounts
are off, not be challenged for a key first.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.errors import ApiError

router = APIRouter()

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _not_enabled(surface: str) -> ApiError:
    return ApiError(
        status_code=404,  # literal, not status.HTTP_404_* (kept uniform with the other routers)
        code="NOT_ENABLED",
        message=(
            f"{surface} is not enabled on this instance. Accounts and per-user API keys are "
            "hosted-instance features; this is an anonymous self-hosted deployment (Part 6 §4)."
        ),
    )


@router.api_route("/auth/{rest:path}", methods=_METHODS, include_in_schema=False)
def auth_not_enabled(rest: str) -> None:
    raise _not_enabled("The account (auth) surface")


@router.api_route("/keys", methods=_METHODS, include_in_schema=False)
def keys_not_enabled() -> None:
    raise _not_enabled("The API-key surface")


@router.api_route("/keys/{rest:path}", methods=_METHODS, include_in_schema=False)
def key_item_not_enabled(rest: str) -> None:
    raise _not_enabled("The API-key surface")
