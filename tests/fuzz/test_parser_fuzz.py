"""Parser fuzz seed corpus — the graceful-failure contract on malformed input (M37; R6).

R6 calls parser fuzzing a *permanent maintenance duty*; M37 is its scheduled instance (Part 9
§5.3). This module is the reviewable **seed corpus**: a curated, deterministic battery of malformed
bytes fed to every built-in parser, asserting the one invariant a robust parser must uphold on
adversarial input —

    a parse of arbitrary bytes yields **either** a valid ``ParseResult`` **or** a ``ParseError``,
    and **nothing else**: no ``ValueError``/``KeyError``/``UnicodeDecodeError`` leaking through, no
    unhandled crash, no hang, no unbounded allocation.

That is the "files are data, never code / parsers fail through the §5 error contract" claim made
concrete (the same contract ``tests/parsers/test_xyz.py`` asserts for one case — "non-text bytes
must fail through the ParseError contract, not a raw UnicodeDecodeError"), generalized across all
seven Phase-1 formats.

**Why deterministic seeds, not random mutation.** A seed corpus is reproducible and reviewable, and
it cannot turn a benign CI run red on a mutation no one has seen — the property tests (D50) already
own randomized generation, over *valid* Canonical Objects. Continuous coverage-guided /
random-mutation fuzzing is the documented gap this corpus seeds toward, ticketed in the M37 review
(``docs/security/REVIEW_M37.md``), not attempted here. If a seed ever trips a *non*-graceful outcome
that is a genuine robustness defect — record it as a regression seed and fix the parser, never
weaken the assertion to hide it.

The corpus drives :func:`xtalate.parsers.builtin_parsers` — the seven first-party parsers only, so
the run is independent of whatever third-party plugins happen to be installed.
"""

from __future__ import annotations

import io

import pytest

from xtalate.parsers import builtin_parsers
from xtalate.sdk import ParseError, ParseResult
from xtalate.sdk.plugins import ParserPlugin

# A generic battery every parser must survive — the shapes that most often break a hand-written
# parser: nothing at all, raw binary, mis-declared sizes, non-UTF-8 text, and a pathologically large
# count/line that must fail on EOF rather than pre-allocate.
_GENERIC: dict[str, bytes] = {
    "empty": b"",
    "nulls": b"\x00" * 8,
    "binary_garbage": bytes(range(256)) * 4,
    "utf16_bom": b"\xff\xfe" + "hello world".encode("utf-16-le"),
    "huge_count": b"999999999\ncomment\n",  # a count 9 orders past the body: EOF, not an OOM.
    "text_lines": b"not a real chemistry file\njust some words\n1 2 3\n",
    "one_token": b"42",
    "whitespace": b"   \n\t\n   \n",
    "long_line": b"A" * 200_000 + b"\n",
}

# Format-tailored malformations: a plausible header with a broken body, per format. These reach past
# the sniff/first-line guards into each parser's record-level parsing, where the interesting
# robustness edges live.
#: A minimal but well-formed vasprun.xml header (one atom, one species, no closing tag) and one
#: complete ``<calculation>`` step — building blocks for the vasprun tailored seeds below.
_VASPRUN_HEAD = (
    b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<vasprun>\n'
    b'<generator>\n  <i name="program" type="string" >vasp.5.4.4</i>\n</generator>\n'
    b'<atominfo>\n  <array name="atomtypes">\n    <dimension>2</dimension>\n'
    b"    <field> mass </field>\n    <field> Z </field>\n    <field> psp </field>\n"
    b"    <v> 1.008 1.0 8 </v>\n    <set>\n      <rcmax> 3.0 </rcmax>\n    </set>\n  </array>\n"
    b'  <array name="atoms">\n    <dimension>2</dimension>\n'
    b"    <field> vasp_x </field>\n    <field> vasp_y </field>\n    <field> vasp_z </field>\n"
    b"    <field> atom_type </field>\n    <set>\n      <rcmax> 3.0 </rcmax>\n"
    b"      <c> 0.0 0.0 0.0 1 </c>\n    </set>\n  </array>\n</atominfo>\n"
    b'<structure name="initialpos" >\n  <crystal>\n    <varray name="basis" >\n'
    b"      <v> 4.0 0.0 0.0 </v>\n      <v> 0.0 4.0 0.0 </v>\n      <v> 0.0 0.0 4.0 </v>\n"
    b"    </varray>\n  </crystal>\n"
    b'  <varray name="positions" >\n    <v> 0.0 0.0 0.0 </v>\n  </varray>\n</structure>\n'
)

