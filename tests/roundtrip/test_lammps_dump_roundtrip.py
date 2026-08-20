"""LAMMPS dump identity round-trips (Part 3 §3): ``dump → Canonical → dump' → Canonical'``. This is
the end-to-end proof that M47's exporter and M46's parser agree — the checkpoint that closes the
staging state and makes ``lammps_dump`` a full read+write format.

Dump identity is deliberately *gainy*, the mirror image of CIF's deliberately *lossy* identity
(D68). A dump conventionally needs a numeric ``type`` column, so the exporter assigns one by first
appearance and **reports it** (the ``LAMMPSDUMP_TYPES_ASSIGNED`` warning, S1). A source that carried
only ``element`` labels therefore comes back with one extra carry, ``lammps_dump:type`` — an audited
augmentation, never a silent one (P1/P4). So this cannot use bare ``assert_scientifically_equal``;
like CIF it pins *which* field is allowed to appear and proves nothing else moved.

Two anchors, because a dump carries two things the earlier formats did not:

* ``metal-ortho-declared`` — declared ``metal`` units + an orthogonal box + velocities + a per-atom
  ``c_pe`` custom column over two frames. Its round-trip proves the unit-style carry
  (``custom_global['lammps_dump:units']``), the velocities, and the custom column all survive.
* ``wrapped-flags-metal`` — image flags (``ix iy iz``). Its round-trip is the S2 symmetry proof:
  the flags written on export come back byte-for-byte, so a dump that carries unwrapping
  information keeps it (D178).

Neither fixture needs a recovery preset — both *declare* their unit style, so ``export`` writes the
``ITEM: UNITS`` header straight from the carry.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np

from tests._format_helpers import assert_scientifically_equal, parse_bytes
from xtalate.conversion import ConversionEngine
from xtalate.exporters.lammps_dump import make_lammps_dump_exporter
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.sdk.image_flags import IMAGE_FLAGS_CARRY_KEY

GOLDEN = Path(__file__).parent.parent / "golden"
_UNITS_KEY = "lammps_dump:units"
_TYPE_KEY = "lammps_dump:type"
_ID_KEY = "lammps_dump:id"
_TYPES_ASSIGNED = "LAMMPSDUMP_TYPES_ASSIGNED"
_METAL = {"ambiguous_units": {"choice": "metal", "parameters": {}}}

_META = GOLDEN / "lammps_dump" / "metal-ortho-declared" / "dump.lammpstrj"
_FLAGS = GOLDEN / "lammps_dump" / "wrapped-flags-metal" / "dump.lammpstrj"


def _write(exporter: object, obj: CanonicalObject) -> bytes:
    buf = io.BytesIO()
    exporter.export(obj, buf)  # type: ignore[attr-defined]
    return buf.getvalue()


def test_lammps_dump_identity_gains_exactly_the_reported_type_carry() -> None:
    parser, exporter = make_lammps_dump_parser(), make_lammps_dump_exporter()
    first = parse_bytes(parser, _META.read_bytes()).canonical
    second = parse_bytes(parser, _write(exporter, first)).canonical

    # The source carried only element labels, so the numeric type carry must not already exist —
    # otherwise "gained" proves nothing.
    assert _TYPE_KEY not in first.user_metadata.custom_per_atom

    # The one and only per-atom carry that appears is the type column, and it is REPORTED — the
    # augmentation is audited, never silent (P1).
    gained = (
        second.user_metadata.custom_per_atom.keys() - first.user_metadata.custom_per_atom.keys()
    )
    assert gained == {_TYPE_KEY}
    assert _TYPE_KEY in second.user_metadata.custom_per_atom
    assert _TYPES_ASSIGNED in {w.code for w in exporter.export_warnings(first)}

    # And the gain stops there. Everything the earlier formats' identity tests would have compared
    # outright is equal: the declared unit style, the velocities, the symbols/positions, and every
    # carried column the source already had.
    assert first.user_metadata.custom_global[_UNITS_KEY] == "metal"
    assert second.user_metadata.custom_global == first.user_metadata.custom_global
    for f0, f1 in zip(first.frames, second.frames, strict=True):
        assert f0.atoms.symbols == f1.atoms.symbols
        assert np.allclose(f0.atoms.positions, f1.atoms.positions)
        assert f0.dynamics.velocities is not None and f1.dynamics.velocities is not None
        assert np.allclose(f0.dynamics.velocities, f1.dynamics.velocities)
    for key, col in first.user_metadata.custom_per_atom.items():
        second_col = second.user_metadata.custom_per_atom[key]
        assert np.array_equal(np.asarray(col), np.asarray(second_col))


def test_lammps_dump_reaches_its_fixed_point_at_the_first_hop() -> None:
    """The practical payoff of the reported type column: hop 1 adds ``lammps_dump:type``, and every
    later hop has nothing left to add. From hop 1 on the round-trip is an exact scientific identity
    — the strong claim that the parser and exporter are true inverses once the type carry exists."""
    parser, exporter = make_lammps_dump_parser(), make_lammps_dump_exporter()
    source = parse_bytes(parser, _META.read_bytes()).canonical
    hop1 = parse_bytes(parser, _write(exporter, source)).canonical
    hop2 = parse_bytes(parser, _write(exporter, hop1)).canonical
    assert _TYPE_KEY in hop1.user_metadata.custom_per_atom
    assert_scientifically_equal(hop1, hop2)


def _atoms_rows(dump_text: str) -> list[list[str]]:
    """The whitespace-split ATOMS data rows of every snapshot (the lines under each
    ``ITEM: ATOMS`` header, up to the next ``ITEM:``)."""
    rows: list[list[str]] = []
    in_atoms = False
    for line in dump_text.splitlines():
        if line.startswith("ITEM: ATOMS"):
            in_atoms = True
            continue
        if line.startswith("ITEM:"):
            in_atoms = False
            continue
        if in_atoms and line.strip():
            rows.append(line.split())
    return rows


def test_lammps_dump_writes_integer_atom_ids_not_floats() -> None:
    """A carried atom id is written as an integer (``1``), never ``1.0``. The parser reads every
    dump column as float64, so the id carry is a float array; formatting it through the float path
    would emit ``1.0`` — which a real LAMMPS reader rejects for the integer id field, and which is a
    ``1``→``1.0`` hand-diff surprise the report never mentions (the litmus test). The id column is
    the first column of these fixtures' ATOMS rows."""
    parser, exporter = make_lammps_dump_parser(), make_lammps_dump_exporter()
    source = parse_bytes(parser, _META.read_bytes()).canonical
    # The fixture really carries an id column — otherwise the check proves nothing.
    assert _ID_KEY in source.user_metadata.custom_per_atom
    written = _write(exporter, source).decode("utf-8")

    rows = _atoms_rows(written)
    assert rows, "the export wrote no ATOMS rows"
    integer = re.compile(r"-?\d+")
    for row in rows:
        assert integer.fullmatch(row[0]), f"id column is not an integer token: {row[0]!r}"


