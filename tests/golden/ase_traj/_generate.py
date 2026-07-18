"""Regenerate the committed ``ase_traj`` golden fixtures (M14C; Part 8 §3).

``.traj`` is ASE's binary ULM container, so — unlike the hand-writable text fixtures of the other
formats — the golden source bytes cannot be authored by hand. This script builds each case's ASE
``Atoms`` from exactly the values the expectation records, writes the deterministic ``.traj`` bytes
(ASE's ULM writer is byte-stable: no timestamps, no run-to-run entropy — verified below), parses
them through the real parser to emit ``expected.canonical.json``, and prints the two SHA-256 digests
each ``manifest.yaml`` must carry.

The expectations are still *external truth*, not a blind snapshot: every value fed to ``Atoms`` here
is an exact, hand-chosen quantity (integer-ish coordinates, isotope masses, round energies), so each
number in ``expected.canonical.json`` is one a reader can verify by eye against the ``Atoms`` built
below — the ULM container is merely the transport. Run from the repo root::

    python tests/golden/ase_traj/_generate.py

then copy the printed ``sha256`` / ``expected_sha256`` into the manifests if the fixtures changed.
This module is governance *scaffolding* (a ``.py`` file), so the corpus coverage check ignores it.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms
from ase.io.trajectory import TrajectoryWriter

from xtalate.parsers.ase_traj import make_ase_traj_parser

HERE = Path(__file__).parent


def _co_relax_3frame() -> list[Atoms]:
    """Rich all-fields trajectory: a CO molecule relaxing over three frames, each carrying a cell +
    pbc, source-written (isotope) masses, velocities, a FixAtoms constraint, an ``info`` step, and a
    calculator energy + forces. Exercises every mapped canonical field in one fixture."""
    images: list[Atoms] = []
    for i in range(3):
        atoms = Atoms(
            symbols=["C", "O"],
            positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.10 + 0.02 * i]],
            cell=[6.0, 6.0, 6.0],
            pbc=True,
        )
        atoms.set_masses([12.011, 15.999])
        atoms.set_velocities(np.full((2, 3), 0.001 * (i + 1)))
        atoms.set_constraint(FixAtoms(indices=[0]))
        atoms.info["step"] = i
        atoms.calc = SinglePointCalculator(
            atoms, energy=-5.0 - i, forces=np.full((2, 3), 0.01 * (i + 1))
        )
        images.append(atoms)
    return images


def _water_single_molecule() -> list[Atoms]:
    """Minimal molecule + laundering anchor: one isolated water frame with only symbols and
    positions. ASE's manufactured defaults (zero cell, derived masses, zeroed momenta, empty
    constraints) must all launder to ``None``, and a single frame carries no trajectory."""
    return [
        Atoms(
            symbols=["H", "O", "H"],
            positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.98], [0.0, 0.93, -0.26]],
        )
    ]


CASES: dict[str, Callable[[], list[Atoms]]] = {
    "co-relax-3frame": _co_relax_3frame,
    "water-single-molecule": _water_single_molecule,
}


def _write_traj_bytes(images: list[Atoms]) -> bytes:
    buf = io.BytesIO()
    writer = TrajectoryWriter(buf, "w")
    for atoms in images:
        writer.write(atoms)
    return buf.getvalue()


def _generate_case(case: str, build: Callable[[], list[Atoms]]) -> None:
    images = build()
    source = _write_traj_bytes(images)
    # ASE's ULM writer must be byte-deterministic for a committed fixture to be reproducible.
    if source != _write_traj_bytes(build()):
        raise AssertionError(f"{case}: .traj bytes are not reproducible")

    directory = HERE / case
    directory.mkdir(exist_ok=True)
    (directory / "relax.traj").write_bytes(source)

    obj = make_ase_traj_parser().parse(io.BytesIO(source), filename="relax.traj").canonical
    expected = obj.model_dump_json(indent=2) + "\n"
    (directory / "expected.canonical.json").write_text(expected, encoding="utf-8")

    print(f"{case}:")
    print(f"  sha256:          {hashlib.sha256(source).hexdigest()}")
    print(f"  expected_sha256: {hashlib.sha256(expected.encode()).hexdigest()}")


if __name__ == "__main__":
    for case, build in CASES.items():
        _generate_case(case, build)
