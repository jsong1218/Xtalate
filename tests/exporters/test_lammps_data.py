"""LAMMPS data (configuration/restart) exporter — the write side of M48 (v1.3 M48-S2, D181).

These tests pin the exporter as the exact inverse of the M48-S1 parser and prove the invariants the
slice guarantees:

* **Data→data identity round-trips.** Every S1 golden exports and re-parses back to a scientifically
  equal object under the same recovery preset — the restart flagship works for the atomic, charge,
  and full styles, and for the orthogonal and triclinic boxes alike. Like the dump identity (D177),
  the round-trip is deliberately *gainy* only where the format forces it: a data file needs a
  numeric type column, so the exporter assigns one and **reports it**
  (``LAMMPSDATA_TYPES_ASSIGNED``).
* **Topology is written back byte-faithfully.** The ``Bonds``/``Bond Coeffs`` sections a data file
  carried come back byte-for-byte from ``custom_global['lammps_data:topology']`` (M48-S1's carry).
* **A declared-but-unused atom type is preserved.** When S1 folded a type that no atom uses into a
  verbatim ``Masses`` section, the exporter writes that section verbatim (all types) and preserves
  the source's own type numbering, rather than regenerating a table that would drop the unused type.
* **Value-level refusals.** ``unrepresentable`` refuses a multi-frame object, a non-restricted cell,
  a molecule-id without charges, and one element carrying two masses — each a clean refusal, never a
  silent flatten (the engine-level trio lives in ``tests/conversion/test_write_lammps_data.py``).
* **Absence stays absent (P3).** A source with no title writes a blank first line; velocities are
  written only when present.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_scientifically_equal
from xtalate.exporters.lammps_data import make_lammps_data_exporter
from xtalate.parsers.lammps_data import make_lammps_data_parser
from xtalate.schema import CanonicalObject, load_canonical

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_data"
_TYPES_ASSIGNED = "LAMMPSDATA_TYPES_ASSIGNED"
_UNITS_KEY = "lammps_data:units"
_COMMENT_KEY = "lammps_data:comment"
_MOLECULE_KEY = "lammps_data:molecule_id"
_TYPE_KEY = "lammps_data:type"

# Each S1 golden with the recovery preset it was recorded under (mirrors the S1 parser test's
# _CASES): the unit style and the type→symbol species map needed to re-parse the export.
_CASES = {
    "atomic-metal-ortho": ("metal", "1:Ar 2:Ne"),
    "charge-real-velocities": ("real", "1:O 2:H"),
    "full-triclinic-topology": ("metal", "1:C 2:H"),
    "full-no-style-comment": ("metal", "1:Na 2:Cl"),
}


def _load(case: str) -> CanonicalObject:
    return load_canonical((GOLDEN / case / "expected.canonical.json").read_text())


def _export(obj: CanonicalObject) -> bytes:
    buf = io.BytesIO()
    make_lammps_data_exporter().export(obj, buf)
    return buf.getvalue()


def _reparse(written: bytes, units: str, species: str) -> CanonicalObject:
    ctx = {
        "ambiguous_units": {"choice": units, "parameters": {}},
        "missing_species": {"choice": "species_map", "parameters": {"species": species}},
    }
    return (
        make_lammps_data_parser()
        .parse_recover(
            io.BytesIO(written),
            filename="structure.data",
            hint="ambiguous_units",
            choice=units,
            parameters={},
            recovery_context=ctx,
        )
        .canonical
    )


# --- identity round-trips ------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(_CASES))
def test_data_identity_round_trips_scientifically(case: str) -> None:
    """The restart flagship: parse → export → re-parse is scientifically equal for every S1 golden,
    across the atomic/charge/full styles and the orthogonal/triclinic boxes."""
    units, species = _CASES[case]
    obj = _load(case)
    second = _reparse(_export(obj), units, species)
    assert_scientifically_equal(obj, second)


def test_full_style_topology_writes_back_byte_for_byte() -> None:
    """The topology-bearing full-style object restores its ``Bonds`` and ``Bond Coeffs`` sections
    byte-for-byte from the carried payload — the data→data topology write-back."""
    written = _export(_load("full-triclinic-topology")).decode("utf-8")
    source = (GOLDEN / "full-triclinic-topology" / "structure.data").read_text()
    for section in ("Bonds", "Bond Coeffs"):
        assert _section_rows(source, section) == _section_rows(written, section)


def _section_rows(text: str, name: str) -> list[str]:
    """The stripped data rows under a named body section (up to the next keyword/blank block)."""
    keywords = {
        "Masses",
        "Atoms",
        "Velocities",
        "Bonds",
        "Angles",
        "Dihedrals",
        "Impropers",
        "Bond Coeffs",
        "Angle Coeffs",
    }
    rows: list[str] = []
    grabbing = False
    for raw in text.splitlines():
        line = raw.strip()
        head = line.split("#", 1)[0].strip()
        if head == name:
            grabbing = True
            continue
        if grabbing:
            if not line:
                if rows:
                    break
                continue
            if head in keywords:
                break
            rows.append(line)
    return rows


# --- the reported type map (P1) ------------------------------------------------------


def test_type_map_is_assigned_by_first_appearance_and_reported() -> None:
    obj = _load("full-triclinic-topology")
    warnings = make_lammps_data_exporter().export_warnings(obj)
    assert _TYPES_ASSIGNED in {w.code for w in warnings}
    message = next(w.message for w in warnings if w.code == _TYPES_ASSIGNED)
    # full-triclinic carries C then H in first-appearance order → 1→C, 2→H.
    assert "type 1 → C" in message and "type 2 → H" in message


def test_atom_type_column_is_a_bare_integer() -> None:
    """The ``type`` column is a bare integer (``1``), never a float — a real ``read_data`` rejects a
    decimal in the integer type field, and it is a hand-diff surprise the report never mentions."""
    written = _export(_load("atomic-metal-ortho")).decode("utf-8")
    rows = _atom_rows(written)
    assert rows, "no Atoms rows were written"
    for row in rows:
        # atomic layout: id type x y z → the type token is column 1.
        assert row[1].isdigit() or (row[1].startswith("-") and row[1][1:].isdigit())


def _atom_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    grabbing = False
    for raw in text.splitlines():
        if raw.strip().split("#", 1)[0].strip() == "Atoms":
            grabbing = True
            continue
        if grabbing:
            if not raw.strip():
                if rows:
                    break
                continue
            rows.append(raw.split())
    return rows


# --- a declared-but-unused atom type -------------------------------------------------

# Three atom types are declared but only two (C, H) are used; S1 cannot fold the unused type into
# atoms.masses, so it carries a verbatim Masses section (all three rows) into the topology payload.
_UNUSED_TYPE_DATA = b"""unused-type test

