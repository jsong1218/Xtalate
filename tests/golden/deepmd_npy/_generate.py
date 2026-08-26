"""Regenerate the committed ``deepmd_npy`` golden fixtures (v1.5 M56-S1; Part 8 §3).

``deepmd_npy`` is the first **directory** format: a DeePMD system is a directory of NumPy
files, so the golden source bytes cannot be authored by hand (``numpy.save`` output is not
hand-writable). This script builds each case's system directory from exactly the values the
expectation records, parses it through the real parser to emit ``expected.canonical.json``,
and writes each ``manifest.yaml`` with the two digests it must carry — the source's **tree**
digest (deterministic over sorted relative paths, the governance extension for directory
sources) and the expectation's file digest.

The expectations are still *external truth*, not a blind snapshot: every value fed to
``numpy.save`` here is an exact, hand-chosen quantity (a bent H₂O at round coordinates,
integer-ish box, round energies/forces), and the **virial fixture's** ``virial.npy`` is
hand-computed from a declared stress + cell via the documented stress·volume relation
(``stress = 0.01/0.02/0.03 eV/Å³`` diagonal against a 1000 Å³ box → ``virial = [-10, 0, 0, 0,
-20, 0, 0, 0, -30]`` eV), so each number in ``expected.canonical.json`` is one a reader can
verify by eye. Run from the repo root::

    python tests/golden/deepmd_npy/_generate.py

then commit the regenerated system directories / ``expected.canonical.json`` /
``manifest.yaml`` files if the fixtures changed. This module is governance *scaffolding* (a
``.py`` file), so the corpus coverage check ignores it.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
from tests.golden.deepmd_npy._systems import (  # noqa: E402
    BOX_FLAT,
    H2O_COORDS,
    H2O_ENERGY,
    H2O_FORCES,
    VIRIAL_FLAT,
    write_system,
)

from xtalate.parsers.deepmd_npy import make_deepmd_npy_parser  # noqa: E402

HERE = Path(__file__).parent

# The shared bent H₂O geometry every case builds on: O at the origin, two H at ~0.96 Å with a
# ~104.5° angle, inside a 10 Å cubic box. Atom order [O, H, H] with type_map "O H", type.raw
# "0 1 1" — the numbering is deliberately NOT first-appearance-collapsed so the carried
# numbering round-trip is exercised everywhere.


def _tree_sha256(root: Path) -> str:
    """Deterministic digest over a system directory (sorted relative paths + content digests)."""
    digest = hashlib.sha256()
    for relative in sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256((root / relative).read_bytes()).digest())
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(
    case: str,
    source_dir: Path,
    expected_path: Path,
    notes: str,
) -> None:
    manifest = {
        "case": case,
        "format_id": "deepmd_npy",
        "source_file": source_dir.name,
        "expected_canonical": expected_path.name,
        "canonical_schema_version": "1.0.0",
        "sha256": _tree_sha256(source_dir),
        "expected_sha256": _file_sha256(expected_path),
        "origin": {
            "kind": "synthetic",
            "source": (
                "Hand-authored for M56-S1 via tests/golden/deepmd_npy/_generate.py "
                "(NumPy system-directory layout, written with numpy.save)."
            ),
            "license": "Apache-2.0",
        },
        "notes": notes,
    }
    (source_dir.parent / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=88), encoding="utf-8"
    )


def _write_case(case: str, files: dict[str, bytes], notes: str, *, recover: bool) -> None:
    case_dir = HERE / case
    system_dir = case_dir / "system"
    for path, content in files.items():
        target = system_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    parser = make_deepmd_npy_parser()
    if recover:
        result = parser.parse_recover(
            b"",
            filename="system",
            hint="supply_species",
            choice="species_map",
            parameters={"species": "O H", "directory_files": files},
            recovery_context={"missing_species": {"choice": "species_map", "parameters": {}}},
        )
    else:
        result = parser.parse_dir(files, dirname="system")
    expected_path = case_dir / "expected.canonical.json"
    expected_path.write_text(result.canonical.model_dump_json(indent=2), encoding="utf-8")
    _manifest(case, system_dir, expected_path, notes)


def main() -> None:
    # 1. The matrix anchor: a labeled single-set system (energy + forces, no virial — so every
    #    hop out of it in the round-trip matrix is stress-free and needs no convention choice).
    _write_case(
        "labeled-single-set",
        write_system(
            coords=[H2O_COORDS],
            boxes=[BOX_FLAT],
            energy=H2O_ENERGY,
            forces=[H2O_FORCES],
        ),
        (
            "The round-trip matrix anchor (M56-S2): a labeled single-set H₂O system — one frame, "
            "energy + forces, no virial. Proves the directory read seam, the type_map→species "
            "mapping, the carried type numbering (type_map 'O H' / type.raw '0 1 1' — NOT "
            "first-appearance-collapsed), and that absent labels are None, never zero-filled (P3)."
        ),
        recover=False,
    )
    # 2. Multi-set concatenation: DeePMD's train/test sharding read back as one trajectory, with
    #    the dropped partition reported (DEEPMD_SET_PARTITION_DROPPED) — aggregation, never
    #    curation: the partition is information, so its loss is announced, never silent.
    _write_case(
        "multi-set",
        write_system(
            coords=[
                H2O_COORDS,
                H2O_COORDS + np.array([0.05, 0.0, 0.0]),
                H2O_COORDS + np.array([0.0, 0.05, 0.0]),
            ],
            boxes=[BOX_FLAT, BOX_FLAT, BOX_FLAT],
            energy=[-14.0, -14.05, -14.1],
            forces=[H2O_FORCES, H2O_FORCES + 0.01, H2O_FORCES - 0.01],
            set_splits=[2, 1],  # set.000 holds 2 frames, set.001 holds 1
        ),
        (
            "The multi-set case: the same H₂O trajectory sharded across set.000 (2 frames) and "
            "set.001 (1 frame) the way DeePMD splits train/test partitions. The parser "
            "concatenates set.* in sorted order into one 3-frame trajectory and reports "
            "DEEPMD_SET_PARTITION_DROPPED — the source's partition is information, its loss is "
            "announced (aggregation, never curation)."
        ),
        recover=False,
    )
    # 3. Missing type_map.raw: numeric type indices only → the recoverable
    #    DEEPMD_MISSING_TYPE_MAP, resolved by the existing missing_species scenario (the LAMMPS
    #    numeric-type pattern, third application). The expectation is the *recovered* object.
    _write_case(
        "no-type-map",
        write_system(
            coords=[H2O_COORDS],
            boxes=[BOX_FLAT],
            energy=H2O_ENERGY,
            forces=[H2O_FORCES],
            omit_type_map=True,
        ),
        (
            "The missing-type_map case: type.raw '0 1 1' with no type_map.raw → the recoverable "
            "DEEPMD_MISSING_TYPE_MAP, resolved by the existing missing_species scenario "
            "(species_map, 'O H'). The expectation is the recovered parse — the same object a "
            "'--recover missing_species=species_map,species=O H' conversion produces."
        ),
        recover=True,
    )
    # 4. The virial oracle: virial.npy hand-computed from a declared stress + cell via the
    #    documented stress·volume relation, so the stress↔virial mapping is pinned in both
    #    directions (the S1 go/no-go, inverted by the S2 exporter).
    _write_case(
        "virial-labeled",
        write_system(
            coords=[H2O_COORDS],
            boxes=[BOX_FLAT],
            energy=H2O_ENERGY,
            forces=[H2O_FORCES],
            virial=[VIRIAL_FLAT],
        ),
        (
            "The virial oracle: stress = diag(0.01, 0.02, 0.03) eV/Å³ against a 10×10×10 Å box "
            "(volume 1000 Å³) gives virial = -stress·volume = [-10, 0, 0, 0, -20, 0, 0, 0, -30] "
            "eV, flattened row-major — hand-computed, so the deterministic virial↔stress mapping "
            "(D211) is pinned in both directions: the parser reads virial → stress 0.01/0.02/0.03 "
            "and the exporter writes stress → the same virial.npy bytes."
        ),
        recover=False,
    )
    print(f"Regenerated {len(list(HERE.glob('*/manifest.yaml')))} deepmd_npy golden cases.")


if __name__ == "__main__":
    main()
