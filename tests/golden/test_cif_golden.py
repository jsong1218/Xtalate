"""CIF golden fidelity and the symmetry-expansion correctness anchors (M18 deliverables 4–5).

The expansion tests in ``tests/parsers/`` prove the machinery does what this project *decided*
it should do. These prove it produces what the *crystallography* says it should, which is a
different claim and the only one that catches a self-consistent misunderstanding: every case
here has an atom count, a formula-unit count Z, and site multiplicities that were published
long before this parser existed.

That external anchoring is the whole design. Rock salt and rutile are not arbitrary fixtures —
they are structures whose answers are known independently, declared as an asymmetric unit plus
operations so that *every* atom past the first two is the expansion's work. A parser that
expands wrongly cannot accidentally agree with them.

The invariants (Part 8 §1.3, ``tests/_invariants.py``) are re-derivations that never touch the
parser's own arithmetic, so an expansion bug cannot satisfy both sides by construction.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from tests._invariants import (
    cell_volume,
    formula_unit_multiple,
    minimum_interatomic_distance,
    stoichiometry,
    volume_from_parameters,
)
from xtalate.parsers.cif import make_cif_parser
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent / "cif"


@dataclass(frozen=True)
class Anchor:
    """A golden case plus the facts the published structure fixes independently of this code."""

    case: str
    source: str
    formula_unit: dict[str, int]
    z: int
    atom_count: int
    multiplicities: list[int]
    operations: int
    parameters: tuple[float, float, float, float, float, float]
    # The shortest interatomic separation in the periodic crystal, Å, counting an atom's own
    # image in a neighbouring cell — which in a cell this small is often the shortest contact.
    minimum_distance: float


ANCHORS = [
    Anchor(
        case="nacl-fm3m",
        source="nacl_fm3m.cif",
        formula_unit={"Na": 1, "Cl": 1},
        z=4,
        atom_count=8,
        multiplicities=[4, 4],
        operations=192,
        parameters=(5.6402, 5.6402, 5.6402, 90.0, 90.0, 90.0),
        # Nearest Na–Cl in rock salt is exactly a/2.
        minimum_distance=2.8201,
    ),
    Anchor(
        case="rutile-p42mnm",
        source="rutile_p42mnm.cif",
        formula_unit={"Ti": 1, "O": 2},
        z=2,
        atom_count=6,
        multiplicities=[2, 4],
        operations=16,
        parameters=(4.5941, 4.5941, 2.9589, 90.0, 90.0, 90.0),
        # Rutile has two distinct Ti–O bonds; the shorter *equatorial* one is the minimum
        # (the apical bond is 1.980 Å). Both fall out of the O free parameter x = 0.30478,
        # which is why this case is sensitive to an operation applied with a wrong translation.
        minimum_distance=1.9487,
    ),
    Anchor(
        case="zno-hexagonal-p1",
        source="zno_hexagonal.cif",
        formula_unit={"Zn": 1, "O": 1},
        z=1,
        atom_count=2,
        multiplicities=[1, 1],
        operations=1,
        parameters=(3.0, 3.0, 5.0, 90.0, 90.0, 120.0),
        # A synthetic cell, so there is no published bond to anchor to: the shortest contact is
        # the a-axis repeat itself (3.0), shorter than the 3.041 Å Zn–O separation.
        minimum_distance=3.0,
    ),
]

IDS = [anchor.case for anchor in ANCHORS]


def _parse(anchor: Anchor) -> CanonicalObject:
    path = GOLDEN / anchor.case / anchor.source
    parser = make_cif_parser()
    return parser.parse(io.BytesIO(path.read_bytes()), filename=anchor.source).canonical


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_parse_matches_golden(anchor: Anchor) -> None:
    expected = (GOLDEN / anchor.case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(anchor), expected)


# --- external anchors (deliverable 4) -------------------------------------------------------


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_expanded_stoichiometry_matches_the_published_formula_units(anchor: Anchor) -> None:
    """The element multiset must be exactly Z formula units — the published number.

    This is the assertion the milestone exists to make true. A dropped operation gives a
    fraction of the atoms and a duplicated one gives a multiple; either way the observed Z
    stops being the published Z, whatever else about the file still looks well-formed.
    """
    symbols = _parse(anchor).frames[0].atoms.symbols
    assert len(symbols) == anchor.atom_count
    assert formula_unit_multiple(symbols, anchor.formula_unit) == anchor.z


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_site_multiplicities_match_the_published_wyckoff_orbits(anchor: Anchor) -> None:
    """Per-site multiplicities are reported, and are the published ones.

    The totals alone cannot distinguish "both sites expanded correctly" from "one over- and one
    under-expanded by compensating amounts", which is why the note carries the split.
    """
    notes = " ".join(_parse(anchor).provenance.parse_notes)
    assert f"Per-site multiplicities: {anchor.multiplicities}" in notes
    assert sum(anchor.multiplicities) == anchor.atom_count


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_the_declared_operations_are_recoverable_from_the_output(anchor: Anchor) -> None:
    """Provenance carries the operations verbatim, so the expansion can be re-derived (D67)."""
    simulation = _parse(anchor).simulation
    assert simulation is not None
    declared = simulation.extra["cif:symmetry_operations"].split("\n")
    assert len(declared) == anchor.operations
    assert "x, y, z" in declared


# --- scientific invariants (deliverable 5, Part 8 §1.3) --------------------------------------


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_cell_volume_agrees_with_the_declared_cell_parameters(anchor: Anchor) -> None:
    """The constructed lattice and the source's own a/b/c/α/β/γ must imply the same volume.

    Two independent derivations of one quantity: a transposed or mis-ordered lattice
    construction changes the vectors while leaving every individual cell parameter intact,
    so this catches what an element-wise comparison against a near-cubic fixture cannot.
    Expansion adds atoms and must never touch the cell, so it holds after expansion too.
    """
    cell = _parse(anchor).frames[0].cell
    assert cell is not None and cell.lattice_vectors is not None
    constructed = cell_volume(cell.lattice_vectors)
    declared = volume_from_parameters(*anchor.parameters)
    assert constructed == pytest.approx(declared, rel=1e-9)


@pytest.mark.parametrize("anchor", ANCHORS, ids=IDS)
def test_no_two_atoms_occupy_the_same_place(anchor: Anchor) -> None:
    """The sharpest expansion check: a merge that failed to fire leaves atoms ~0 Å apart.

    Counts can be made to look right by compensating errors; two atoms on top of each other
    is unphysical under any accounting. The expected minimum is the structure's own published
    nearest-neighbour distance, so this pins the geometry rather than merely excluding zero.
    """
    frame = _parse(anchor).frames[0]
    cell = frame.cell
    lattice = cell.lattice_vectors if cell is not None else None
    shortest = minimum_interatomic_distance(frame.atoms.positions, lattice)
    assert shortest > 0.5, f"atoms {shortest:.4f} Å apart — a special-position merge did not fire"
    assert shortest == pytest.approx(anchor.minimum_distance, abs=1e-3)


# --- the assertions have teeth (the milestone's "done means") --------------------------------


def test_a_truncated_operation_list_produces_detectably_wrong_stoichiometry() -> None:
    """Deleting operations from a golden must break the checks above — the meta-test.

    Every assertion in this module would pass vacuously if expansion quietly returned the
    asymmetric unit and the anchors had been written to match whatever it produced. So the
    rutile fixture is deliberately damaged: dropping the operations carrying a 1/2 translation
    removes the z = 1/2 layer, leaving a file that is still well-formed, still parses, and still
    has the right cell.

    What it produces is the exact reason this milestone insists on Z rather than a formula. The
    truncated structure is **still TiO2** — Ti:O is still exactly 1:2, so a check on the element
    *ratio* passes it without complaint — but there are 3 atoms where the crystal has 6. Half
    the atoms are missing behind a perfectly correct-looking formula. Only the absolute count
    against the published Z of the cell sees it, which is what the invariant asserts.
    """
    source = (GOLDEN / "rutile-p42mnm" / "rutile_p42mnm.cif").read_text()
    kept = [line for line in source.splitlines() if "+1/2" not in line]
    truncated = "\n".join(kept) + "\n"

    parser = make_cif_parser()
    result = parser.parse(io.BytesIO(truncated.encode()), filename="truncated.cif")
    symbols = result.canonical.frames[0].atoms.symbols

    # The damage is invisible to the formula: the ratio is still exactly TiO2.
    counts = stoichiometry(symbols)
    assert counts["O"] == 2 * counts["Ti"]

    # And plainly visible to Z, which is the assertion the goldens actually make.
    assert len(symbols) == 3, "expected half the 6-atom cell"
    assert formula_unit_multiple(symbols, {"Ti": 1, "O": 2}) == 1.0
    with pytest.raises(AssertionError):
        assert formula_unit_multiple(symbols, {"Ti": 1, "O": 2}) == 2
