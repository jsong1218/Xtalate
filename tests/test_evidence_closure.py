"""Evidence closure (M75; IMPLEMENTATION_PLAN_v2.0 §M75 deliverable 4).

For every refusal class the ladder recorded since v1.3 — "this trajectory is real and we cannot
represent it, here is why" — this suite demonstrates it is now either **convertible** (a named
variable-N asset parses to a per-frame-N object and converts+validates to a variable-N-capable
target) or **still refused with a reason** (a constant-N-only target refuses at pre-flight and
offers ``frame_selection``). The v1.3–v1.8 evidence file is closed here as committed test assets,
not deleted: schema 2.0.0 (M72) lifted the constant-N invariant and M73 retired the reader
refusals, so the four classes that used to raise ``*_VARIABLE_ATOM_COUNT`` / ``ASEDB_MULTIPLE_ROWS``
now read through, while the honest way out for a format that truly cannot hold a per-frame-N
trajectory is unchanged (P1/P3 — never a silent pad, mask, or truncate).

The variable-N sources are the real M73 evidence: two committed files (the ``h5md`` grand-canonical
golden and the ``lammps_dump`` deposition wild case) and two built exactly as their M73 parser
tests build them (a variable-N extXYZ trajectory and a mixed-composition multi-row ASE ``.db``).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from ase import Atoms
from ase.db import connect

from tests.roundtrip._matrix import FIXED_PRESETS
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_STRICT = ToleranceProfile.named("strict")

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent
_H5MD = _TESTS / "golden" / "h5md" / "gcmc-variable-n-3frame" / "sample.h5"
_LAMMPS = _TESTS / "wild" / "lammps" / "dump-variable-n-deposition" / "dump.lammpstrj"

# A loader yields (bytes, filename) for a source; file-based ones read the committed asset, the two
# constructed ones build the same evidence their M73 parser tests do (a tmp dir is passed for the
# ASE ``.db``, which the library writes as a real SQLite file).
_Loader = Callable[[Path], tuple[bytes, str]]


def _read(path: Path) -> _Loader:
    def _loader(_tmp: Path) -> tuple[bytes, str]:
        return path.read_bytes(), path.name

    return _loader


def _extxyz_variable_n(_tmp: Path) -> tuple[bytes, str]:
    # The exact bytes tests/parsers/test_extxyz.py uses: 1 atom, then 2 (once a refusal).
    data = (
        b"1\nProperties=species:S:1:pos:R:3\nH 0 0 0\n"
        b"2\nProperties=species:S:1:pos:R:3\nH 0 0 0\nH 1 0 0\n"
    )
    return data, "variable_n.xyz"


def _asedb_multirow(tmp_path: Path) -> tuple[bytes, str]:
    # The exact rows tests/parsers/test_ase_db.py::_two_rows builds: H2 then He — a genuinely
    # variable-N *and* mixed-composition multi-row database (once ASEDB_MULTIPLE_ROWS).
    path = tmp_path / "multirow.db"
    db = connect(str(path), use_lock_file=False)
    db.write(
        Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]]), key_value_pairs={"label": "a"}
    )
    db.write(Atoms("He", positions=[[0.0, 0.0, 0.0]]), key_value_pairs={"label": "b"})
    return path.read_bytes(), "multirow.db"


# Each row: (label, source_format, loader). Every one used to be a recorded refusal since v1.3.
_RETIRED: list[tuple[str, str, _Loader]] = [
    ("h5md grand-canonical (2->3->4 atoms)", "h5md", _read(_H5MD)),
    ("lammps deposition dump (3->4->4 atoms)", "lammps_dump", _read(_LAMMPS)),
    ("extxyz variable-N trajectory (1->2 atoms)", "extxyz", _extxyz_variable_n),
    ("ase_db multi-row (H2 then He)", "ase_db", _asedb_multirow),
]

# Constant-N-only write targets: none can express a per-frame-N trajectory, so each must refuse a
# variable-N source at pre-flight and offer frame_selection — the honest way out.
_CONSTANT_N_TARGETS = ["poscar", "contcar", "xdatcar", "cif"]


@pytest.mark.parametrize(("label", "source_fmt", "loader"), _RETIRED, ids=[r[0] for r in _RETIRED])
def test_retired_refusal_now_converts(
    label: str, source_fmt: str, loader: _Loader, tmp_path: Path
) -> None:
    data, filename = loader(tmp_path)
    source = _REGISTRY.get_parser(source_fmt).parse(io.BytesIO(data), filename=filename).canonical
    counts = {len(f.atoms.symbols) for f in source.frames}
    assert len(counts) > 1, f"{label}: source is not variable-N (counts {sorted(counts)})"

    result = _ENGINE.convert(
        source,
        source_format_id=source_fmt,
        target_format_id="extxyz",
        mode="permissive",
        recovery_choices=FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    assert result.report.status != "refused", f"{label}: refused — {result.report.refusal}"
    assert result.validation is not None, f"{label}: no validation report"
    problems = [
        (c.check_id, c.status)
        for c in result.validation.checks
        if c.status not in ("pass", "skipped")
    ]
    assert result.validation.status == "passed", f"{label}: validation not passed — {problems}"


@pytest.mark.parametrize("target", _CONSTANT_N_TARGETS)
def test_constant_n_target_still_refuses_variable_n_with_reason(target: str) -> None:
    source = (
        _REGISTRY.get_parser("h5md").parse(io.BytesIO(_H5MD.read_bytes()), filename=_H5MD.name)
    ).canonical
    # Every gap resolved *except* the atom count, so a refusal can only be about variable N.
    presets = {k: v for k, v in FIXED_PRESETS.items() if k != "frame_selection"}
    result = _ENGINE.convert(
        source,
        source_format_id="h5md",
        target_format_id=target,
        mode="permissive",
        recovery_choices=presets,
        tolerance_profile=_STRICT,
    )
    assert result.report.status == "refused", (
        f"{target}: a constant-N target did not refuse a variable-N source "
        f"(status {result.report.status}) — a silent pad/truncate would look exactly like this"
    )
    assert result.report.refusal is not None
    offered = {s["scenario"] for s in result.report.refusal["unresolved_scenarios"]}
    assert "frame_selection" in offered, (
        f"{target}: refused but frame_selection not offered ({offered})"
    )


def test_no_code_path_pads_masks_or_truncates_n() -> None:
    # A structural companion to the behavioural matrix (S3): the no-ghost-atoms rule (M73) is
    # citable, so no engine code may fabricate, mask, or drop atoms to fit a constant-N target.
    # This asserts the *absence* of such a path by construction — a grep guard over the source tree.
    src = _REPO / "src" / "xtalate"
    tokens = ("pad_to_n", "mask_atoms", "ghost_atom", "truncate_atoms")
    offenders = [
        str(path.relative_to(_REPO))
        for path in src.rglob("*.py")
        if any(token in path.read_text(encoding="utf-8") for token in tokens)
    ]
    assert not offenders, f"ghost-atom-shaped code path found: {offenders}"
