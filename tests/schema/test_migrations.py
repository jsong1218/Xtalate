"""The real 0.1.0 -> 1.0.0 schema migration (M35 / D114, Part 2 §5, Part 8 §3.3).

The v1.0 contract freeze is the schema's first genuine version transition. These tests pin the
three things the freeze promised: the move is *real* (occupancy leaves the pre-1.0
``custom_per_atom['cif:occupancy']`` carry-through and lands in the first-class
``atoms.occupancies`` field), it is *recorded* (exactly one ``operation="migrate"`` provenance
entry, never silent — P1/§3.9), and it is *safe to run twice* (an already-current object is
untouched). The committed before/after JSON pair is the migration's worked example: a genuine
0.1.0 object and the exact 1.0.0 result the chain produces.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from xtalate import __version__
from xtalate.schema import (
    SCHEMA_VERSION,
    CanonicalObject,
    MigrationError,
    load_canonical,
    migrate,
)

FIXTURES = Path(__file__).parent / "fixtures"
BEFORE = FIXTURES / "occupancy_0_1_0_before.json"
AFTER = FIXTURES / "occupancy_1_0_0_after.json"


def _before() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(BEFORE.read_text(encoding="utf-8"))
    return data


def _pin_migrate_bookkeeping(data: dict[str, Any]) -> dict[str, Any]:
    """Replace the migrate record's run-varying fields with the stable placeholders the committed
    ``after`` fixture carries, so the produced object can be compared to it byte-for-byte."""
    for record in data["provenance"]["history"]:
        if record["operation"] == "migrate":
            record["timestamp"] = "<migrated>"
            record["tool_version"] = "<migrated>"
    return data


# --- the committed before/after pair (the migration's worked example) ---------------------------


def test_migrating_the_before_fixture_produces_the_after_fixture() -> None:
    # The whole migration, end to end, against a real persisted 0.1.0 object: the produced 1.0.0
    # mapping (with the migrate record's clock/version pinned) must equal the committed artifact.
    produced = _pin_migrate_bookkeeping(migrate(_before()))
    expected = json.loads(AFTER.read_text(encoding="utf-8"))
    assert produced == expected


def test_the_after_fixture_is_a_valid_current_object() -> None:
    # The artifact is not just a shape we asserted — it validates against the live 1.0.0 models,
    # so the pair cannot drift from the schema it documents.
    obj = CanonicalObject.model_validate_json(AFTER.read_text(encoding="utf-8"))
    assert obj.schema_version == "1.0.0"
    assert obj.frames[0].atoms.occupancies == [1.0, 0.5, None]


# --- the field move ------------------------------------------------------------------------------


def test_occupancy_moves_from_custom_per_atom_into_the_first_class_field() -> None:
    obj = load_canonical(_before())
    assert obj.frames[0].atoms.occupancies == [1.0, 0.5, None]
    assert "cif:occupancy" not in obj.user_metadata.custom_per_atom
    # The other carry-through columns are untouched — only the promoted key moves.
    assert "cif:atom_site_label" in obj.user_metadata.custom_per_atom


def test_object_level_occupancy_applies_to_every_frame() -> None:
    # A pre-1.0 per-atom carry-through is object-level: its first dimension is the atom count and it
    # applies to all frames (Part 2 §3.10). CIF is single-structure so this never arose in practice,
    # but the migration honours the general rule rather than assuming one frame.
    data = _before()
    frame0 = data["frames"][0]
    data["frames"].append({**copy.deepcopy(frame0), "index": 1})
    data["trajectory"] = {"timestep": None}

    obj = load_canonical(data)
    assert obj.frame_count == 2
    for frame in obj.frames:
        assert frame.atoms.occupancies == [1.0, 0.5, None]


# --- the version stamp and the record ------------------------------------------------------------


def test_schema_version_is_stamped_current() -> None:
    obj = load_canonical(_before())
    assert obj.schema_version == SCHEMA_VERSION == "1.0.0"


def test_exactly_one_migrate_record_is_appended() -> None:
    obj = load_canonical(_before())
    migrate_records = [r for r in obj.provenance.history if r.operation == "migrate"]
    assert len(migrate_records) == 1

    record = migrate_records[0]
    assert record.source_format is None
    assert record.target_format is None
    assert record.parser_version is None
    assert record.tool_version == __version__
    assert record.assumptions[0] == "Migrated canonical schema 0.1.0 → 1.0.0."
    assert "atoms.occupancies for 3 atom(s)" in record.assumptions[1]


def test_the_original_parse_record_is_preserved() -> None:
    # Provenance is append-only (§3.9): migration adds, never rewrites. The 0.1.0 parse record
    # survives verbatim ahead of the migrate record.
    obj = load_canonical(_before())
    ops = [r.operation for r in obj.provenance.history]
    assert ops == ["parse", "migrate"]
    assert obj.provenance.history[0].tool_version == "0.3.0"


# --- the version-only path (an object with nothing to move) --------------------------------------


def test_a_0_1_0_object_without_occupancy_still_migrates_and_records() -> None:
    # Every 0.1.0 object crosses the version boundary, occupancy or not: the version is stamped and
    # the transition recorded, but the field-move note is absent because nothing moved.
    data = _before()
    data["user_metadata"]["custom_per_atom"].pop("cif:occupancy")

    obj = load_canonical(data)
    assert obj.schema_version == "1.0.0"
    assert obj.frames[0].atoms.occupancies is None
    record = next(r for r in obj.provenance.history if r.operation == "migrate")
    assert record.assumptions == ["Migrated canonical schema 0.1.0 → 1.0.0."]


# --- idempotence and the no-op ------------------------------------------------------------------


def test_an_already_current_object_is_not_migrated_again() -> None:
    once = load_canonical(_before())
    twice = load_canonical(once.model_dump(mode="json"))
    # Loading a 1.0.0 object adds no second migrate record — the chain is a no-op at current.
    assert [r.operation for r in twice.provenance.history] == ["parse", "migrate"]
    assert twice.schema_version == "1.0.0"


def test_migrate_does_not_mutate_its_input() -> None:
    data = _before()
    snapshot = copy.deepcopy(data)
    migrate(data)
    assert data == snapshot  # the caller's mapping is untouched; a deep copy is migrated


# --- refusals: no default, no guess --------------------------------------------------------------


def test_missing_schema_version_is_refused() -> None:
    data = _before()
    del data["schema_version"]
    with pytest.raises(MigrationError, match="no schema_version"):
        migrate(data)


def test_unknown_schema_version_is_refused() -> None:
    data = _before()
    data["schema_version"] = "0.9.0"
    with pytest.raises(MigrationError, match="no migration path"):
        migrate(data)


# --- load_canonical accepts text, bytes, and mappings -------------------------------------------


@pytest.mark.parametrize("as_", ["text", "bytes", "dict"])
def test_load_canonical_accepts_text_bytes_and_dict(as_: str) -> None:
    raw = BEFORE.read_text(encoding="utf-8")
    source: str | bytes | dict[str, Any]
    if as_ == "text":
        source = raw
    elif as_ == "bytes":
        source = raw.encode("utf-8")
    else:
        source = json.loads(raw)

    obj = load_canonical(source)
    assert obj.schema_version == "1.0.0"
    assert obj.frames[0].atoms.occupancies == [1.0, 0.5, None]
