"""Shared DeePMD system builders for the ``deepmd_npy`` golden fixtures (v1.5 M56-S1).

The values here are the *external truth* the expectations record: a bent H₂O at round
coordinates inside a 10 Å cubic box, with hand-chosen energies/forces and a hand-computed
virial (stress 0.01/0.02/0.03 eV/Å³ · 1000 Å³ → virial -10/-20/-30 eV). ``write_system``
serializes a system directory to relative-POSIX-path → bytes with ``numpy.save`` (never
hand-authored bytes), used by ``_generate.py`` to write the committed fixtures and by the
parser/exporter tests to build systems in memory.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Any

import numpy as np

# Atom order [O, H, H]; type_map "O H"; type.raw "0 1 1". The numbering deliberately is not
# first-appearance-collapsed (which would be the same thing here) — it is the canonical spelling
# every fixture uses, so the carried-numbering round-trip is exercised everywhere.
H2O_COORDS = np.array(
    [
        [0.0, 0.0, 0.0],
        [0.96, 0.0, 0.0],
        [-0.24, 0.93, 0.0],
    ],
    dtype=np.float64,
)
H2O_ENERGY = -14.0
H2O_FORCES = np.array(
    [
        [0.05, 0.02, 0.0],
        [-0.03, 0.01, 0.0],
        [-0.02, -0.03, 0.0],
    ],
    dtype=np.float64,
)
# Row-major 3x3 box: 10 Å cubic.
BOX_FLAT = np.array([10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0], dtype=np.float64)
# -stress·volume with stress = diag(0.01, 0.02, 0.03) eV/Å³ and volume = 1000 Å³.
VIRIAL_FLAT = np.array([-10.0, 0.0, 0.0, 0.0, -20.0, 0.0, 0.0, 0.0, -30.0], dtype=np.float64)


def _npy(values: np.ndarray) -> bytes:
    stream = BytesIO()
    np.save(stream, np.asarray(values, dtype=np.float64), allow_pickle=False)
    return stream.getvalue()


def write_system(
    *,
    coords: Sequence[Any],
    boxes: Sequence[Any],
    energy: Any = None,
    forces: Sequence[Any] | None = None,
    virial: Sequence[Any] | None = None,
    set_splits: Sequence[int] | None = None,
    omit_type_map: bool = False,
    type_map: Sequence[str] = ("O", "H"),
    type_indices: Sequence[int] = (0, 1, 1),
) -> dict[str, bytes]:
    """Build one DeePMD system directory as relative-posix-path → bytes.

    ``set_splits`` (default ``None`` → a single ``set.000``) shards the frames across
    ``set.000``/``set.001``/… in order — the multi-set fixture's train/test layout. A
    ``type_map`` of ``None``-like omission is expressed with ``omit_type_map=True`` (the
    missing-type-map fixture: numeric indices only).
    """
    coord_array = np.asarray(coords, dtype=np.float64)
    n_frames = coord_array.shape[0]
    coord_array = coord_array.reshape((n_frames, -1))
    flat_atoms = coord_array.shape[1]
    assert flat_atoms % 3 == 0
    box_array = np.asarray(boxes, dtype=np.float64)
    assert box_array.shape == (n_frames, 9)
    output: dict[str, bytes] = {
        "type.raw": (" ".join(str(index) for index in type_indices) + "\n").encode(),
    }
    if not omit_type_map:
        output["type_map.raw"] = (" ".join(type_map) + "\n").encode()
    splits = list(set_splits) if set_splits is not None else [n_frames]
    assert sum(splits) == n_frames
    offset = 0
    for set_index, size in enumerate(splits):
        prefix = f"set.{set_index:03d}/"
        output[prefix + "coord.npy"] = _npy(coord_array[offset : offset + size])
        output[prefix + "box.npy"] = _npy(box_array[offset : offset + size])
        if energy is not None:
            energy_array = np.atleast_1d(np.asarray(energy, dtype=np.float64))
            output[prefix + "energy.npy"] = _npy(energy_array[offset : offset + size])
        if forces is not None:
            force_array = np.asarray(forces, dtype=np.float64).reshape((n_frames, -1))
            output[prefix + "force.npy"] = _npy(force_array[offset : offset + size])
        if virial is not None:
            virial_array = np.asarray(virial, dtype=np.float64)
            output[prefix + "virial.npy"] = _npy(virial_array[offset : offset + size])
        offset += size
    return output
