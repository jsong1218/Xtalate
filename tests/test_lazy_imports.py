"""Lazy optional-heavy imports (spec E2): ``ase`` and ``h5py`` load only when a format that
needs them is actually used.

Each case runs in a fresh interpreter, because ``sys.modules`` in the pytest process is already
polluted by other suites. The poscar -> cif path is the representative "no ASE needed" job: it
exercises ``default_registry()``, the Sniffer over *every* registered parser, the Discovery
Engine, parse, convert and the validation re-parse.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

POSCAR = b"NaCl\n1.0\n 5.64 0 0\n 0 5.64 0\n 0 0 5.64\nNa Cl\n1 1\nDirect\n 0 0 0\n 0.5 0.5 0.5\n"

_PRELUDE = f"""
import json, sys
from xtalate.conversion import ConversionEngine, parse_with_recovery
from xtalate.discovery import DiscoveryEngine
from xtalate.registry import default_registry

POSCAR = {POSCAR!r}
reg = default_registry()
parsed = parse_with_recovery(reg, POSCAR, filename="POSCAR")
DiscoveryEngine(reg).discover(POSCAR, filename="POSCAR")
engine = ConversionEngine(reg)
"""


def _run(body: str) -> dict[str, object]:
    code = _PRELUDE + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out: dict[str, object] = json.loads(proc.stdout.strip().splitlines()[-1])
    return out


def _convert(target: str) -> str:
    return f"""
result = engine.convert(
    parsed.canonical, source_format_id=parsed.format_id, target_format_id="{target}",
    parse_recovery=parsed,
)
assert result.report.status == "completed", result.report.status
assert result.output
print(json.dumps({{
    "ase": "ase" in sys.modules,
    "h5py": "h5py" in sys.modules,
    "head": result.output[:8].decode("latin-1"),
}}))
"""


def test_default_registry_and_a_cif_conversion_import_neither_ase_nor_h5py() -> None:
    state = _run(_convert("cif"))
    assert state["ase"] is False, "ase was imported by import/sniff/discover/poscar->cif"
    assert state["h5py"] is False, "h5py was imported by import/sniff/discover/poscar->cif"


def test_registry_construction_alone_imports_neither() -> None:
    code = (
        "import sys\n"
        "from xtalate.registry import default_registry\n"
        "default_registry()\n"
        "print(int('ase' in sys.modules) + 2 * int('h5py' in sys.modules))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0"


def test_an_extxyz_conversion_imports_ase_but_not_h5py() -> None:
    state = _run(_convert("extxyz"))
    assert state["ase"] is True
    assert state["h5py"] is False
    assert str(state["head"]).startswith("2\n")


def test_an_ase_traj_conversion_works_lazily() -> None:
    state = _run(_convert("ase_traj"))
    assert state["ase"] is True
    assert state["head"] == "- of Ulm"


def test_an_h5md_conversion_imports_h5py() -> None:
    state = _run(_convert("h5md"))
    assert state["h5py"] is True
    assert str(state["head"]).startswith("\x89HDF")
