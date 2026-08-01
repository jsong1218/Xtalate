"""The committed UI vocabulary must not drift silently from the engine's registries (M26).

``docs/vocabulary.json`` is what the frontend's plain-language mapping-coverage lint reads (Part 7
§3.3) — it enumerates every recovery scenario code and every canonical field path the UI could show.
It only means something if it stays in lockstep with the engine, so this test regenerates it and
asserts byte-equality: a new scenario in ``SCENARIO_HAZARD`` or a new field in the presence path
table fails the gate until ``python -m backend.vocabulary`` is rerun and the artifact committed —
at which point the frontend lint (which reads this file) demands a matching mapping-table entry.

The vocabulary is a pure function of the source registries (sorted keys), so this comparison is
deterministic across differently-stale editable installs, exactly like the OpenAPI drift test.
"""

from __future__ import annotations

from backend.vocabulary import ARTIFACT_PATH, build_vocabulary, serialize
from xtalate.conversion.parse_recovery import PARSE_TIME_SCENARIOS
from xtalate.conversion.preflight import GENERIC_REQUIRED_FIELD_SCENARIO
from xtalate.recovery.engine import _DEP_ORDER
from xtalate.recovery.scenarios import SCENARIO_HAZARD, available_options
from xtalate.schema.presence import FIXED_CANONICAL_PATHS


def test_committed_vocabulary_matches_the_engine() -> None:
    """``docs/vocabulary.json`` equals a freshly generated export — regenerate it if this fails."""
    committed = ARTIFACT_PATH.read_text(encoding="utf-8")
    regenerated = serialize(build_vocabulary())
    assert committed == regenerated, (
        "The committed UI vocabulary artifact is stale. Run `python -m backend.vocabulary` and "
        "commit docs/vocabulary.json — then add the missing mapping-table entry in the frontend."
    )


def test_vocabulary_covers_every_engine_registry() -> None:
    """A sanity floor independent of the byte diff: nothing the engine exposes is omitted."""
    document = build_vocabulary()
    # The catalog scenarios plus the generic required-field fallback (P6): the code a target's
    # required field surfaces when it has no catalog-specific mapping. It is not in SCENARIO_HAZARD
    # (which is the interactive-recovery catalog) but the UI must still be able to label it.
    expected_scenarios = set(SCENARIO_HAZARD) | {GENERIC_REQUIRED_FIELD_SCENARIO}
    assert set(document["scenario_codes"]) == expected_scenarios
    assert set(document["canonical_paths"]) == set(FIXED_CANONICAL_PATHS)
    # The dynamic per-key categories are the only non-fixed paths, and must be present so the
    # mapping table can label a `custom_global['k']` row by its category (Part 7 §3.3).
    assert document["custom_path_categories"], "custom_* categories must be exported for the lint"


def test_choice_codes_cover_every_catalog_scenario() -> None:
    """Every catalog scenario has a choice-code list including the choices the engine offers for the
    concrete pair — the ground truth the frontend choice-label lint checks."""
    document = build_vocabulary()
    codes = document["choice_codes"]
    assert set(codes) == set(SCENARIO_HAZARD)
    # A directly-computed option is a subset of the exported union (unioned across flag combos), so
    # the union can never omit a choice a real pause could show.
    assert set(available_options("missing_lattice")) <= set(codes["missing_lattice"])
    # The flag-gated choices only the union exposes are present: `non_periodic` (non-periodic
    # target), `split_all` (multi-file target), `omit` (optional field, permissive mode).
    assert "non_periodic" in codes["missing_lattice"]
    assert "split_all" in codes["frame_selection"]
    assert "omit" in codes["missing_velocities"]


def test_resolution_order_is_parse_time_then_dependency_order() -> None:
    """The exported order is the engine's own: the parse-time stage first (it precedes parsing),
    then the conversion-time dependency order — from the engine constants, never re-typed here."""
    document = build_vocabulary()
    assert document["scenario_resolution_order"] == [*PARSE_TIME_SCENARIOS, *_DEP_ORDER]
    # The parse-time scenarios sort ahead of every conversion-time one (the F4 correctness point).
    order = document["scenario_resolution_order"]
    assert order.index("missing_species") < order.index("frame_selection")
    assert order.index("missing_species") < order.index("missing_lattice")
