"""The 6-number Voigt `stress=` read (v1.2 M42-S4, RF-4; DECISIONS.md D162).

ASE's extXYZ reader refuses a 6-number `stress=` outright (it requires the 9-number
full-tensor spelling), so the parser expands the Voigt-6 value to the 9-number form — via
ASE's own `voigt_6_to_full_3x3_stress` (ASE ordering `[xx, yy, zz, yz, xz, xy]`, not VASP's
from M42-S3) — before ASE reads the comment line. The read value lands under
`custom_per_frame['extxyz:stress']` exactly like the 9-number path and still resolves only
under the `ambiguous_stress_convention` recovery (RF-4 is about *reading the spelling*, not
about resolving its convention — D162).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from xtalate.conversion import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry
from xtalate.schema.models import CanonicalObject
from xtalate.sdk import ParseError
from xtalate.sdk.streaming import materialize

_STRESS_KEY = "extxyz:stress"

_SIX = b'1\nProperties=species:S:1:pos:R:3 stress="1 2 3 4 5 6" pbc="T T T"\nH 0 0 0\n'
# The semantically-equal 9-number spelling (ASE reads the 9 values column-major, so the flat
# form is the transpose's row-major flatten of the same 3×3).
_NINE = b'1\nProperties=species:S:1:pos:R:3 stress="1 6 5 6 2 4 5 4 3" pbc="T T T"\nH 0 0 0\n'


def _parse(data: bytes) -> CanonicalObject:
    canonical = ExtxyzParser().parse(io.BytesIO(data), filename="x.xyz").canonical
    assert canonical is not None
    return canonical


def test_six_number_stress_reads_and_carries_identically_to_nine() -> None:
    six = _parse(_SIX)
    nine = _parse(_NINE)
    assert np.array_equal(
        np.asarray(six.user_metadata.custom_per_frame[_STRESS_KEY]),
        np.asarray(nine.user_metadata.custom_per_frame[_STRESS_KEY]),
    )
    # The carry is the Voigt-6 values verbatim; nothing is mapped silently to
    # electronic.stress (the convention stays unresolved on read, D18/D151).
    assert six.frames[0].electronic.stress is None
    assert np.asarray(six.user_metadata.custom_per_frame[_STRESS_KEY]).ravel().tolist() == [
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
    ]


def test_six_number_carry_resolves_via_ambiguous_stress_convention() -> None:
    # Done-means #2: the 6-number carry resolves to first-class electronic.stress exactly like
    # the 9-number case — M40's machinery reused unchanged (D162).
    obj = _parse(_SIX)
    res = ConversionEngine(default_registry()).convert(
        obj,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert res.report.status == "completed"
    assert [a.scenario for a in res.report.assumptions] == ["ambiguous_stress_convention"]
    assert res.canonical_out is not None
    stress = res.canonical_out.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == voigt_6_to_full_3x3_stress([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]).tolist()
    assert res.validation is not None and res.validation.status == "passed"


def test_streamed_and_materialized_six_number_reads_are_identical() -> None:
    stream = ExtxyzParser().parse_stream(io.BytesIO(_SIX), filename="x.xyz")
    streamed, _ = materialize(stream)
    assert streamed.model_dump(mode="json") == _parse(_SIX).model_dump(mode="json")


def test_malformed_stress_value_refuses_naming_the_frame() -> None:
    # Done-means #3: a value that is neither 6 nor 9 numbers refuses EXTXYZ_PARSE_ERROR with
    # the frame located — replacing ASE's frame-less wrap for this case (RF-A1 honesty).
    # 7 numbers; non-numeric.
    for bad in (
        b'1\nProperties=species:S:1:pos:R:3 stress="1 2 3 4 5 6 7" pbc="T T T"\nH 0 0 0\n',
        b'1\nProperties=species:S:1:pos:R:3 stress="1 2 abc 4 5 6" pbc="T T T"\nH 0 0 0\n',
    ):
        with pytest.raises(ParseError) as excinfo:
            ExtxyzParser().parse(io.BytesIO(bad), filename="x.xyz")
        issue = excinfo.value.issues[0]
        assert issue.code == "EXTXYZ_PARSE_ERROR"
        assert issue.location == "frame 0"
        assert "stress" in issue.message


def test_six_number_stress_never_leaks_a_non_parse_error() -> None:
    # The 6-number path must fail inside the ParseError contract, never a raw exception.
    # 3 numbers; 10 numbers.
    for bad in (
        b'1\nProperties=species:S:1:pos:R:3 stress="1 2 3" pbc="T T T"\nH 0 0 0\n',
        b'1\nProperties=species:S:1:pos:R:3 stress="1 2 3 4 5 6 7 8 9 10" pbc="T T T"\nH 0 0 0\n',
    ):
        with pytest.raises(ParseError):
            ExtxyzParser().parse(io.BytesIO(bad), filename="x.xyz")
