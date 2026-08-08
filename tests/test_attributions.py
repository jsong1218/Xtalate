"""The project-level ``ATTRIBUTIONS.md`` must not drift behind the dependency set.

``ATTRIBUTIONS.md`` (repo root, v1.0 M38) records every third-party distribution Xtalate installs
and runs against, with its license, so those obligations can never silently lapse (Part 10 §6, the
honesty half of the definition-of-done). A file like this rots the moment a dependency is added and
the attribution is forgotten — the exact failure the v1.0 review exists to rule out — so the same
slip is caught by CI, not by the next reviewer.

The completeness form: every distribution declared in ``pyproject.toml`` — the core
``[project].dependencies`` and the ``service`` optional extra — must appear, by name, in
``ATTRIBUTIONS.md``. (The ``dev`` extra is excluded on purpose: it ships no runtime code and is not
part of any installed or distributed artifact, so it carries no attribution obligation.) The check
matches distribution *names* on token boundaries, so listing ``pydantic-settings`` does not
spuriously satisfy a missing ``pydantic``. It reads ``pyproject.toml`` for the source of truth
rather than the installed environment, so it runs in the ordinary gate without a resolved venv and
without network.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_ATTRIBUTIONS = _ROOT / "ATTRIBUTIONS.md"

#: Leading distribution name of a PEP 508 requirement string, before any extras (``[...]``),
#: version specifier, marker, or URL. ``uvicorn[standard]>=0.30`` -> ``uvicorn``.
_REQ_NAME = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of ``-_.`` collapse to a single ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(requirements: list[str]) -> list[str]:
    names: list[str] = []
    for req in requirements:
        match = _REQ_NAME.match(req)
        assert match is not None, f"unparseable requirement string: {req!r}"
        names.append(_normalize(match.group("name")))
    return names


def _declared_runtime_dependencies() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    core = _requirement_names(project["dependencies"])
    service = _requirement_names(project["optional-dependencies"]["service"])
    # Deduplicate while preserving order (service repeats nothing from core today, but be robust).
    return list(dict.fromkeys(core + service))


def test_attributions_file_exists_and_is_substantive() -> None:
    assert _ATTRIBUTIONS.is_file(), "ATTRIBUTIONS.md is missing from the repository root"
    text = _ATTRIBUTIONS.read_text(encoding="utf-8")
    assert "Apache" in text, "ATTRIBUTIONS.md must state Xtalate's own Apache-2.0 license"


def test_every_declared_runtime_dependency_is_attributed() -> None:
    normalized_file = _normalize(_ATTRIBUTIONS.read_text(encoding="utf-8"))
    missing: list[str] = []
    for name in _declared_runtime_dependencies():
        # Token-boundary match on the normalized name: ``pydantic`` must appear standalone, not
        # merely as the prefix of ``pydantic-settings`` (``-`` is a name-continuation character).
        pattern = re.compile(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])")
        if not pattern.search(normalized_file):
            missing.append(name)
    assert not missing, (
        "ATTRIBUTIONS.md is missing these declared runtime dependencies: "
        f"{', '.join(missing)}. Every distribution in pyproject.toml's [project].dependencies and "
        "the `service` extra must be attributed (with its license) in ATTRIBUTIONS.md — add the "
        "row, do not delete this check."
    )
