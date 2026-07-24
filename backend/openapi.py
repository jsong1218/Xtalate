"""Generate the committed OpenAPI artifact for the ``/v1`` service (MASTER_SPEC Part 8 §1.1).

The v1.0 freeze will diff the then-current schema against a committed baseline to prove the REST
contract did not drift silently (Part 10 §6 item; the "start the paper trail now" deliverable of
M25). So the schema is emitted **deterministically** to a checked-in file, and a test regenerates
and diffs it — a route added, a field renamed, or a status code changed fails CI until the artifact
is regenerated on purpose.

Two determinism decisions make the diff meaningful rather than noisy:

* **``info.version`` is pinned to** :data:`xtalate.__version__` **(the source of truth), not the
  installed distribution metadata.** ``FastAPI.openapi()`` reads the version from the running app,
  which reads ``importlib.metadata.version("xtalate")`` — and an editable checkout's metadata lags
  the source tree until reinstalled (a known local footgun). Normalizing here means the artifact is
  a function of the source, so two machines with differently-stale editable installs produce byte-
  identical output.
* **Keys are sorted and indentation is fixed.** ``json.dumps(..., sort_keys=True, indent=2)`` makes
  the output invariant to dict-insertion order, so a FastAPI upgrade that reorders a schema's keys
  without changing its meaning does not spuriously fail the drift test.

Run ``python -m backend.openapi`` to regenerate :data:`ARTIFACT_PATH` after an intended API change.
Nothing here contains scientific logic; it introspects the assembled app (Part 6 preamble).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xtalate
from backend.app import create_app
from backend.config import Settings

#: The committed baseline the v1.0 freeze diffs against. Repo-relative; kept beside the human docs.
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def build_openapi_document(settings: Settings | None = None) -> dict[str, Any]:
    """Return the ``/v1`` OpenAPI schema as a plain dict, with ``info.version`` source-pinned.

    Builds a throwaway app (the engine is lazy and the filesystem object store only makes its root
    dir, so this needs no running database or MinIO) and asks FastAPI for its schema. The only edit
    is normalizing the version — see the module docstring for why.
    """
    app = create_app(settings)
    document = app.openapi()
    document["info"]["version"] = xtalate.__version__
    return document


def serialize(document: dict[str, Any]) -> str:
    """Canonical text form of the schema: sorted keys, 2-space indent, one trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_artifact(path: Path = ARTIFACT_PATH, settings: Settings | None = None) -> Path:
    """Regenerate the committed artifact at ``path`` and return it."""
    path.write_text(serialize(build_openapi_document(settings)), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised via write_artifact() in tests
    written = write_artifact()
    print(f"Wrote {written}")
