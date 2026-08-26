"""The adapters' import contract (v1.5 M57-S1; D215).

``import xtalate`` and ``import xtalate.adapters`` must succeed with pymatgen **absent**
— the lazy-import obligation that makes pymatgen a consumed optional extra, never a
dependency (D4). This module deliberately does *not* ``pytest.importorskip("pymatgen")``
so the import assertions always run; only the call-path cases below are gated on the
extra being installed.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_BLOCKED = (
    "import sys; sys.modules['pymatgen'] = None; "
    "sys.modules['pymatgen.core'] = None; "
    "sys.modules['pymatgen.core.periodic_table'] = None"
)


def test_import_xtalate_and_adapters_never_touch_pymatgen() -> None:
    """Both imports succeed unconditionally — this test runs even without the extra."""
    import xtalate  # noqa: F401
    import xtalate.adapters  # noqa: F401


@pytest.mark.parametrize(
    "snippet",
    [
        "import xtalate",
        "import xtalate.adapters",
    ],
)
def test_imports_succeed_with_pymatgen_absent(snippet: str) -> None:
    """A fresh interpreter with every pymatgen module blocked still imports both."""
    result = subprocess.run(
        [sys.executable, "-c", f"{_BLOCKED}; {snippet}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_adapter_call_without_pymatgen_names_the_extra() -> None:
    """Calling an adapter with the extra absent raises the extra-naming message (D4),
    not a bare ImportError traceback from deep inside a lazy import."""
    code = (
        f"{_BLOCKED}; "
        "from xtalate.adapters import from_pymatgen\n"
        "try:\n"
        "    from_pymatgen(None)\n"
        "except ImportError as exc:\n"
        "    print(str(exc))\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "pymatgen is required for the pymatgen adapters; install xtalate[pymatgen]"
    )