def test_lammps_dump_reports_species_that_first_appear_after_frame_zero() -> None:
    """A species that first appears in a *later* frame is assigned its type and — crucially —
    **reported**. The type map grows by first appearance across the whole trajectory, so the
    ``LAMMPSDUMP_TYPES_ASSIGNED`` audit line must list every species, not only frame 0's; otherwise
    a late species reaches the bytes with an unreported type number (P1). The canonical model fixes
    the atom count across frames (Part 2 §3.2), so the source keeps two atoms throughout and instead
    *swaps* the second species O→H between the frames — H first appears in frame 1."""
    two_frames = (
        b'2\nLattice="4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0" '
        b'Properties=species:S:1:pos:R:3 pbc="T T T"\n'
        b"Si 0.0 0.0 0.0\nO 2.0 2.0 2.0\n"
        b'2\nLattice="4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0" '
        b'Properties=species:S:1:pos:R:3 pbc="T T T"\n'
        b"Si 0.0 0.0 0.0\nH 2.0 2.0 2.0\n"
    )
    registry = default_registry()
    engine = ConversionEngine(registry)
    source = registry.get_parser("extxyz").parse(io.BytesIO(two_frames), filename=None).canonical
    # Frame 0 is Si/O; H first appears in frame 1 — otherwise "after frame zero" proves nothing.
    assert source.frames[0].atoms.symbols == ["Si", "O"]
    assert "H" in source.frames[1].atoms.symbols and "H" not in source.frames[0].atoms.symbols

    result = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="lammps_dump",
        recovery_choices=_METAL,
    )
    assert result.report.status == "completed"
    assert result.output is not None

    # The audit line names the COMPLETE map, including the late H (type 3).
    audit = [w for w in result.report.warnings if w.code == _TYPES_ASSIGNED]
    assert audit, "the type-assignment audit warning is missing"
    assert "type 3 → H" in audit[0].message
    # And the written dump actually carries an H atom under type 3 in the second snapshot (the
    # column layout is ``element type x y z``).
    rows = _atoms_rows(result.output.decode("utf-8"))
    assert any(row[0] == "H" and row[1] == "3" for row in rows)


def test_lammps_dump_identity_preserves_image_flags() -> None:
    """The S2 symmetry proof (D178): image flags written on export re-parse identically, so a dump
    carrying unwrapping information round-trips it rather than losing it."""
    parser, exporter = make_lammps_dump_parser(), make_lammps_dump_exporter()
    first = parse_bytes(parser, _FLAGS.read_bytes()).canonical
    second = parse_bytes(parser, _write(exporter, first)).canonical

    first_flags = np.asarray(first.user_metadata.custom_per_atom[IMAGE_FLAGS_CARRY_KEY])
    second_flags = np.asarray(second.user_metadata.custom_per_atom[IMAGE_FLAGS_CARRY_KEY])
    # The fixture must actually carry a non-trivial flag, or the round-trip proves nothing.
    assert np.any(first_flags != 0.0)
    assert np.array_equal(first_flags, second_flags)
