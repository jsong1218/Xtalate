"""E4: bulk float parsing must not change a single error message, location, hint or ordering
(P1; the parsers' error text is what users and the recovery engine act on)."""

from __future__ import annotations

import io

import numpy as np
import pytest

from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.parsers.xdatcar import make_xdatcar_parser
from xtalate.sdk import ParseError

_LAMMPS_HEAD = (
    b"ITEM: UNITS\nmetal\nITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n3\n"
    b"ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\nITEM: ATOMS id element x y z\n"
)
_COLS = "['id', 'element', 'x', 'y', 'z']"
_MAL = "LAMMPSDUMP_MALFORMED_HEADER"

_LAMMPS_ERRORS: list[tuple[str, bytes, str, str, str | None]] = [
    (
        "short block",
        b"1 Si 0 0 0\n2 Si 1 1 1\n",
        _MAL,
        "frame 0 declares 3 atoms but the block ended after 2 data rows",
        "frame 0",
    ),
    (
        "blank line ends the block",
        b"1 Si 0 0 0\n\n3 Si 2 2 2\n",
        _MAL,
        "frame 0 declares 3 atoms but the block ended after 1 data rows",
        "frame 0",
    ),
    (
        "wrong token count",
        b"1 Si 0 0 0\n2 Si 1 1\n3 Si 2 2 2\n",
        _MAL,
        f"frame 0 data row has 4 values, expected 5 for columns {_COLS}: '2 Si 1 1'",
        "frame 0",
    ),
    (
        "non-numeric value names column, value and atom",
        b"1 Si 0 0 0\n2 Si 1 abc 1\n3 Si 2 2 2\n",
        _MAL,
        "frame 0 'y' column value 'abc' at atom 1 is not numeric",
        "frame 0",
    ),
    (
        "token-count error wins over a later invalid byte",
        b"1 Si 0 0 0\n2 Si 1 1\n3 Si 2 \xff 2\n",
        _MAL,
        f"frame 0 data row has 4 values, expected 5 for columns {_COLS}: '2 Si 1 1'",
        "frame 0",
    ),
    (
        "token-count error wins over a later non-numeric value",
        b"1 Si 0 0 nope\n2 Si 1 1\n3 Si 2 2 2\n",
        _MAL,
        f"frame 0 data row has 4 values, expected 5 for columns {_COLS}: '2 Si 1 1'",
        "frame 0",
    ),
    (
        "invalid UTF-8 surfaces as the encoding error, with no location",
        b"1 Si 0 0 0\n2 Si 1 \xff 1\n",
        "LAMMPSDUMP_ENCODING_ERROR",
        "file is not valid UTF-8 text (byte 0xff); lammps_dump is a text format",
        None,
    ),
]


@pytest.mark.parametrize(
    ("rows", "code", "message", "location"),
    [c[1:] for c in _LAMMPS_ERRORS],
    ids=[c[0] for c in _LAMMPS_ERRORS],
)
def test_lammps_dump_error_text_is_unchanged(
    rows: bytes, code: str, message: str, location: str | None
) -> None:
    with pytest.raises(ParseError) as exc:
        make_lammps_dump_parser().parse(io.BytesIO(_LAMMPS_HEAD + rows), filename="d.lammpstrj")
    issue = exc.value.issues[0]
    assert (issue.code, issue.message, issue.location) == (code, message, location)


def test_lammps_dump_happy_path_is_bit_identical_to_per_token_float() -> None:
    body = b"1 Si 0.1 -2.5e-3 3\n2 Si 1e1 -0.0 2\n3 Si 0.30000000000000004 4.5E+00 7\n"
    obj = (
        make_lammps_dump_parser()
        .parse(io.BytesIO(_LAMMPS_HEAD + body), filename="d.lammpstrj")
        .canonical
    )
    expected = np.array(
        [[float(t) for t in r.split()[2:]] for r in body.decode().splitlines()], dtype=np.float64
    )
    got = np.asarray(obj.frames[0].atoms.positions, dtype=np.float64)
    assert got.tobytes() == expected.tobytes()


_XD_HEAD = b"t\n1.0\n 2 0 0\n 0 2 0\n 0 0 2\nSi\n3\nDirect configuration=     1\n"
_XD_CODE = "XDATCAR_TRUNCATED_CONFIGURATION"
_XD_HINT = "truncate_at_last_valid_frame"
_XD_ERRORS: list[tuple[str, bytes, str]] = [
    (
        "short block",
        b" 0 0 0\n 0.1 0.1 0.1\n",
        "configuration 0 declares 3 atoms but the block ended after 2; the file appears "
        "truncated mid-configuration",
    ),
    (
        "blank line ends the block",
        b" 0 0 0\n\n 0.2 0.2 0.2\n",
        "configuration 0 declares 3 atoms but the block ended after 1; the file appears "
        "truncated mid-configuration",
    ),
    (
        "fewer than three components",
        b" 0 0 0\n 0.1 0.1\n 0.2 0.2 0.2\n",
        "coordinate line in configuration 0 has fewer than 3 components: '0.1 0.1'; the line "
        "appears to have been truncated mid-write",
    ),
    (
        "non-numeric coordinate",
        b" 0 0 0\n 0.1 x 0.1\n 0.2 0.2 0.2\n",
        "non-numeric coordinate in configuration 0: '0.1 x 0.1'",
    ),
    (
        "a non-numeric row wins over a later short row",
        b" 0 x 0\n 0.1 0.1\n 0.2 0.2 0.2\n",
        "non-numeric coordinate in configuration 0: '0 x 0'",
    ),
]


@pytest.mark.parametrize(
    ("rows", "message"), [c[1:] for c in _XD_ERRORS], ids=[c[0] for c in _XD_ERRORS]
)
def test_xdatcar_error_text_is_unchanged(rows: bytes, message: str) -> None:
    with pytest.raises(ParseError) as exc:
        make_xdatcar_parser().parse(io.BytesIO(_XD_HEAD + rows), filename="XDATCAR")
    issue = exc.value.issues[0]
    assert issue.code == _XD_CODE
    assert issue.message == message
    assert issue.location == "frame 0"
    assert issue.recovery_hint == _XD_HINT


def test_xdatcar_invalid_utf8_is_the_encoding_error() -> None:
    with pytest.raises(ParseError) as exc:
        make_xdatcar_parser().parse(
            io.BytesIO(_XD_HEAD + b" 0 0 0\n 0.1 \xff 0.1\n"), filename="XDATCAR"
        )
    issue = exc.value.issues[0]
    assert issue.code == "XDATCAR_ENCODING_ERROR"
    assert issue.message == "file is not valid UTF-8 text (byte 0xff); xdatcar is a text format"
    assert issue.location is None


def test_xdatcar_extra_selective_dynamics_columns_are_ignored_and_values_are_exact() -> None:
    rows = b" 0 0 0 T T T\n 0.1 0.1 0.1\n 0.2 0.2 0.2\n"
    obj = make_xdatcar_parser().parse(io.BytesIO(_XD_HEAD + rows), filename="XDATCAR").canonical
    lattice = np.diag([2.0, 2.0, 2.0])
    frac = np.array([[0.0, 0.0, 0.0], [0.1, 0.1, 0.1], [0.2, 0.2, 0.2]])
    got = np.asarray(obj.frames[0].atoms.positions, dtype=np.float64)
    assert got.tobytes() == (frac @ lattice).tobytes()
