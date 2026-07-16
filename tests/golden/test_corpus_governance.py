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
def test_expected_hash_matches(case: gov.GoldenCase) -> None:
    gov.verify_expected_hash(case)


def test_no_misspelled_manifests() -> None:
    stray = gov.find_misspelled_manifests()
    assert not stray, (
        f"manifest(s) named 'manifest.yml' bypass discovery — rename to 'manifest.yaml': {stray}"
    )


def test_every_corpus_data_file_is_claimed_by_a_manifest() -> None:
    # The generalization of "no manifest, no merge": a source or expectation file dropped under
    # tests/golden/ without a manifest would bypass license/hash/schema governance entirely.
    orphans = gov.find_unclaimed_files()
    assert not orphans, (
        "corpus data file(s) claimed by no manifest (no license, no hash, no schema check) — "
        f"add a manifest.yaml or move them out of tests/golden/: {orphans}"
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_expectation_loads_through_migration_chain(case: gov.GoldenCase) -> None:
    obj = gov.load_expected_through_migration_chain(case)
    assert obj.frame_count >= 1


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_schema_version_lag_within_bounds(case: gov.GoldenCase) -> None:
    gov.check_schema_version_lag(case)


def _synthetic_case(schema_version: str) -> gov.GoldenCase:
    """A GoldenCase whose only relevant field is the declared schema version — for exercising the
    lag bound at the boundary the single-pre-1.0-version corpus can never reach on its own."""
    return gov.GoldenCase(
        manifest_path=gov.GOLDEN_ROOT / "synthetic" / "manifest.yaml",
        data={"canonical_schema_version": schema_version},
    )


@pytest.mark.parametrize(
    ("current", "declared", "ok"),
    [
        ("2.0.0", "2.1.0", True),  # same major, ahead minor — fine
        ("2.0.0", "1.5.0", True),  # one major behind — the permitted lag
        ("2.0.0", "0.9.0", False),  # two majors behind — must regenerate
        ("1.0.0", "2.0.0", False),  # ahead of current major — impossible, a mistake
    ],
)
def test_schema_version_lag_boundary(
    monkeypatch: pytest.MonkeyPatch, current: str, declared: str, ok: bool
) -> None:
    # The live corpus is all 0.1.0, so lag can never be >1 (or negative) there; monkeypatch the
    # current schema version to prove the bound actually fires at the boundary in both directions.
    monkeypatch.setattr(gov, "SCHEMA_VERSION", current)
    case = _synthetic_case(declared)
    if ok:
        gov.check_schema_version_lag(case)
    else:
        with pytest.raises(gov.ManifestError):
            gov.check_schema_version_lag(case)


def test_attributions_file_is_up_to_date() -> None:
    rendered = gov.render_attributions(_cases())
    committed = gov.ATTRIBUTIONS_PATH.read_text(encoding="utf-8")
    assert committed == rendered, (
        "tests/golden/ATTRIBUTIONS.md is stale — regenerate with "
        "`python tests/golden/_governance.py` and commit the result."
    )
