"""Regenerate the committed ``h5md`` golden fixtures (M74-S4; Part 8 §3).

H5MD is a binary HDF5 container, so — like the ``.traj`` ULM and ``.db`` SQLite fixtures — the
golden source bytes cannot be authored by hand in a text editor. This script builds each case's
groups with **raw ``h5py``** (deliberately *not* through ``exporters.h5md``, so the golden remains
an independent check on the parser rather than a round-trip of one Xtalate component against
another), writes the deterministic ``.h5`` bytes, parses them through the real parser to emit
``expected.canonical.json``, and writes each ``manifest.yaml`` with the two SHA-256 digests it must
carry.

The expectations are still *external truth*, not a blind snapshot: every value written here is an
exact, hand-chosen quantity (integer-ish coordinates, isotope masses, round energies), so each
number in ``expected.canonical.json`` is one a reader can verify by eye against the arrays built
below. Run from the repo root::

    python tests/golden/h5md/_generate.py

then commit the regenerated ``*.h5`` / ``expected.canonical.json`` / ``manifest.yaml`` if the
fixtures changed. This module is governance *scaffolding* (a ``.py`` file), so the corpus coverage
check ignores it.

HDF5 embeds object modification times by default, which would make the bytes differ on every run;
every dataset here is created with ``track_times=False`` and every group's own object time is pinned
the same way, so the committed fixture is byte-reproducible (``_generate_case`` asserts it).
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from xtalate.parsers.h5md import make_h5md_parser

HERE = Path(__file__).parent


def _dataset(group: h5py.Group, name: str, data: np.ndarray, unit: str | None = None) -> None:
    ds = group.create_dataset(name, data=data, track_times=False)
    if unit is not None:
        ds.attrs["unit"] = unit


def _time_dep(
    parent: h5py.Group, name: str, value: np.ndarray, n_steps: int, unit: str | None = None
) -> h5py.Group:
    """A time-dependent ``{step, time, value}`` element with a regular ``value`` array."""
    group = parent.create_group(name, track_order=False)
    _dataset(group, "step", np.arange(n_steps, dtype=np.int64))
    _dataset(group, "time", np.arange(n_steps, dtype=np.float64))
    _dataset(group, "value", value, unit=unit)
    return group


def _time_dep_vlen(
    parent: h5py.Group,
    name: str,
    rows: list[np.ndarray],
    dtype: object,
    unit: str | None = None,
) -> h5py.Group:
    """A time-dependent element whose ``value`` is a per-step VLEN array — the variable-N layout."""
    group = parent.create_group(name, track_order=False)
    n_steps = len(rows)
    _dataset(group, "step", np.arange(n_steps, dtype=np.int64))
    _dataset(group, "time", np.arange(n_steps, dtype=np.float64))
    value = group.create_dataset(
        "value", shape=(n_steps,), dtype=h5py.vlen_dtype(dtype), track_times=False
    )
    for i, row in enumerate(rows):
        value[i] = row
    if unit is not None:
        value.attrs["unit"] = unit
    return group


def _metadata(f: h5py.File, *, name: str, version: str | None) -> None:
    h5md = f.create_group("h5md", track_order=False)
    h5md.attrs["version"] = np.asarray((1, 1), dtype=np.int64)
    creator = h5md.create_group("creator", track_order=False)
    creator.attrs["name"] = name
    if version is not None:
        creator.attrs["version"] = version


# --- the three cases ------------------------------------------------------------------


def _co2_nvt(f: h5py.File) -> None:
    """All-fields constant-N (N=3) trajectory over 3 frames: a CO2 molecule with per-frame
    positions/velocities/forces/charges, fixed isotope masses, a fixed cubic box, and a
    potential-energy series. Canonical units throughout, so every number round-trips as-is — the
    round-trip matrix source (bare-parses; the full label set flows through every hop)."""
    _metadata(f, name="h5md-tools", version="0.3.1")
    grp = f.create_group("particles/all", track_order=False)
    positions = np.array(
        [
            [[0.0, 0.0, 0.0], [0.0, 0.0, 1.16], [0.0, 0.0, -1.16]],
            [[0.0, 0.0, 0.02], [0.0, 0.0, 1.17], [0.0, 0.0, -1.15]],
            [[0.0, 0.0, -0.01], [0.0, 0.0, 1.18], [0.0, 0.0, -1.17]],
        ]
    )
    _time_dep(grp, "position", positions, 3, unit="Angstrom")
    _dataset(grp, "species", np.array([6, 8, 8], dtype=np.int64))  # C, O, O (fixed-in-time)
    velocities = np.array(
        [
            [[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]],
            [[0.02, 0.0, 0.0], [0.0, 0.02, 0.0], [0.0, 0.0, 0.02]],
            [[0.03, 0.0, 0.0], [0.0, 0.03, 0.0], [0.0, 0.0, 0.03]],
        ]
    )
    _time_dep(grp, "velocity", velocities, 3, unit="Angstrom/fs")
    forces = np.array(
        [
            [[0.0, 0.0, 0.5], [0.0, 0.0, -0.25], [0.0, 0.0, -0.25]],
            [[0.0, 0.0, 0.4], [0.0, 0.0, -0.20], [0.0, 0.0, -0.20]],
            [[0.0, 0.0, 0.3], [0.0, 0.0, -0.15], [0.0, 0.0, -0.15]],
        ]
    )
    _time_dep(grp, "force", forces, 3, unit="eV/Angstrom")
    _dataset(grp, "mass", np.array([12.011, 15.999, 15.999]), unit="u")  # fixed-in-time
    charges = np.array([[0.5, -0.25, -0.25], [0.4, -0.20, -0.20], [0.3, -0.15, -0.15]])
    _time_dep(grp, "charge", charges, 3, unit="e")
    box = grp.create_group("box", track_order=False)
    box.attrs["dimension"] = np.int64(3)
    _dataset(box, "edges", np.array([10.0, 10.0, 10.0]))  # cuboid shorthand -> diagonal cell
    _dataset(box, "boundary", np.array([b"periodic", b"periodic", b"periodic"]))
    obs = f.create_group("observables", track_order=False)
    _time_dep(obs, "potential_energy", np.array([-100.0, -100.5, -100.2]), 3, unit="eV")


def _gcmc_variable_n(f: h5py.File) -> None:
    """A grand-canonical (variable-N) trajectory: 2, then 3, then 4 argon atoms over 3 frames,
    written with per-step VLEN ``position``/``species``/``velocity`` — the M72/M73 variable-N
    engines proven on a committed binary file. Carries a potential-energy series plus a
    ``temperature`` observable (→ ``custom_per_frame['h5md:temperature']``) in a fixed cubic box."""
    _metadata(f, name="gcmc-sampler", version=None)
    grp = f.create_group("particles/all", track_order=False)
    positions = [
        np.array([0.0, 0.0, 0.0, 3.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 3.0, 0.0]),
        np.array([0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 3.0]),
    ]
    _time_dep_vlen(grp, "position", positions, np.float64, unit="Angstrom")
    species = [
        np.array([18, 18], dtype=np.int64),
        np.array([18, 18, 18], dtype=np.int64),
        np.array([18, 18, 18, 18], dtype=np.int64),
    ]
    _time_dep_vlen(grp, "species", species, np.int64)
    velocities = [
        np.array([0.01, 0.0, 0.0, 0.0, 0.01, 0.0]),
        np.array([0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]),
        np.array([0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01, 0.02, 0.0, 0.0]),
    ]
    _time_dep_vlen(grp, "velocity", velocities, np.float64, unit="Angstrom/fs")
    box = grp.create_group("box", track_order=False)
    box.attrs["dimension"] = np.int64(3)
    _dataset(box, "edges", np.array([12.0, 12.0, 12.0]))
    obs = f.create_group("observables", track_order=False)
    _time_dep(obs, "potential_energy", np.array([-5.0, -7.5, -10.0]), 3, unit="eV")
    _time_dep(obs, "temperature", np.array([300.0, 300.0, 300.0]), 3)  # no unit -> carried verbatim


def _npt_triclinic(f: h5py.File) -> None:
    """A constant-N (N=2) run whose *cell* varies between frames: a time-dependent ``box/edges``
    with a full 3x3 matrix per step (frame 1 is sheared to triclinic), exercising the
    time-dependent box reader and the 3x3 ``edges`` path plus the ``/h5md/creator`` note."""
    _metadata(f, name="lammps-h5md", version="2Aug2023")
    grp = f.create_group("particles/all", track_order=False)
    positions = np.array(
        [
            [[0.0, 0.0, 0.0], [1.36, 1.36, 1.36]],
            [[0.0, 0.0, 0.0], [1.38, 1.36, 1.40]],
        ]
    )
    _time_dep(grp, "position", positions, 2, unit="Angstrom")
    _dataset(grp, "species", np.array([14, 14], dtype=np.int64))  # Si, Si (fixed-in-time)
    box = grp.create_group("box", track_order=False)
    box.attrs["dimension"] = np.int64(3)
    edges = np.array(
        [
            [[5.43, 0.0, 0.0], [0.0, 5.43, 0.0], [0.0, 0.0, 5.43]],
            [[5.50, 0.0, 0.0], [0.10, 5.50, 0.0], [0.0, 0.0, 5.60]],
        ]
    )
    _time_dep(box, "edges", edges, 2)
    _dataset(box, "boundary", np.array([b"periodic", b"periodic", b"periodic"]))
    obs = f.create_group("observables", track_order=False)
    _time_dep(obs, "potential_energy", np.array([-10.8, -10.6]), 2, unit="eV")


@dataclass(frozen=True)
class Case:
    build: Callable[[h5py.File], None]
    notes: str


CASES: dict[str, Case] = {
    "co2-nvt-3frame": Case(
        build=_co2_nvt,
        notes=(
            "The all-fields constant-N anchor: a CO2 molecule over 3 frames carrying per-frame "
            "positions, velocities, forces and charges, fixed isotope masses, a fixed cubic box, "
            "and a potential-energy series, all in canonical units so nothing is converted. Proves "
            "the field map (position/species/velocity/force/mass/charge/box/observables) end to "
            "end and that a fixed-in-time species/mass dataset and a cuboid-shorthand box read "
            "correctly. Enrolled as the round-trip matrix source."
        ),
    ),
    "gcmc-variable-n-3frame": Case(
        build=_gcmc_variable_n,
        notes=(
            "The variable-N anchor: a grand-canonical run of 2, 3, then 4 argon atoms written with "
            "per-step VLEN position/species/velocity — the M72/M73 variable-N engines on a "
            "committed binary file, each frame read at its own atom count (P3). A non-energy "
            "'temperature' observable carries to custom_per_frame['h5md:temperature'] "
            "(carry, never interpret), and the potential-energy series maps to total_energy."
        ),
    ),
    "npt-triclinic-2frame": Case(
        build=_npt_triclinic,
        notes=(
            "The time-dependent-box anchor: a 2-atom cell that shears to triclinic between frames, "
            "written as a time-dependent box/edges group with a full 3x3 matrix per step. It "
            "exercises the time-dependent box reader, the 3x3 edges path, and the /h5md/creator "
            "provenance note. Bare positions + fixed species otherwise, so only the cell varies."
        ),
    ),
}


_MANIFEST = """\
case: {case}
format_id: h5md
source_file: {source}
expected_canonical: expected.canonical.json
canonical_schema_version: "2.0.0"
sha256: "{sha256}"
expected_sha256: "{expected_sha256}"
origin:
  kind: synthetic
  source: >-
    Hand-authored for M74-S4 via tests/golden/h5md/_generate.py (raw h5py, HDF5 container).
  license: "Apache-2.0"
