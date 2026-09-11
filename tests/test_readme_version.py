"""The README version badge names the version too, and it must not drift from the package.

``README.md`` is the most user-visible surface the project has, and its shields.io ``version``
badge is a fourth place the release number is written by hand — alongside ``pyproject.toml`` and
``xtalate.__version__`` (guarded in ``test_version.py``) and ``CITATION.cff`` (guarded in
``test_citation_version.py``). Unlike those three it had **no** guard, so it could silently lag a
release behind — every other surface moving while the full suite stayed green, and the badge
telling every reader the wrong version. Like the citation drift (D99), it corrupts no
provenance, but it makes the project misreport itself on its own front page — a transparency
defect for a tool whose whole claim is that its record can be trusted — so the same slip should be
caught by CI, not by the next reviewer.

The comparison is against ``xtalate.__version__`` (already pinned to ``pyproject.toml``), so all
four declarations form one chain: bump one, and the guards make the rest fail until they agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import xtalate

_README = Path(__file__).resolve().parent.parent / "README.md"

#: The shields.io badge encodes the version as ``badge/version-<value>-<color>.svg``. The version
#: starts with a digit and carries no dash of its own (shields escapes a literal dash as ``--``),
#: so capturing up to the next single dash isolates it without depending on the badge colour.
_BADGE_VERSION = re.compile(r"img\.shields\.io/badge/version-(?P<value>[0-9][^-]*)-")


def test_readme_version_badge_matches_package() -> None:
    text = _README.read_text(encoding="utf-8")
    match = _BADGE_VERSION.search(text)
    assert match is not None, "README.md has no shields.io `version` badge"
    declared = match.group("value")
    assert declared == xtalate.__version__, (
        f"version drift: the README version badge says {declared!r} but xtalate.__version__ is "
        f"{xtalate.__version__!r}. The badge is the version every reader sees first; a release "
        "bump must move it too, or the project misreports its own version on its front page."
    )
