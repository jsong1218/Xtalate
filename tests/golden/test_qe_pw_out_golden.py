"""qe_pw_out golden fidelity (v1.4 M52-S1/S2; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The
expectations are external truth, not snapshots of parser output — every value below is
hand-computed from the declared unit/sign at the boundary, exactly as the M50 goldens pin
the input parser's.

**M52-S2: the go/no-go cross-layout set.** The same four runs are committed twice — the QE
7.x spelling and the QE 6.x spelling (the documented drift: banner version, ``atomic
species`` capitalization, column widths, an extra diagnostic block) — and both must parse
to **identical** label-complete objects (only the declared program banner differs). That
two-layout agreement, plus the input-parser agreement the cross-check asserts, is the
milestone's go/no-go gate.

**The M52 trap, pinned here.** The output label mappings do not exist in the ``_qe`` core
before M52 — S1 adds them (D195), and these goldens are where they are pinned:

* **Energy** — Ry → eV × ``RY_TO_EV`` = 13.605693122994 (QE's ``RYTOEV``): frame 0 of the
  relax case is −49.12345678 Ry → −668.3586780893389 eV, asserted literally.
* **Forces** — Ry/bohr → eV/Å × 25.71103385054424 (= RYTOEV / bohr_radius_angs): the first
  atom's first component 0.01 Ry/bohr → 0.2571103385054424 eV/Å, asserted literally.
* **Stress** — the 3×3 Ry/bohr³ tensor → **tension-positive** eV/Å³ × 91.8157694288102,
  **sign-flipped** because QE prints compression-positive (the ASE reference reader states
  the sign is "opposite of ase", D195): the printed −0.00001 Ry/bohr³ diagonal maps to
  +0.0009181576942881021 eV/Å³, asserted literally — a parser that skipped or double-applied
  the flip would fail here. The kbar column is the within-file cross-check.
* **Positions** — the declared per-block unit is read, never assumed: the header site table
  (bohr units) converts via QE's exact Bohr radius (2.5 Å lands at 2.49999999999994…), while
  each step's ``ATOMIC_POSITIONS (angstrom)`` card reads as-is (exactly 2.5).

**The other pins.** Species labels O/H resolve through QE's documented label rule; declared
masses promote to ``atoms.masses`` (present-with-value, P3); the initial cell is alat × the
crystal-axes identity (alat = 9.448630664428 bohr → 5.0 Å); the ``vc-relax`` case carries a
per-step ``CELL_PARAMETERS (alat= …)`` card so each frame's cell differs from the initial one;
the ``scf`` case has one frame with forces/stress ``None`` (P3 — absence is never defaulted);
every step's ``total force`` scalar rides the ``QEOUT_UNMAPPED_BLOCK_CARRIED`` carry (P1).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers._qe.labels import (
    FORCES_FACTOR,
    RY_TO_EV,
    STRESS_FACTOR,
)
from xtalate.parsers.qe_pw_out import make_qe_pw_out_parser
from xtalate.sdk import ParseResult

GOLDEN = Path(__file__).parent / "qe_pw_out"

#: The four S1 cases — one canonical QE 7.x layout, read completely.
CASES = ["scf", "relax", "vc-relax", "md"]
#: M52-S2's second-layout set — the same four runs in the QE 6.x spelling.
_SIX_X = [case + "-6x" for case in CASES]

#: The shared H2O setup: O + 2×H in a 5 Å cubic cell (alat = 9.448630664428 bohr).
_CELL = [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]]
_SYMBOLS = ["O", "H", "H"]
_MASSES = [15.999, 1.008, 1.008]


def _source(case: str) -> bytes:
    return (GOLDEN / case / "pw.out").read_bytes()


def _parse(case: str) -> ParseResult:
    return make_qe_pw_out_parser().parse(io.BytesIO(_source(case)), filename="pw.out")


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", _SIX_X)
def test_6x_layout_matches_golden(case: str) -> None:
    """The QE 6.x spelling of each run parses to its hand-verified expectation — the
    go/no-go set's second half (S2)."""
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", CASES)
def test_6x_and_7x_layouts_agree_except_source_code(case: str) -> None:
    """The go/no-go cross-layout agreement: both QE major layouts read the same run to
    **identical** label-complete objects — only the declared program banner (source_code)
    differs. A layout whose scrape diverged from the other's would fail here."""
    seven = json.loads(_parse(case).canonical.model_dump_json())
    six = json.loads(_parse(case + "-6x").canonical.model_dump_json())
    assert seven["simulation"]["source_code"] != six["simulation"]["source_code"]
    seven["simulation"]["source_code"] = six["simulation"]["source_code"]
    assert seven == six


