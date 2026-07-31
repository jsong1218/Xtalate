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

import itertools
import json
from pathlib import Path
from typing import Any

from xtalate.conversion.parse_recovery import PARSE_TIME_SCENARIOS
from xtalate.conversion.preflight import GENERIC_REQUIRED_FIELD_SCENARIO
from xtalate.recovery.engine import _DEP_ORDER
from xtalate.recovery.scenarios import SCENARIO_HAZARD, available_options
from xtalate.schema.presence import CUSTOM_PATH_CATEGORIES, FIXED_CANONICAL_PATHS

#: The committed vocabulary the frontend mapping-coverage lint reads. Kept beside the human docs and
#: ``openapi.json`` — the two machine-readable contracts the UI generates/checks itself against.
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "docs" / "vocabulary.json"


def _all_choice_codes(scenario: str) -> list[str]:
    """Every ``choice`` code the engine could ever offer for ``scenario`` (Part 4 §3.3).

    ``available_options`` is *pair-specific* — it hides a choice not coherent for a given
    source/target (no ``non_periodic`` for a periodic-only target, no ``split_all`` for a
    single-file target, no ``omit`` for a required field). The coverage lint needs the *whole*
    offerable set so a plain-language label exists for every choice the UI could render, so we union
    the option list across all flag combinations. The catalog itself is the ground truth (v0.7
    review, F3): a choice added to ``available_options`` surfaces here, then as a lint failure until
    the frontend labels it — never as a raw code on a card."""
    codes: set[str] = set()
    for nonperiodic, multifile, optional, permissive in itertools.product((False, True), repeat=4):
        codes.update(
            available_options(
                scenario,
                target_can_be_nonperiodic=nonperiodic,
                target_supports_multifile=multifile,
                target_field_optional=optional,
                permissive_mode=permissive,
            )
        )
    return sorted(codes)


def build_vocabulary() -> dict[str, Any]:
    """Return the UI vocabulary as a plain dict: the scenario codes, every choice code each scenario
    can offer, the engine's recovery resolution order, the fixed canonical paths, and the dynamic
    ``custom_*`` category prefixes the mapping table must each label."""
    return {
        "scenario_codes": sorted({*SCENARIO_HAZARD, GENERIC_REQUIRED_FIELD_SCENARIO}),
        "choice_codes": {code: _all_choice_codes(code) for code in sorted(SCENARIO_HAZARD)},
        # The order the engine resolves recovery scenarios in (Part 4 §3.3): the parse-time stage
        # first (it precedes parsing), then the conversion-time dependency order. Read straight from
        # the engine constants — never re-typed — so the Web UI can render decision cards in true
        # resolution order without hand-copying the sequence (v0.7 review, F4).
        "scenario_resolution_order": [*PARSE_TIME_SCENARIOS, *_DEP_ORDER],
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
