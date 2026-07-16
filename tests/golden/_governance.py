"""Golden-corpus governance: manifest schema, integrity, and attribution aggregation.

This module is the mechanized form of the sourcing/licensing/versioning policy of
``docs/MASTER_SPEC.md`` Part 8 §3 and the licensing decision of Part 10 §4.1 (v0.2 M11).
It is *not* a test module; ``tests/golden/test_corpus_governance.py`` drives it, and
running it as a script (``python tests/golden/_governance.py``) regenerates
``tests/golden/ATTRIBUTIONS.md`` in place so a contributor can refresh attributions
locally exactly as CI checks them.

Four guarantees are enforced here, each with a *why* rooted in the mission — a golden
corpus a stranger can extend without a maintainer in the loop, and that can never
silently rot or lose an attribution:

* **Schema.** Every ``manifest.yaml`` carries the required fields — including
  ``origin.kind``, ``origin.license``, and ``sha256`` — with values in the declared
  vocabularies. *No manifest, no license, no merge* (§3.2): a missing license is a hard
  failure, not a warning, because redistributing an unlicensed third-party file is the
  one corpus mistake that cannot be undone after the fact.
* **Integrity.** The recorded ``sha256`` matches the source file's real digest, so a
  silent fixture edit (which would silently invalidate its hand-verified expectation) is
  impossible — the hash is the tripwire.
* **Schema-version sync (§3.3).** Every ``expected.canonical.json`` loads through the
  migration chain (currently the identity, since the schema is a single pre-1.0 version —
  see ``load_expected_through_migration_chain``), and no manifest's
  ``canonical_schema_version`` is more than one *major* version behind current. Expectations
  may lag; they may not silently rot.
* **Attribution (§3.2).** ``ATTRIBUTIONS.md`` is *generated* from the manifests, never
  hand-edited, so an attribution obligation carried in a manifest can never lapse in the
  aggregate file — the test diffs the committed file against a fresh render and fails on
  any drift.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xtalate.schema import SCHEMA_VERSION, CanonicalObject

GOLDEN_ROOT = Path(__file__).parent
ATTRIBUTIONS_PATH = GOLDEN_ROOT / "ATTRIBUTIONS.md"

# The three admissible origins (Part 8 §3.2), in the spec's preference order.
ORIGIN_KINDS = ("synthetic", "published-dataset", "contributed")

# A 64-char lowercase-hex SHA-256 digest.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# A loose semver *shape* check — the schema-version cross-checks do the real work.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ManifestError(ValueError):
    """A golden manifest violates the corpus governance policy (Part 8 §3)."""


@dataclass(frozen=True)
class GoldenCase:
    """A single golden entry, resolved from its ``manifest.yaml``."""

    manifest_path: Path
    data: dict[str, Any]

    @property
    def directory(self) -> Path:
        return self.manifest_path.parent

    @property
    def source_path(self) -> Path:
        return self.directory / str(self.data["source_file"])

    @property
    def expected_path(self) -> Path:
        return self.directory / str(self.data["expected_canonical"])

    @property
    def rel_manifest(self) -> str:
        try:
            return self.manifest_path.relative_to(GOLDEN_ROOT.parent.parent).as_posix()
        except ValueError:
            return self.manifest_path.as_posix()


def discover_cases(root: Path = GOLDEN_ROOT) -> list[GoldenCase]:
    """Every golden case under ``root``, one per ``manifest.yaml``, sorted by path."""

    cases: list[GoldenCase] = []
    for manifest_path in sorted(root.rglob("manifest.yaml")):
        with manifest_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ManifestError(f"{manifest_path}: manifest must be a YAML mapping")
        cases.append(GoldenCase(manifest_path=manifest_path, data=data))
    return cases


def validate_manifest_schema(case: GoldenCase) -> None:
    """Enforce the manifest schema (Part 8 §3.1–§3.2). Raises ``ManifestError``.

    Required top-level keys and an ``origin`` mapping with a ``kind`` in the admissible
    vocabulary and a **non-empty license** are non-negotiable; CC-BY origins additionally
    require an ``attribution`` string, since that is the obligation the aggregated
    ``ATTRIBUTIONS.md`` exists to honor.
    """

    data = case.data
    where = case.rel_manifest

    required = (
        "case",
        "format_id",
        "source_file",
        "expected_canonical",
        "canonical_schema_version",
        "sha256",
        "origin",
    )
    for key in required:
        if key not in data:
            raise ManifestError(f"{where}: missing required field '{key}'")

    if not _SHA256_RE.match(str(data["sha256"])):
        raise ManifestError(f"{where}: 'sha256' must be 64 lowercase hex chars")

    if not _SEMVER_RE.match(str(data["canonical_schema_version"])):
        raise ManifestError(
            f"{where}: 'canonical_schema_version' must be a semver string (e.g. '0.1.0')"
        )

    origin = data["origin"]
    if not isinstance(origin, dict):
        raise ManifestError(f"{where}: 'origin' must be a mapping")

    kind = origin.get("kind")
    if kind not in ORIGIN_KINDS:
        raise ManifestError(f"{where}: origin.kind must be one of {ORIGIN_KINDS}, got {kind!r}")

    # No license, no merge (§3.2). A blank or missing license is a hard failure.
    license_ = origin.get("license")
    if not isinstance(license_, str) or not license_.strip():
        raise ManifestError(
            f"{where}: origin.license is required and must be non-empty "
            "(no manifest, no license, no merge — Part 8 §3.2)"
        )

    # A published-dataset case must name its source; a contributed case must carry the
    # contributor's license grant in the manifest (the PR template's checkbox, §3.2 item 3).
    if kind == "published-dataset" and not str(origin.get("source", "")).strip():
        raise ManifestError(f"{where}: origin.source is required for a published-dataset case")

    # CC-BY* requires attribution to be carried into ATTRIBUTIONS.md.
    if license_.upper().startswith("CC-BY") and not str(origin.get("attribution", "")).strip():
        raise ManifestError(
            f"{where}: origin.attribution is required for a CC-BY license "
            "(it is the obligation ATTRIBUTIONS.md aggregates)"
        )

    # The source and expectation files the manifest names must actually exist.
    if not case.source_path.is_file():
        raise ManifestError(f"{where}: source_file '{data['source_file']}' not found")
    if not case.expected_path.is_file():
        raise ManifestError(f"{where}: expected_canonical '{data['expected_canonical']}' not found")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source_hash(case: GoldenCase) -> None:
    """Fail if the source file's digest disagrees with the manifest (silent-edit tripwire)."""

    recorded = str(case.data["sha256"])
    actual = sha256_of(case.source_path)
    if actual != recorded:
        raise ManifestError(
            f"{case.rel_manifest}: sha256 mismatch for '{case.data['source_file']}'\n"
            f"  manifest: {recorded}\n  actual:   {actual}\n"
            "  If the fixture change is intentional, update the manifest sha256."
        )


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def load_expected_through_migration_chain(case: GoldenCase) -> CanonicalObject:
    """Load ``expected.canonical.json`` as the current schema would (Part 8 §3.3).

    The schema is a single pre-1.0 version (``0.1.0``), so the *migration chain* is the
    identity today: pydantic validation against the current models. This function is the
    seam Part 8 §3.3 names — when real migrations land (schema §5), they are threaded here,
    so the whole corpus exercises the migration path on every run and a minor (additive)
    bump needs zero fixture edits. It deliberately owns the load so that "load through the
    migration chain" has exactly one implementation for the whole corpus.
    """

    obj = CanonicalObject.model_validate_json(case.expected_path.read_text(encoding="utf-8"))

    # The embedded schema_version and the manifest's declared authoring version must agree —
    # a mismatch means the manifest or the expectation was edited without the other.
    embedded = obj.schema_version
    declared = str(case.data["canonical_schema_version"])
    if embedded != declared:
        raise ManifestError(
            f"{case.rel_manifest}: expectation schema_version {embedded!r} != manifest "
            f"canonical_schema_version {declared!r}"
        )
    return obj