notes: >-
  {notes}
"""


def _write_h5_bytes(build: Callable[[h5py.File], None]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".h5") as tmp:
        with h5py.File(tmp.name, "w") as f:
            build(f)
        return Path(tmp.name).read_bytes()


def _generate_case(case: str, spec: Case) -> None:
    source = _write_h5_bytes(spec.build)
    # HDF5 output must be byte-deterministic for a committed fixture to be reproducible.
    if source != _write_h5_bytes(spec.build):
        raise AssertionError(f"{case}: .h5 bytes are not reproducible")

    directory = HERE / case
    directory.mkdir(exist_ok=True)
    source_name = "sample.h5"
    (directory / source_name).write_bytes(source)

    obj = make_h5md_parser().parse(io.BytesIO(source), filename=source_name).canonical
    expected = obj.model_dump_json(indent=2) + "\n"
    (directory / "expected.canonical.json").write_text(expected, encoding="utf-8")

    manifest = _MANIFEST.format(
        case=case,
        source=source_name,
        sha256=hashlib.sha256(source).hexdigest(),
        expected_sha256=hashlib.sha256(expected.encode()).hexdigest(),
        notes=" ".join(spec.notes.split()),
    )
    (directory / "manifest.yaml").write_text(manifest, encoding="utf-8")
    print(f"{case}: wrote {source_name} + expected.canonical.json + manifest.yaml")


if __name__ == "__main__":
    for case, spec in CASES.items():
        _generate_case(case, spec)
