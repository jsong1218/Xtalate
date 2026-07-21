"""Test-corpus governance tests (v0.2 M11, Part 8 §3; extended to the wild corpus in v0.4 M20).

These are the CI teeth behind the sourcing/licensing/versioning policy: a PR that adds a
case with a missing license, a wrong hash, a lagging schema version, or a stale
``ATTRIBUTIONS.md`` fails here with a readable message. The logic lives in
``tests/golden/_governance.py`` (also runnable as a script to regenerate attributions).

Both corpora are governed here — ``tests/golden/`` and ``tests/wild/`` (D70). The wild corpus
is where the teeth matter most: its files are genuinely third-party, so it is the only place a
lapsed attribution could become a real licensing problem rather than a hypothetical one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden import _governance as gov


def _cases() -> list[gov.GoldenCase]:
    """Every case in every corpus root.

    Sourcing, licensing, hashing and attribution are corpus-independent (D70), so the teeth
    bite on the wild corpus exactly as hard as on the golden one — a vendored COD file with no
    license is no more admissible than a synthetic fixture with none. The handful of checks
    that *are* golden-only (the canonical-JSON hash, the migration-chain load) filter to
    ``not case.is_wild`` at their own parametrization rather than here."""
    return gov.discover_all_cases()


def _golden_cases() -> list[gov.GoldenCase]:
    """Cases whose expectation is a hand-verified ``expected.canonical.json``."""
    return [case for case in gov.discover_all_cases() if not case.is_wild]


def test_corpus_is_non_empty() -> None:
    # A vacuously-passing governance suite (no manifests discovered) would be worse than
    # no suite at all — it would advertise a guarantee it does not check.
    assert _cases(), "no manifests discovered under tests/golden/ or tests/wild/"


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_manifest_schema_valid(case: gov.GoldenCase) -> None:
    gov.validate_manifest_schema(case)


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c.rel_manifest)
def test_source_hash_matches(case: gov.GoldenCase) -> None:
    gov.verify_source_hash(case)


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c.rel_manifest)
def test_expected_hash_matches(case: gov.GoldenCase) -> None:
    gov.verify_expected_hash(case)


@pytest.mark.parametrize("root", gov.ALL_ROOTS, ids=lambda r: r.name)
def test_no_misspelled_manifests(root: Path) -> None:
    stray = gov.find_misspelled_manifests(root)
    assert not stray, (
        f"manifest(s) named 'manifest.yml' bypass discovery — rename to 'manifest.yaml': {stray}"
    )


@pytest.mark.parametrize("root", gov.ALL_ROOTS, ids=lambda r: r.name)
def test_every_corpus_data_file_is_claimed_by_a_manifest(root: Path) -> None:
    # The generalization of "no manifest, no merge": a source or expectation file dropped into
    # a corpus root without a manifest would bypass license/hash/schema governance entirely.
    orphans = gov.find_unclaimed_files(root)
    assert not orphans, (
        "corpus data file(s) claimed by no manifest (no license, no hash, no schema check) — "
        f"add a manifest.yaml or move them out of {root.name}/: {orphans}"
    )


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c.rel_manifest)
def test_expectation_loads_through_migration_chain(case: gov.GoldenCase) -> None:
    obj = gov.load_expected_through_migration_chain(case)
    assert obj.frame_count >= 1


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c.rel_manifest)
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
