"""Golden-corpus governance tests (v0.2 M11, Part 8 §3).

These are the CI teeth behind the sourcing/licensing/versioning policy: a PR that adds a
golden case with a missing license, a wrong hash, a lagging schema version, or a stale
``ATTRIBUTIONS.md`` fails here with a readable message. The logic lives in
``tests/golden/_governance.py`` (also runnable as a script to regenerate attributions).
"""

from __future__ import annotations

import pytest

from tests.golden import _governance as gov


def _cases() -> list[gov.GoldenCase]:
    return gov.discover_cases()


def test_corpus_is_non_empty() -> None:
    # A vacuously-passing governance suite (no manifests discovered) would be worse than
    # no suite at all — it would advertise a guarantee it does not check.
    assert _cases(), "no golden manifests discovered under tests/golden/"


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_manifest_schema_valid(case: gov.GoldenCase) -> None:
    gov.validate_manifest_schema(case)


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_source_hash_matches(case: gov.GoldenCase) -> None:
    gov.verify_source_hash(case)


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_expectation_loads_through_migration_chain(case: gov.GoldenCase) -> None:
    obj = gov.load_expected_through_migration_chain(case)
    assert obj.frame_count >= 1


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_schema_version_lag_within_bounds(case: gov.GoldenCase) -> None:
    gov.check_schema_version_lag(case)


def test_attributions_file_is_up_to_date() -> None:
    rendered = gov.render_attributions(_cases())
    committed = gov.ATTRIBUTIONS_PATH.read_text(encoding="utf-8")
    assert committed == rendered, (
        "tests/golden/ATTRIBUTIONS.md is stale — regenerate with "
        "`python tests/golden/_governance.py` and commit the result."
    )
