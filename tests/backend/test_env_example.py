"""``.env.example`` documents exactly the settings the service reads (M34-S2).

The self-hosting story is "configure by environment only" (MASTER_SPEC Part 9 §2), and
``.env.example`` is the committed, commented template a self-hoster copies. It is only trustworthy
if it neither **omits** a real setting (a knob you cannot discover) nor advertises a **phantom** one
(a knob that does nothing). This binds the template to the two things that actually read the
environment:

* every field of :class:`backend.config.Settings` (with the ``XTALATE_`` prefix), and
* the three launcher variables ``python -m backend`` reads straight from ``os.environ``
  (``XTALATE_HOST``, ``XTALATE_PORT``, ``XTALATE_RELOAD``) — the one documented seam that is not a
  ``Settings`` field, listed here so the phantom scan does not flag them.

Mirrors the error-code and vocabulary completeness scans: a missing setting fails, a phantom knob
fails. Values are not asserted here — only that the *keys* are the real, complete set.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.config import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

#: Read directly by ``backend/__main__.py`` (the local-dev uvicorn launcher), not ``Settings``
#: fields. Adding a new one of these is the one case that also needs a line here.
_LAUNCHER_VARS = {"HOST", "PORT", "RELOAD"}

#: A commented or live ``XTALATE_<KEY>=`` assignment line.
_KEY_LINE = re.compile(r"^#?\s*XTALATE_([A-Z0-9_]+)=", re.MULTILINE)


def _documented_keys() -> set[str]:
    """Every ``XTALATE_<KEY>`` the template names (commented lines included)."""
    return set(_KEY_LINE.findall(_ENV_EXAMPLE.read_text(encoding="utf-8")))


def _settings_keys() -> set[str]:
    """Every configurable ``Settings`` field, upper-cased to its environment-variable spelling."""
    return {name.upper() for name in Settings.model_fields}


def test_every_setting_is_documented() -> None:
    """No real setting is missing from the template a self-hoster copies."""
    missing = _settings_keys() - _documented_keys()
    assert not missing, (
        f".env.example omits these XTALATE_ settings (add a commented line for each): "
        f"{sorted(missing)}"
    )


def test_no_phantom_knobs() -> None:
    """The template advertises nothing the service does not read."""
    phantom = _documented_keys() - _settings_keys() - _LAUNCHER_VARS
    assert not phantom, (
        f".env.example documents knobs the service never reads (remove them, or the scan missed a "
        f"new seam): {sorted(phantom)}"
    )