_VASPRUN_CALC = (
    b'<calculation>\n  <energy>\n    <i name="e_0_energy" type="float" > -12.5 </i>\n  </energy>\n'
    b'  <varray name="forces" >\n    <v> 0.1 0.0 0.0 </v>\n    <v> -0.1 0.0 0.0 </v>\n  </varray>\n'
    b"</calculation>\n"
)

#: A minimal-but-parseable OUTCAR header (one H atom, 10 A cubic cell) — the building block for the
#: OUTCAR tailored seeds below.
_OUTCAR_HEAD = (
    b" vasp.6.3.2 08Feb23\n\n"
    b"  VRHFIN =H: 1s1\n"
    b"  ions per type = 1\n\n"
    b"  direct lattice vectors\n"
    b"  10 0 0 0.1 0 0\n"
    b"  0 10 0 0 0.1 0\n"
    b"  0 0 10 0 0 0.1\n\n"
)

_TAILORED: dict[str, list[tuple[str, bytes]]] = {
    "deepmd_npy": [("directory_marker", b"type.raw\n0\nset.000/coord.npy")],
    "xyz": [
        ("count_gt_atoms", b"5\ncomment\nH 0 0 0\nH 1 1 1\n"),
        ("nonnumeric_coord", b"1\nc\nH x y z\n"),
        ("count_not_int", b"abc\nc\nH 0 0 0\n"),
    ],
    "extxyz": [
        ("bad_lattice", b'2\nLattice="1 2 3" Properties=species:S:1:pos:R:3\nH 0 0 0\nH 1 1 1\n'),
        ("bad_properties", b"1\nProperties=garbage\nH 0 0 0\n"),
    ],
    "poscar": [
        ("bad_scale", b"c\nNOTFLOAT\n1 0 0\n0 1 0\n0 0 1\nH\n1\nDirect\n0 0 0\n"),
        ("counts_mismatch", b"c\n1.0\n1 0 0\n0 1 0\n0 0 1\nH O\n1\nDirect\n0 0 0\n"),
        ("short_lattice", b"c\n1.0\n1 0 0\n0 1 0\nH\n1\nDirect\n0 0 0\n"),
    ],
    "contcar": [
        ("bad_scale", b"c\nNOTFLOAT\n1 0 0\n0 1 0\n0 0 1\nH\n1\nDirect\n0 0 0\n"),
    ],
    "xdatcar": [
        ("no_config", b"c\n1.0\n1 0 0\n0 1 0\n0 0 1\nH\n1\n"),
        ("bad_lattice", b"c\n1.0\nx y z\n0 1 0\n0 0 1\nH\n1\nDirect config= 1\n0 0 0\n"),
    ],
    "cif": [
        ("unterminated_loop", b"data_x\nloop_\n_atom_site_label\n"),
        ("bad_number", b"data_x\n_cell_length_a NOTANUMBER\n"),
        ("empty_data", b"data_x\n"),
    ],
    "ase_traj": [
        ("truncated_pickle", b"\x80\x04\x95\x00\x00garbage"),
        ("text_as_traj", b"- Trajectory\nnot really\n"),
    ],
    "vasprun": [
        ("no_calculation_steps", _VASPRUN_HEAD + b"</vasprun>\n"),
        (
            "unclosed_root",
            b'<vasprun>\n<generator>\n  <i name="program" type="string" >vasp.5.4.4</i>\n'
            b"</generator>\n",
        ),
        (
            "truncated_mid_calculation",
            _VASPRUN_HEAD
            + _VASPRUN_CALC
            + b'<calculation>\n<energy>\n<i name="e_0_energy" type="float" > -13.0 </i>\n',
        ),
        (
            "nonnumeric_energy",
            _VASPRUN_HEAD
            + b'<calculation>\n<energy>\n<i name="e_0_energy" type="float" > NOTANUMBER </i>\n'
            + b"</energy>\n"
            + b'<varray name="forces" >\n<v> 0.1 0.0 0.0 </v>\n<v> -0.1 0.0 0.0 </v>\n'
            + b"</varray>\n</calculation>\n</vasprun>\n",
        ),
    ],
    "outcar": [
        ("no_force_table", _OUTCAR_HEAD + b"  energy(sigma->0) = -1.0\n"),
        (
            "nonnumeric_force_row",
            _OUTCAR_HEAD
            + b"  energy(sigma->0) = -1.0\n\n"
            + b"  POSITION  TOTAL-FORCE (eV/Angst)\n  ---\n  x y z fx fy fz\n",
        ),
        (
            "nions_mismatch",
            _OUTCAR_HEAD
            + b"  NIONS = 2\n"
            + b"  energy(sigma->0) = -1.0\n\n"
            + b"  POSITION  TOTAL-FORCE (eV/Angst)\n  ---\n  0 0 0 0 0 0\n",
        ),
    ],
    # M46-S2: the LAMMPS dump parser — a plausible ITEM: block header with a broken body,
    # reaching past the sniff guard into the block/record-level parsing edges.
    "lammps_dump": [
        ("header_only", b"ITEM: TIMESTEP\n0\n"),  # no NUMBER OF ATOMS -> malformed header.
        ("bad_item", b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n2\nITEM: XYZ\n"),
        (
            "no_box_flags",
            b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n1\n"
            + b"ITEM: BOX BOUNDS\n0 10\n0 10\n0 10\n",
        ),  # noqa: E501
        (
            "triclinic_missing_tilt",
            b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n1\n"
            + b"ITEM: BOX BOUNDS xy xz yz pp pp pp\n0 28\n0 12\n0 10\n",
        ),
        (
            "short_data_block",
            b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n3\nITEM: UNITS metal\n"
            + b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
            + b"ITEM: ATOMS id element x y z\n1 Si 1.0 2.0 3.0\n2 O 4.0 5.0 6.0\n",
        ),
        (
            "nonnumeric_coordinate",
            b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n1\nITEM: UNITS metal\n"
            + b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
            + b"ITEM: ATOMS id element x y z\n1 Si oops 2.0 3.0\n",
        ),
        (
            "invalid_element",
            b"ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n1\nITEM: UNITS metal\n"
            + b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
            + b"ITEM: ATOMS id element x y z\n1 Xx 1.0 2.0 3.0\n",
        ),
    ],
    # M48-S1: the LAMMPS data parser — a plausible box header (a line ending in "xlo xhi" clears
    # the sniff guard) with a broken body, reaching the header/section-reader edges that raise
    # MALFORMED before the recovery refusals ever fire.
    "lammps_data": [
        # box + counts but no Atoms section at all.
        (
            "no_atoms_section",
            b"comment\n1 atoms\n1 atom types\n0.0 10.0 xlo xhi\n"
            + b"0.0 10.0 ylo yhi\n0.0 10.0 zlo zhi\n",
        ),
        # an xlo xhi line carrying a single bound instead of two.
        (
            "short_box_line",
            b"comment\n1 atoms\n1 atom types\n0.0 xlo xhi\n"
            + b"0.0 10.0 ylo yhi\n0.0 10.0 zlo zhi\n",
        ),
        # a header that declares zero atoms — a data file must state at least one.
        (
            "zero_atoms",
            b"comment\n0 atoms\n1 atom types\n0.0 10.0 xlo xhi\n"
            + b"0.0 10.0 ylo yhi\n0.0 10.0 zlo zhi\nAtoms # atomic\n",
        ),
        # non-numeric box bounds on the xlo xhi line.
        (
            "nonnumeric_box",
            b"comment\n1 atoms\n1 atom types\nlo hi xlo xhi\n"
            + b"0.0 10.0 ylo yhi\n0.0 10.0 zlo zhi\n",
        ),
    ],
    # M50-S1: the pw.x input parser — plausible namelist/card skeletons whose bodies break in
    # different places, reaching the namelist-scanner and card-reader edges that raise MALFORMED.
    "qe_pw_in": [
        # no CELL_PARAMETERS at all for ibrav = 0 (the explicit-cell path requires it).
        (
            "missing_cell",
            b"&CONTROL\n  calculation = 'scf'\n/\n&SYSTEM\n  ibrav = 0\n"
            + b"  nat = 1\n  ntyp = 1\n/\nATOMIC_POSITIONS (angstrom)\nSi 0.0 0.0 0.0\n",
        ),
        # an ATOMIC_POSITIONS unit that is not in the QE unit table.
        (
            "bad_positions_unit",
            b"&CONTROL\n/\n&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n/\n"
            + b"CELL_PARAMETERS (angstrom)\n1 0 0\n0 1 0\n0 0 1\n"
            + b"ATOMIC_POSITIONS (furlong)\nSi 0.0 0.0 0.0\n",
        ),
        # CELL_PARAMETERS with only two rows instead of three.
        (
            "short_cell_parameters",
            b"&CONTROL\n/\n&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n/\n"
            + b"CELL_PARAMETERS (angstrom)\n1 0 0\n0 1 0\n"
            + b"ATOMIC_POSITIONS (angstrom)\nSi 0.0 0.0 0.0\n",
        ),
        # namelists before any card, so the header scan never finds an &-opener.
        (
            "no_namelist",
            b"ATOMIC_POSITIONS (angstrom)\nSi 0.0 0.0 0.0\n",
        ),
        # an &SYSTEM namelist that never reaches its closing / before the next card.
        (
            "unclosed_namelist",
            b"&SYSTEM\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
            + b"ATOMIC_POSITIONS (angstrom)\nSi 0.0 0.0 0.0\n",
        ),
    ],
    # M55-S1: the ASE .db parser — the SQLite magic clears the sniff hint, so these reach the
    # ase.db open/read path where every ASE exception type is normalised to ASEDB_MALFORMED.
    "ase_db": [
        # the 16-byte SQLite magic and nothing else — a header with no page data behind it.
        ("magic_only", b"SQLite format 3\x00"),
        # the magic followed by garbage where the first page should be — a corrupt database.
        ("truncated_after_magic", b"SQLite format 3\x00" + b"\xff" * 64),
        # a SQLite file that is valid SQLite but not an ASE schema (no ase-db tables).
        ("sqlite_wrong_schema", b"SQLite format 3\x00" + bytes(range(16, 100))),
    ],
    "qe_pw_out": [
        # a real PWSCF banner but nothing recognizable after it — the record-level refuse.
        ("banner_only", b"Program PWSCF v.7.2 (enter)\nstarting calculation\n" + b"\x00" * 16),
        # CELL_PARAMETERS with only two rows instead of three.
        (
            "short_cell_parameters",
            b"Program PWSCF v.7.2 (enter)\n\n"
            + b"CELL_PARAMETERS (alat= 5.00000000)\n1 0 0\n0 1 0\n"
            + b"ATOMIC_POSITIONS (angstrom)\nSi 0.0 0.0 0.0\n",
        ),
        # an ATOMIC_POSITIONS row whose coordinate is not a number.
        (
            "nonnumeric_position",
            b"Program PWSCF v.7.2 (enter)\n\n"
            + b"CELL_PARAMETERS (alat= 5.00000000)\n1 0 0\n0 1 0\n0 0 1\n"
            + b"ATOMIC_POSITIONS (angstrom)\nSi x y z\n",
        ),
    ],
}


def _assert_graceful(parser: ParserPlugin, data: bytes, label: str) -> None:
    """The whole corpus's assertion: ``ParseError`` xor a valid ``ParseResult`` — never anything
    else. A leaked non-``ParseError`` exception (or a non-``ParseResult`` return) is the defect."""
    try:
        result = parser.parse(io.BytesIO(data), filename=f"fuzz.{parser.format_id}.{label}")
    except ParseError:
        return  # the graceful decline — the §5 contract
    except Exception as exc:  # noqa: BLE001 - catching the defect is the point of the test
        pytest.fail(
            f"{parser.format_id} leaked {type(exc).__name__} on seed {label!r} "
            f"instead of ParseError: {exc}"
        )
    assert isinstance(result, ParseResult), (
        f"{parser.format_id} returned {type(result).__name__} on seed {label!r}, not a ParseResult"
    )


_PARSERS = {p.format_id: p for p in builtin_parsers()}


@pytest.mark.parametrize("format_id", sorted(_PARSERS))
@pytest.mark.parametrize("label", sorted(_GENERIC))
def test_generic_battery_is_handled_gracefully(format_id: str, label: str) -> None:
    _assert_graceful(_PARSERS[format_id], _GENERIC[label], label)


@pytest.mark.parametrize(
    ("format_id", "label", "data"),
    [(fid, label, data) for fid, cases in _TAILORED.items() for label, data in cases],
)
def test_tailored_seeds_are_handled_gracefully(format_id: str, label: str, data: bytes) -> None:
    _assert_graceful(_PARSERS[format_id], data, label)


def test_corpus_covers_every_builtin_parser() -> None:
    # A guard so a newly-added first-party format cannot silently escape the fuzz corpus: every
    # built-in parser must appear in the tailored map (the generic battery already covers all).
    assert set(_TAILORED) == set(_PARSERS), (
        "every built-in parser needs at least one tailored fuzz seed; "
        f"missing: {set(_PARSERS) - set(_TAILORED)}"
    )
