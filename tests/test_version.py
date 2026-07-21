"""The package version is declared twice and must agree.

``pyproject.toml`` names the version the built artifact carries; ``xtalate.__version__`` is what
the code reports, and it reaches users in a way a version string usually does not — it is stamped
into ``provenance.history[].tool_version`` on every object this tool produces. A drift between the
two therefore does not merely mislabel a wheel: it writes the wrong tool version into the
provenance record of every converted file, which is a correctness failure for a converter whose
whole claim is that its record of what happened can be trusted.

The gap is easy to open, because bumping a release touches ``pyproject.toml`` first and nothing
fails if the second declaration is forgotten — which is exactly what happened during the v0.4
bump, on the release commit, with the full suite green. Hence this test.

The comparison is against ``pyproject.toml`` rather than ``importlib.metadata.version``. Installed
metadata goes stale in an editable checkout — it does not re-resolve when the file changes, so it
happily reported ``0.2.0`` in a tree containing two other numbers — and a check that reads it would
be comparing two things that can both be wrong.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import xtalate

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_dunder_version_matches_pyproject() -> None:
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert xtalate.__version__ == declared, (
        f"version drift: pyproject.toml says {declared!r} but xtalate.__version__ is "
        f"{xtalate.__version__!r}. __version__ is stamped into provenance.history[].tool_version "
        "on every object this tool produces, so the mismatch would misattribute the provenance of "
        "every converted file, not just the package metadata."
    )
