"""``_varray_rows`` matches the per-row reading bit for bit and keeps its errors (T11, I1)."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import pytest

from xtalate.parsers.vasprun import _row_values, _varray_rows
from xtalate.sdk import ParseError


def _legacy_rows(varray: ET.Element) -> list[list[float]]:
    where = f"<varray name={varray.get('name')!r}>"
    return [_row_values(v, where) for v in varray]


def test_varray_bulk_equals_legacy_bit_for_bit() -> None:
    xml = (
        '<varray name="positions"><v>0.1 0.2 0.30000000000000004</v>'
        "<v>-1e-3 2.5E+01 nan</v><v>inf 0 -0.0</v></varray>"
    )
    va = ET.fromstring(xml)
    assert repr(_varray_rows(va)) == repr(_legacy_rows(va))


def test_varray_ragged_rows_fall_back_to_legacy() -> None:
    va = ET.fromstring('<varray name="x"><v>1 2 3</v><v>4 5</v></varray>')
    assert _varray_rows(va) == _legacy_rows(va)


def test_varray_empty_is_empty() -> None:
    assert _varray_rows(ET.fromstring('<varray name="x"/>')) == []


def test_varray_blank_row_error_is_preserved() -> None:
    va = ET.fromstring('<varray name="x"><v>1 2 3</v><v>  </v></varray>')
    where = "<varray name='x'>"
    with pytest.raises(ParseError, match=re.escape(f"{where} contains an empty <v>")) as exc:
        _varray_rows(va)
    assert exc.value.issues[0].code == "VASPRUN_MALFORMED_XML"
    assert exc.value.issues[0].location == where


def test_varray_non_numeric_error_is_preserved() -> None:
    va = ET.fromstring('<varray name="x"><v>1 2 3</v><v>1 b 3</v></varray>')
    where = "<varray name='x'>"
    with pytest.raises(
        ParseError, match=re.escape(f"{where} holds non-numeric content: '1 b 3'")
    ) as exc:
        _varray_rows(va)
    assert exc.value.issues[0].code == "VASPRUN_MALFORMED_XML"
    assert exc.value.issues[0].location == where
