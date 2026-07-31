"""``CITATION.cff`` names a version too, and it must not drift from the package.

Alongside ``pyproject.toml`` and ``xtalate.__version__`` (guarded against each other in
``test_version.py``), the citation file carries a third ``version:`` — the one a user cites when
they cite Xtalate. It has no code path forcing it current, so it is the declaration most prone to
being forgotten on a release bump: it sat at ``0.4.0`` through the ``0.5.0`` and ``0.6.0`` releases
before the v0.6 architectural review caught it by eye (`docs/private/DECISIONS.md` D99). A drift
here does not corrupt provenance the way a ``__version__`` drift does, but it does make the project
misreport itself to anyone who cites it — a transparency defect for a tool whose whole claim is that
its record can be trusted — so the same slip should be caught by CI, not by the next reviewer.

The comparison is against ``xtalate.__version__`` (already pinned to ``pyproject.toml``), so the
three declarations form one chain: bump one, and the two guards make the other two fail until they
agree. The release *date* is deliberately not asserted — it has no source-of-truth in code and is
correct to differ from any prior release.
"""

from __future__ import annotations

import re
from pathlib import Path

import xtalate

_CITATION = Path(__file__).resolve().parent.parent / "CITATION.cff"

#: ``version:`` at the start of a line — CFF is YAML, but a full parser is a dependency this one
#: assertion does not justify, and the field is a plain unquoted scalar.
_VERSION_LINE = re.compile(r"^version:\s*(?P<value>\S+)\s*$", re.MULTILINE)


def test_citation_version_matches_package() -> None:
    text = _CITATION.read_text(encoding="utf-8")
    match = _VERSION_LINE.search(text)
    assert match is not None, "CITATION.cff has no top-level `version:` line"
    declared = match.group("value")
    assert declared == xtalate.__version__, (
        f"version drift: CITATION.cff says {declared!r} but xtalate.__version__ is "
        f"{xtalate.__version__!r}. The citation file is the version a user cites; a release bump "
        "must move it too, or the project misreports its own version to anyone citing it (D99)."
    )
