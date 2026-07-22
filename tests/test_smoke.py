"""M0 smoke test: the package imports and every declared subpackage exists.

This keeps the scaffold's ``pytest`` run green (IMPLEMENTATION_PLAN.md M0);
real tests arrive with the canonical schema in M1.
"""

import importlib
import re

import xtalate

SUBPACKAGES = (
    "schema",
    "sdk",
    "parsers",
    "exporters",
    "capabilities",
    "discovery",
    "conversion",
    "recovery",
    "validation",
    "cli",
)


def test_package_version_is_a_release_version() -> None:
    # Deliberately not `== "0.4.0"`. A literal here was a *third* declaration of the version, and
    # pinning the test to it is what let pyproject.toml and __init__.py drift apart on the v0.4
    # release commit with the suite green: bumping a release edits the literal mechanically, so
    # the assertion only ever confirmed that someone had edited two lines in the same file. The
    # comparison that means something — __version__ against pyproject.toml, the number the built
    # artifact actually carries — lives in tests/test_version.py. This keeps only the shape check.
    assert re.fullmatch(r"\d+\.\d+\.\d+", xtalate.__version__), xtalate.__version__


def test_subpackages_importable() -> None:
    for name in SUBPACKAGES:
        importlib.import_module(f"xtalate.{name}")


def test_cli_entry_point_runs() -> None:
    from xtalate.cli import main

    # No subcommand prints help and returns the usage exit code (M6; was a placeholder 0 pre-M6).
    assert main([]) == 1
