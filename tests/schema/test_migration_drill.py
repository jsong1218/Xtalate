"""The widened migration drill (M75; Part 8 §3.3, Part 9 §6.2).

``test_migrations.py`` proves the single worked example — the committed occupancy 0.1.0 → 2.0.0
fixture pair — field by field. This drill generalizes that proof to *every schema version the
project has ever emitted* and to the *whole golden corpus*: a stored object authored at each emitted
version migrates through the full chain to current, carries exactly one recorded ``migrate``
transition (none when already current), and validates; and every hand-verified golden expectation,
whatever version it was authored at, loads green through the chain. This is the release-time
guarantee stated as one named gate — a stored 0.1.0 or 1.x corpus still loads on a 2.0.0 build, and
no persisted object is silently dropped or defaulted across a major boundary (P1/P3).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.golden._governance import (
    GOLDEN_ROOT,
    discover_cases,
    load_expected_through_migration_chain,
)
from xtalate.schema import SCHEMA_VERSION, load_canonical

# Every schema version the project has emitted, oldest first. Extend this tuple when a future major
# is added — the drill then automatically covers a stored object authored at it.
_EMITTED_VERSIONS = ("0.1.0", "1.0.0", "2.0.0")


def _stored_object(version: str) -> dict[str, Any]:
    """A minimal but structurally complete persisted object authored at ``version``.

    0.1.0 and 1.0.0 carry a root-level ``custom_per_atom`` column (the pre-2.0 shape), so the
    1.0.0 → 2.0.0 relocation step has real work to do; a 2.0.0 object omits it (relocated onto the
    frame) so the already-current case is a genuine no-op.
    """
    frame: dict[str, Any] = {
        "index": 0,
        "atoms": {"symbols": ["O", "H"], "positions": [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]},
    }
    base: dict[str, Any] = {
        "schema_version": version,
        "frames": [frame],
        "provenance": {
            "source_filename": "stored.dat",
            "source_format": "extxyz",
            "original_coordinate_system": "cartesian",
            "history": [],
        },
        "user_metadata": {},
    }
    if version in ("0.1.0", "1.0.0"):
        base["user_metadata"]["custom_per_atom"] = {"src:col": [1.0, 2.0]}
    return base


@pytest.mark.parametrize("version", _EMITTED_VERSIONS)
def test_stored_object_at_each_emitted_version_migrates_to_current(version: str) -> None:
    obj = load_canonical(_stored_object(version))
    assert obj.schema_version == SCHEMA_VERSION == "2.0.0"

    migrate_records = [r for r in obj.provenance.history if r.operation == "migrate"]
    if version == SCHEMA_VERSION:
        # Already current: the chain is a no-op, and a no-op is never recorded as a migration (P1 —
        # a recorded migrate that did nothing would be a lie about the provenance).
        assert migrate_records == []
    else:
        # Exactly one record spans the whole chain, naming the endpoints it actually crossed.
        assert len(migrate_records) == 1
        assert (
            migrate_records[0].assumptions[0]
            == f"Migrated canonical schema {version} → {SCHEMA_VERSION}."
        )


def test_the_whole_golden_corpus_loads_through_the_migration_chain() -> None:
    # The corpus-scale drill: every hand-verified expectation in the golden corpus — authored at
    # whatever schema version was current when it was committed — migrates forward and validates as
    # a current object. Governance checks this field-by-field per case; this asserts it as one
    # release gate so a corpus that no longer loads fails loudly here, not in a maintainer restore.
    cases = discover_cases(GOLDEN_ROOT)
    assert cases, "golden corpus is empty — the drill would be vacuous"
    for case in cases:
        obj = load_expected_through_migration_chain(case)
        assert obj.schema_version == SCHEMA_VERSION, case.rel_manifest