def test_6x_source_code_is_the_declared_6x_banner() -> None:
    obj = _parse("scf-6x").canonical
    assert obj.simulation is not None
    assert obj.simulation.source_code == "Program PWSCF v.6.8 (enter)"


@pytest.mark.parametrize("case", CASES)
def test_golden_carries_the_initial_5a_cubic_cell(case: str) -> None:
    obj = _parse(case).canonical
    frame = obj.frames[0]
    assert frame.cell is not None
    assert frame.cell.pbc == (True, True, True)
    assert frame.cell.lattice_vectors.tolist() == [pytest.approx(row, abs=1e-6) for row in _CELL]


@pytest.mark.parametrize("case", CASES)
def test_golden_resolves_species_labels_and_promotes_masses(case: str) -> None:
    """O/H resolve through QE's documented label rule; declared masses promote to
    atoms.masses (present-with-value, P3); the verbatim declared table rides the carry."""
    obj = _parse(case).canonical
    frame = obj.frames[0]
    assert frame.atoms.symbols == _SYMBOLS
    assert frame.atoms.masses is not None
    assert frame.atoms.masses.tolist() == pytest.approx(_MASSES, abs=1e-12)
    assert obj.user_metadata.custom_global["qe_pw_out:atomic_species"] == {
        "O": [6.0, 15.999, "O( 1.00)"],
        "H": [1.0, 1.008, "H( 1.00)"],
    }
    notes = obj.provenance.parse_notes
    assert any("resolves to element O" in note for note in notes)
    assert any("resolves to element H" in note for note in notes)


def test_scf_run_is_a_single_frame_with_absence_honoured() -> None:
    """An SCF-only run has one energy and no ionic loop — the single frame carries energy
    only; forces/stress are None (P3 — never a defaulted zero) and positions/cell reuse the
    initial configuration."""
    obj = _parse("scf").canonical
    assert obj.frame_count == 1
    frame = obj.frames[0]
    assert frame.dynamics.forces is None
    assert frame.electronic.stress is None
    assert frame.electronic.total_energy == -49.12345678 * RY_TO_EV
    assert frame.atoms.positions[0].tolist() == pytest.approx([2.5, 2.5, 2.5], abs=1e-12)


def test_energy_maps_ry_to_ev_with_qes_rytoev() -> None:
    """The M52 trap: the Ry→eV factor must be QE's own RYTOEV (13.605693122994), hand-pinned —
    a wrong or rounded constant would be a silent scale error at MLIP scale."""
    obj = _parse("relax").canonical
    assert obj.frames[0].electronic.total_energy == pytest.approx(
        -49.12345678 * RY_TO_EV, abs=1e-12
    )
    assert RY_TO_EV == 13.605693122994


def test_forces_map_ry_bohr_to_ev_angstrom() -> None:
    obj = _parse("relax").canonical
    forces = obj.frames[0].dynamics.forces
    assert forces is not None
    # 0.01 Ry/bohr → 0.01 × RYTOEV/bohr_radius_angs eV/Å, literally.
    assert forces[0][0] == pytest.approx(0.01 * FORCES_FACTOR, abs=1e-12)
    assert forces[0][1] == pytest.approx(-0.02 * FORCES_FACTOR, abs=1e-12)


