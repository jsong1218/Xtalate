"""Shared DeePMD-kit ``.npy`` layout vocabulary and stress mapping (v1.5 M56).

This module is deliberately below both the parser and exporter. It contains only the native
layout names and the documented virial relation; it does not perform directory I/O or construct
canonical objects.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

FORMAT_ID = "deepmd_npy"
TYPE_FILE = "type.raw"
TYPE_MAP_FILE = "type_map.raw"
SET_PREFIX = "set."
COORD_FILE = "coord.npy"
BOX_FILE = "box.npy"
ENERGY_FILE = "energy.npy"
FORCE_FILE = "force.npy"
VIRIAL_FILE = "virial.npy"
LABEL_FILES = (ENERGY_FILE, FORCE_FILE, VIRIAL_FILE)
REQUIRED_ROOT_FILES = (TYPE_FILE,)


def is_set_path(path: str) -> bool:
    """Return whether ``path`` is a DeePMD set member path."""
    parts = path.split("/")
    return len(parts) == 2 and parts[0].startswith(SET_PREFIX) and parts[1].endswith(".npy")


def set_name(path: str) -> str | None:
    """Return the set directory component for a relative path, if it is one."""
    parts = path.split("/")
    if len(parts) == 2 and parts[0].startswith(SET_PREFIX):
        return parts[0]
    return None


def set_names(paths: Iterable[str]) -> list[str]:
    """Return deterministic sorted DeePMD set directory names."""
    return sorted({name for path in paths if (name := set_name(path)) is not None})


def volume_from_box(box: np.ndarray) -> np.ndarray:
    """Return absolute cell volumes for flattened or 3x3 row-vector boxes."""
    values = np.asarray(box, dtype=np.float64)
    matrices = values.reshape((-1, 3, 3))
    return np.abs(np.linalg.det(matrices))


def stress_from_virial(virial: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Map DeePMD's compression-positive virial to canonical tension-positive stress.

    DeePMD stores the virial as ``-stress * volume`` for the row-major 3x3 tensor. The sign
    reversal is part of DeePMD's documented convention, not an ambiguous source choice.
    """
    raw = np.asarray(virial, dtype=np.float64).reshape((-1, 3, 3))
    volumes = volume_from_box(box)
    if np.any(volumes <= 0):
        raise ValueError("virial requires a non-zero periodic box volume")
    result = (-raw / volumes[:, None, None]).astype(np.float64, copy=False)
    return np.asarray(result, dtype=np.float64)


def virial_from_stress(stress: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Map canonical tension-positive stress to DeePMD's flattened virial convention."""
    values = np.asarray(stress, dtype=np.float64).reshape((-1, 3, 3))
    volumes = volume_from_box(box)
    if np.any(volumes <= 0):
        raise ValueError("stress cannot be written as virial without a non-zero box volume")
    result = (-values * volumes[:, None, None]).reshape((-1, 9)).astype(np.float64, copy=False)
    return np.asarray(result, dtype=np.float64)