4 atoms
3 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

1 12.011
2 1.008
3 15.999

Atoms # atomic

1 1 0.0 0.0 0.0
2 1 1.0 0.0 0.0
3 2 0.0 1.0 0.0
4 2 0.0 0.0 1.0
"""


def test_declared_but_unused_atom_type_is_preserved_verbatim() -> None:
    """A type no atom uses survives the write: the exporter emits the carried ``Masses`` section
    verbatim (all three types, including the unused one) and preserves the source's own type
    numbering — regenerating from ``atoms.masses`` alone would silently drop type 3 (P1)."""
    obj = _reparse(_UNUSED_TYPE_DATA, "metal", "1:C 2:H")
    written = _export(obj).decode("utf-8")
    # The unused third type's mass line survives.
    assert "3 15.999" in written
    # The header still declares three atom types, not a regenerated two, and not doubled.
    assert written.count("atom types") == 1
    assert "3 atom types" in written
    # Its numbering is reported as *preserved*, not freshly assigned.
    warning = next(
        w for w in make_lammps_data_exporter().export_warnings(obj) if w.code == _TYPES_ASSIGNED
    )
    assert "Preserved source" in warning.message


# --- absence stays absent (P3) -------------------------------------------------------


def test_absent_title_writes_a_blank_first_line() -> None:
    obj = _load("atomic-metal-ortho")
    # Remove any carried title → the first line must be blank, never a fabricated default.
    obj.user_metadata.custom_global.pop(_COMMENT_KEY, None)
    written = _export(obj).decode("utf-8")
    assert written.splitlines()[0] == ""


def test_velocities_written_only_when_present() -> None:
    with_vel = _export(_load("charge-real-velocities")).decode("utf-8")
    without_vel = _export(_load("atomic-metal-ortho")).decode("utf-8")
    assert "Velocities" in with_vel
    assert "Velocities" not in without_vel


# --- value-level refusals (unrepresentable) ------------------------------------------


def test_multi_frame_object_is_unrepresentable() -> None:
    import copy

    obj = _load("atomic-metal-ortho")
    second = copy.deepcopy(obj.frames[0])
    second.index = 1
    obj.frames.append(second)
    reason = make_lammps_data_exporter().unrepresentable(obj)
    assert reason is not None and "single configuration" in reason


def test_molecule_id_without_charges_is_unrepresentable() -> None:
    obj = _load("full-triclinic-topology")
    # The full-style object carries a molecule-id; strip its charges → no writable style remains.
    assert _MOLECULE_KEY in obj.user_metadata.custom_per_atom
    obj.frames[0].electronic.charges = None
    reason = make_lammps_data_exporter().unrepresentable(obj)
    assert reason is not None and "molecule-id" in reason


def test_one_symbol_with_two_masses_is_unrepresentable() -> None:
    obj = _load("atomic-metal-ortho")
    symbols = obj.frames[0].atoms.symbols
    masses = np.asarray(obj.frames[0].atoms.masses, dtype=float)
    # The atomic golden has two Ar atoms; give the second a different mass.
    ar_indices = [i for i, s in enumerate(symbols) if s == "Ar"]
    assert len(ar_indices) >= 2
    masses[ar_indices[1]] += 5.0
    obj.frames[0].atoms.masses = masses.tolist()
    reason = make_lammps_data_exporter().unrepresentable(obj)
    assert reason is not None and "more than one mass" in reason


def test_representable_object_returns_none() -> None:
    assert make_lammps_data_exporter().unrepresentable(_load("full-triclinic-topology")) is None


# --- recovery-aware validation: the reparse_recovery hook (D182) ---------------------


def test_reparse_recovery_hands_validation_the_units_and_species() -> None:
    """A data file's output is not self-describing (no unit system, numeric types only), so the
    exporter tells the Validation Engine exactly how to re-read it: the resolved unit style and the
    type→symbol species map — the same choices the conversion recorded — derived from the object it
    wrote, so the re-parse reproduces the write (D181)."""
    obj = _load("full-triclinic-topology")
    ctx = make_lammps_data_exporter().reparse_recovery(obj)
    assert ctx == {
        "ambiguous_units": {"choice": "metal", "parameters": {}},
        "missing_species": {"choice": "species_map", "parameters": {"species": "1:C 2:H"}},
    }
    # And it is the context that actually re-reads this exporter's own bytes back to equality.
    reparsed = _reparse(_export(obj), "metal", "1:C 2:H")
    assert_scientifically_equal(obj, reparsed)


def test_reparse_recovery_species_map_follows_the_written_type_numbering() -> None:
    """The species map is keyed by the same numbering the write used — first appearance (1:O 2:H for
    the charge golden), so validation maps types back to the symbols the exporter actually wrote."""
    ctx = make_lammps_data_exporter().reparse_recovery(_load("charge-real-velocities"))
    assert ctx is not None
    assert ctx["missing_species"]["parameters"] == {"species": "1:O 2:H"}


def test_reparse_recovery_is_none_without_a_resolved_style() -> None:
    """No style on the object → no recovery context: an inconsistent state the engine could not have
    written from, left for validation to surface honestly rather than papered over."""
    obj = _load("atomic-metal-ortho")
    obj.user_metadata.custom_global.pop(_UNITS_KEY, None)
    assert make_lammps_data_exporter().reparse_recovery(obj) is None


# --- guardrails: a write with no resolved style, and defensive backstops -------------


def test_export_without_a_resolved_unit_style_raises() -> None:
    """The exporter refuses to write without a declared style: a data file states no unit system, so
    a guessed default is never acceptable (P4). The engine reaches this state only via the
    ``ambiguous_units`` recovery; a direct call with the key stripped names the fix."""
    obj = _load("atomic-metal-ortho")
    obj.user_metadata.custom_global.pop(_UNITS_KEY, None)
    with pytest.raises(ValueError, match="ambiguous_units"):
        _export(obj)