def test_stress_sign_is_verified_not_assumed() -> None:
    """The central D195 pin: QE prints compression-positive (ASE reference reader: 'sign
    convention is opposite'), so the printed −0.00001 Ry/bohr³ diagonal must map to
    **positive** tension-positive eV/Å³ — a skipped or double-applied flip fails here."""
    obj = _parse("relax").canonical
    stress = obj.frames[0].electronic.stress
    assert stress is not None
    assert stress[0][0] == pytest.approx(0.00001 * STRESS_FACTOR, abs=1e-18)
    assert stress[1][1] == pytest.approx(0.00002 * STRESS_FACTOR, abs=1e-18)
    # The off-diagonal mirror (the printed tensor is symmetric): the shared element is
    # 0.00000050 Ry/bohr³ → −0.00000050 × STRESS_FACTOR eV/Å³ (still compression-positive
    # printed, so the same flip applies).
    assert stress[0][1] == pytest.approx(-0.00000050 * STRESS_FACTOR, abs=1e-18)
    assert stress[1][0] == pytest.approx(-0.00000050 * STRESS_FACTOR, abs=1e-18)
    notes = obj.provenance.parse_notes
    assert any("sign-flipped" in note and "compression-positive" in note for note in notes)


def test_vc_relax_carries_a_per_step_cell() -> None:
    """Each vc-relax step's own CELL_PARAMETERS (alat= …) card supplies that step's cell —
    the per-step-cell form — and the alat is read from the card itself, so the drifting
    cells differ from the initial 5 Å one."""
    obj = _parse("vc-relax").canonical
    cells: list[float] = []
    for f in obj.frames:
        assert f.cell is not None
        cells.append(f.cell.lattice_vectors[0][0])
    assert cells[0] == pytest.approx(9.44863066 * 0.52917720859, abs=1e-9)
    assert cells[1] == pytest.approx(9.45000000 * 0.52917720859, abs=1e-9)
    assert cells[2] == pytest.approx(9.44700000 * 0.52917720859, abs=1e-9)


def test_md_is_a_label_complete_trajectory() -> None:
    obj = _parse("md").canonical
    assert obj.frame_count == 5
    assert all(f.dynamics.forces is not None for f in obj.frames)
    assert all(f.electronic.stress is not None for f in obj.frames)
    assert [f.electronic.total_energy for f in obj.frames] == pytest.approx(
        [(-49.0 + 0.01 * i) * RY_TO_EV for i in range(5)]
    )


@pytest.mark.parametrize(
    ("case", "total_forces"),
    [
        ("relax", [0.00141421] * 3),
        ("vc-relax", [0.00141421] * 3),
        ("md", [0.00141421 + 0.0001 * i for i in range(5)]),
    ],
)
def test_unmapped_total_force_carries_with_a_warning(case: str, total_forces: list[float]) -> None:
    """The recognized-but-unmapped per-step 'total force' scalar rides
    user_metadata.custom_per_frame['qe_pw_out:total_force'] with one
    QEOUT_UNMAPPED_BLOCK_CARRIED warning per frame (P1 — kept + reported, never dropped)."""
    result = _parse(case)
    obj = result.canonical
    assert len(obj.frames) == len(result.issues)  # one carry warning per frame
    codes = [i.code for i in result.issues]
    assert codes == ["QEOUT_UNMAPPED_BLOCK_CARRIED"] * obj.frame_count
    assert all(i.severity == "warning" for i in result.issues)
    assert obj.user_metadata.custom_per_frame["qe_pw_out:total_force"] == pytest.approx(
        total_forces
    )


def test_scf_run_carries_no_warnings() -> None:
    assert _parse("scf").issues == []


def test_every_golden_records_the_mappings_in_parse_notes() -> None:
    for case in CASES + _SIX_X:
        notes = _parse(case).canonical.provenance.parse_notes
        assert any("RYTOEV" in note for note in notes)
        assert any("Ry/bohr" in note for note in notes)
        assert any("compression-positive" in note for note in notes)
        assert any("units of alat" in note for note in notes)
        assert any("positions" in note.lower() and "unit" in note.lower() for note in notes)


def test_source_code_is_the_declared_banner() -> None:
    obj = _parse("scf").canonical
    assert obj.simulation is not None
    assert obj.simulation.source_code == "Program PWSCF v.7.2 (enter) (v.7.2)"
