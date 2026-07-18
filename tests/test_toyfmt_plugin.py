"""End-to-end proof of entry-point discovery against a *real installed distribution* (M16B).

M16A verified the discovery mechanism with in-memory fakes monkeypatched over
``entry_points``. This module closes the last gap: an actual installable package,
``tests/fixtures/xtalate_toyfmt``, that advertises a parser and exporter under the
``xtalate.parsers`` / ``xtalate.exporters`` entry-point groups. When it is pip-installed, the
``toyfmt`` format must appear in ``default_registry()``, in the Capability Matrix, on the
``xtalate capabilities`` CLI surface, and must carry a real conversion through the whole pipeline.

The fixture is installed by CI (`pip install --no-deps ./tests/fixtures/xtalate_toyfmt`); these
tests **skip** when it is absent, so a plain local checkout stays green. To run them locally:

    pip install --no-deps ./tests/fixtures/xtalate_toyfmt

The always-on mechanism proof lives in ``tests/test_entry_point_discovery.py``; this is the
genuine-packaging complement, which by nature needs a distribution on disk.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from xtalate.registry import default_registry

_DISTRIBUTION = "xtalate-toyfmt"
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xtalate_toyfmt"


def _toyfmt_installed() -> bool:
    try:
        importlib_metadata.distribution(_DISTRIBUTION)
    except importlib_metadata.PackageNotFoundError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _toyfmt_installed(),
    reason=(
        f"{_DISTRIBUTION} not installed; run `pip install --no-deps ./{_FIXTURE_DIR.as_posix()}` "
        "(CI installs it before pytest)"
    ),
)


def test_toyfmt_is_discovered_in_default_registry() -> None:
    """The installed plugin is registered as both a parser and an exporter, additively — the
    built-ins are still present and unchanged (P6)."""
    registry = default_registry()
    parser_ids = {p.format_id for p in registry.parsers()}
    exporter_ids = {e.format_id for e in registry.exporters()}

    assert "toyfmt" in parser_ids
    assert "toyfmt" in exporter_ids
    assert {"xyz", "poscar"} <= parser_ids  # built-ins untouched


def test_toyfmt_is_queryable_in_the_capability_matrix() -> None:
    """It went through the real ``register_*`` path, so its capability declaration is assembled
    into the matrix on both directions (which is what lets it participate in conversions)."""
    matrix = default_registry().capability_matrix()
    assert matrix.get("toyfmt", "read").format_id == "toyfmt"
    assert matrix.get("toyfmt", "write").format_id == "toyfmt"


def test_cli_capabilities_lists_toyfmt() -> None:
    """The discovered format surfaces on the real CLI. Run in a fresh subprocess so the entry
    point is resolved from installed dist-info metadata, not from anything this process set up."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from xtalate.cli import main; sys.exit(main(sys.argv[1:]))",
            "capabilities",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    payload = json.loads(proc.stdout)
    assert "toyfmt" in payload
    assert "read" in payload["toyfmt"]
    assert "write" in payload["toyfmt"]


def test_toyfmt_converts_to_xyz_through_the_full_pipeline(tmp_path: Path) -> None:
    """A cross-format conversion enabled purely by discovery: the toy file is parsed by the
    installed third-party parser, flows through the Canonical Model, and is written by the built-in
    XYZ exporter — geometry preserved exactly. Proves the plugin plugs into the whole spine, not
    just the registry."""
    source = tmp_path / "water.toy"
    source.write_text("TOYFMT 1\nO 0.0 0.0 0.0\nH 0.9584 0.0 0.0\n", encoding="utf-8")
    output = tmp_path / "water.xyz"

    from xtalate.cli import main

    assert main(["convert", str(source), "--to", "xyz", "-o", str(output)]) == 0

    # Re-parse the emitted XYZ with the built-in parser and confirm the geometry survived.
    registry = default_registry()
    with output.open("rb") as handle:
        reparsed = registry.get_parser("xyz").parse(handle, filename=output.name)
    atoms = reparsed.canonical.frames[0].atoms
    assert atoms.symbols == ["O", "H"]
    np.testing.assert_allclose(atoms.positions, [[0.0, 0.0, 0.0], [0.9584, 0.0, 0.0]])
