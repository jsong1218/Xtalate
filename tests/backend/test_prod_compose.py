"""``docker-compose.prod.yml`` is a hardened, secret-free production stack (M34-S2).

Self-hosting is the primary supported deployment (MASTER_SPEC Part 9 §5.4), and this is the file a
self-hoster runs. Two properties matter enough to guard in CI — this is the slice where a committed
secret first becomes possible (CLAUDE.md "Never commit secrets"):

* **No secret is committed.** Every credential-shaped environment value is an unresolved ``${...}``
  reference, never a literal — real values live only in an untracked ``.env``.
* **It is production-shaped, not the dev stack.** Both entrypoints of the one image are present (the
  ``backend`` API and the ``worker``), and no service bind-mounts repository source — a dev mount
  would ship the host tree into a run labelled "production".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

_PROD_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"

#: Environment keys whose *value* would be a credential if written as a literal. ``SECRET`` covers
#: ``SECRET_KEY`` and ``API_KEY`` covers ``API_KEYS``, so a short alternation is exhaustive.
_SECRET_HINT = re.compile(r"(PASSWORD|SECRET|ACCESS_KEY|API_KEY)", re.IGNORECASE)


def _load() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(_PROD_COMPOSE.read_text(encoding="utf-8")))


def _services() -> dict[str, Any]:
    return cast("dict[str, Any]", _load()["services"])


def _env_items(service: dict[str, Any]) -> list[tuple[str, Any]]:
    """Normalise a service's ``environment`` (dict or ``KEY=value`` list) to (key, value) pairs."""
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return list(env.items())
    pairs: list[tuple[str, Any]] = []
    for entry in env:
        key, _, value = str(entry).partition("=")
        pairs.append((key, value))
    return pairs


def test_defines_both_entrypoints() -> None:
    """The API and the worker — the one image's two entrypoints (Part 9 §2) — are both present."""
    services = _services()
    assert "backend" in services, "prod compose must define the API service `backend`"
    assert "worker" in services, "prod compose must define the `worker` service"


def test_no_source_bind_mounts() -> None:
    """No service bind-mounts host repository source; production has no dev mounts."""
    for name, service in _services().items():
        for volume in service.get("volumes") or []:
            if isinstance(volume, str):
                source = volume.split(":", 1)[0]
            else:
                source = volume.get("source", "")
            assert not str(source).startswith("."), (
                f"service {name!r} bind-mounts host path {source!r}; prod compose has no dev mounts"
            )


def test_no_committed_secrets() -> None:
    """Credential-shaped env values are env references (``${...}``), never baked-in literals."""
    for name, service in _services().items():
        for key, value in _env_items(service):
            if value is None or not _SECRET_HINT.search(str(key)):
                continue
            text = str(value)
            assert text == "" or "${" in text, (
                f"{name}.{key} looks like a committed secret: {text!r}. Reference an env var "
                f"(e.g. ${{{key}:?set in your untracked .env}}) instead."
            )
