"""M0 smoke test: the package imports and every declared subpackage exists.

This keeps the scaffold's ``pytest`` run green (IMPLEMENTATION_PLAN.md M0);
real tests arrive with the canonical schema in M1.
"""

import importlib

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


def test_package_version() -> None:
    assert xtalate.__version__ == "0.3.0"


def test_subpackages_importable() -> None:
    for name in SUBPACKAGES:
        importlib.import_module(f"xtalate.{name}")


def test_cli_entry_point_runs() -> None:
    from xtalate.cli import main

    # No subcommand prints help and returns the usage exit code (M6; was a placeholder 0 pre-M6).
    assert main([]) == 1
