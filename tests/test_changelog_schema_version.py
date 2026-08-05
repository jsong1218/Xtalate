"""The changelog names the schema version it ships, and it must not drift from the code.

Alongside the three *package* version declarations (`pyproject.toml`, `xtalate.__version__`,
`CITATION.cff` — chained together in ``test_version.py`` and ``test_citation_version.py``), every
release states the *canonical* ``schema_version`` it carries. The two axes move under distinct rules
(see ``README.md`` — Versioning and stability): a release can ship without a schema change, so the
schema version is not derivable from the package version and has to be stated on its own.

The ``[Unreleased]`` section is where the next release accrues, so it is where the obligation is
enforced: it carries a ``Schema version:`` line, and that line must equal
``xtalate.schema.SCHEMA_VERSION``. This is the same kind of guard as the package-version chain —
a declaration a human maintains by hand, with no code path forcing it current, caught by CI rather
than by the next reviewer. Without it, a schema bump behind a real migration could ship while the
changelog still advertised the old ``schema_version`` — a transparency defect for a converter whose
whole claim is that its record of what it ships can be trusted.

Only the ``[Unreleased]`` section is asserted, not the historical release entries: those record what
each past release actually shipped and are not rewritten to match today's code.
"""

from __future__ import annotations

import re
from pathlib import Path

from xtalate.schema import SCHEMA_VERSION

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

#: The ``## [Unreleased]`` heading through to the next ``## [`` release heading (or end of file).
_UNRELEASED_SECTION = re.compile(
    r"^##\s*\[Unreleased\]\s*$(?P<body>.*?)(?=^##\s*\[|\Z)",
    re.MULTILINE | re.DOTALL,
)

#: ``Schema version: X.Y.Z`` at the start of a line — a plain scalar, no YAML parser needed.
_SCHEMA_VERSION_LINE = re.compile(r"^Schema version:\s*(?P<value>\S+)\s*$", re.MULTILINE)


def test_unreleased_schema_version_matches_code() -> None:
    text = _CHANGELOG.read_text(encoding="utf-8")

    section = _UNRELEASED_SECTION.search(text)
    assert section is not None, "CHANGELOG.md has no `## [Unreleased]` section"

    match = _SCHEMA_VERSION_LINE.search(section.group("body"))
    assert match is not None, (
        "the `## [Unreleased]` section of CHANGELOG.md has no `Schema version:` line. Every "
        "release entry — and the accruing `[Unreleased]` section — must state the canonical "
        "`schema_version` it ships, so a schema bump cannot go out silently."
    )

    declared = match.group("value")
    assert declared == SCHEMA_VERSION, (
        f"schema-version drift: CHANGELOG.md `[Unreleased]` says {declared!r} but "
        f"xtalate.schema.SCHEMA_VERSION is {SCHEMA_VERSION!r}. A schema change moves the canonical "
        "version behind a real migration; the changelog line must move with it, or the project "
        "misreports the schema version its next release ships."
    )
