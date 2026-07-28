"""Emit the committed UI vocabulary artifact (MASTER_SPEC Part 7 §3.3; v0.6 M26).

The frontend's plain-language mapping table turns machine vocabulary — every recovery *scenario
code* the engine can raise and every canonical *field path* the Discovery inventory can render —
into plain labels a non-expert can act on, with the machine code always one disclosure away
(Part 7 §3.3). That table only stays honest if it covers the whole vocabulary; the plan's
mapping-coverage lint (Part 8 §1.1 frontend row) is what enforces it, and it must read **the same
registry the backend is built from** so a future plugin scenario or a new schema field surfaces as
a lint failure, not a raw code on screen.

The frontend is TypeScript and cannot import Python, so this module exports those two registries —
:data:`~xtalate.recovery.scenarios.SCENARIO_HAZARD` and the fixed canonical-path list of
:mod:`xtalate.schema.presence` — to a deterministic, checked-in JSON file the Vitest lint reads. A
drift test regenerates and diffs it (exactly as ``backend.openapi`` does for the REST contract), so
the artifact cannot silently fall behind the engine.

Determinism mirrors :mod:`backend.openapi`: ``json.dumps(..., sort_keys=True, indent=2)`` and one
trailing newline, so two machines produce byte-identical output. Nothing here contains scientific
logic; it reads registries the engine already exposes.

Run ``python -m backend.vocabulary`` to regenerate :data:`ARTIFACT_PATH` after the engine's scenario
catalog or the canonical schema's field set changes on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xtalate.conversion.preflight import GENERIC_REQUIRED_FIELD_SCENARIO
from xtalate.recovery.scenarios import SCENARIO_HAZARD
from xtalate.schema.presence import CUSTOM_PATH_CATEGORIES, FIXED_CANONICAL_PATHS

#: The committed vocabulary the frontend mapping-coverage lint reads. Kept beside the human docs and
#: ``openapi.json`` — the two machine-readable contracts the UI generates/checks itself against.
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "docs" / "vocabulary.json"


def build_vocabulary() -> dict[str, Any]:
    """Return the UI vocabulary as a plain dict: the scenario codes, the fixed canonical paths, and
    the dynamic ``custom_*`` category prefixes the mapping table must each label."""
    return {
        "scenario_codes": sorted({*SCENARIO_HAZARD, GENERIC_REQUIRED_FIELD_SCENARIO}),
        "canonical_paths": sorted(FIXED_CANONICAL_PATHS),
        "custom_path_categories": sorted(CUSTOM_PATH_CATEGORIES),
    }


def serialize(document: dict[str, Any]) -> str:
    """Canonical text form: sorted keys, 2-space indent, one trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_artifact(path: Path = ARTIFACT_PATH) -> Path:
    """Regenerate the committed artifact at ``path`` and return it."""
    path.write_text(serialize(build_vocabulary()), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised via write_artifact() in tests
    written = write_artifact()
    print(f"Wrote {written}")