def check_schema_version_lag(case: GoldenCase) -> None:
    """Fail if the manifest's schema version is more than one *major* behind current (§3.3)."""

    declared = str(case.data["canonical_schema_version"])
    lag = _major(SCHEMA_VERSION) - _major(declared)
    if lag > 1:
        raise ManifestError(
            f"{case.rel_manifest}: canonical_schema_version {declared!r} is {lag} major "
            f"versions behind current {SCHEMA_VERSION!r} (max 1) — regenerate the expectation."
        )


# --- ATTRIBUTIONS.md generation (§3.2) ------------------------------------------------

_ATTRIBUTIONS_HEADER = """\
<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python tests/golden/_governance.py
     Source of truth: the per-fixture tests/golden/**/manifest.yaml files.
     CI regenerates this file and fails if it drifts (Part 8 §3.2; Part 10 §4.5). -->

# Golden-corpus attributions

Every file in the golden test corpus (`tests/golden/`) is admitted only with a license
recorded in its `manifest.yaml` (Part 8 §3.2). This file aggregates those licenses and
attributions so the obligations can never silently lapse. Synthetic, hand-authored
fixtures are the project's own work under Apache-2.0; third-party data (CC0 / CC-BY /
contributor grants) carries its source attribution here and is surfaced in the top-level
`NOTICE` file.
"""


def render_attributions(cases: list[GoldenCase]) -> str:
    """Render ``ATTRIBUTIONS.md`` from the manifests. Deterministic and byte-stable."""

    lines = [_ATTRIBUTIONS_HEADER]
    for case in sorted(cases, key=lambda c: (c.data["format_id"], c.data["case"])):
        origin = case.data["origin"]
        lines.append(f"## `{case.data['format_id']}` / `{case.data['case']}`\n")
        lines.append(f"- **Source file:** `{case.data['source_file']}`")
        lines.append(f"- **Origin:** {origin['kind']}")
        lines.append(f"- **License:** {origin['license']}")
        source = str(origin.get("source", "")).strip()
        if source:
            lines.append(f"- **Source:** {source}")
        url = str(origin.get("url", "")).strip()
        if url:
            lines.append(f"- **URL:** {url}")
        doi = str(origin.get("doi", "")).strip()
        if doi:
            lines.append(f"- **DOI:** {doi}")
        attribution = str(origin.get("attribution", "")).strip()
        if attribution:
            lines.append(f"- **Attribution:** {attribution}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_attributions(root: Path = GOLDEN_ROOT) -> str:
    """Regenerate ``ATTRIBUTIONS.md`` on disk and return the content written."""

    content = render_attributions(discover_cases(root))
    ATTRIBUTIONS_PATH.write_text(content, encoding="utf-8")
    return content


if __name__ == "__main__":
    written = write_attributions()
    print(f"Wrote {ATTRIBUTIONS_PATH} ({len(written)} bytes)")
