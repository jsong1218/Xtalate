"""XYZ parser tests (M3a): golden fidelity, sniffing, and the error contract (Part 3 §5)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden, parse_bytes
from xtalate.parsers.xyz import XyzParser
from xtalate.sdk import ParseError

GOLDEN = Path(__file__).parent.parent / "golden" / "xyz" / "water-traj"


def _parser() -> XyzParser:
    return XyzParser()


def test_golden_water_traj() -> None:
    source = (GOLDEN / "water_traj.xyz").read_bytes()
    result = parse_bytes(_parser(), source, filename="water_traj.xyz")
    assert result.issues == []
    assert_matches_golden(result.canonical, (GOLDEN / "expected.canonical.json").read_text())


def test_single_frame_is_a_structure_not_a_trajectory() -> None:
    # One frame => static structure, trajectory=None (Part 2 §3.2).
    data = b"1\nlone\nO 0.0 0.0 0.0\n"
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frame_count == 1
    assert obj.trajectory is None
    assert obj.frames[0].cell is None  # XYZ carries no cell — absence, not identity (§2 rule 2)


def test_multi_frame_populates_trajectory_with_absent_timestep() -> None:
    obj = parse_bytes(_parser(), (GOLDEN / "water_traj.xyz").read_bytes()).canonical
    assert obj.frame_count == 2
    assert obj.trajectory is not None
    assert obj.trajectory.timestep is None  # frames without a declared time base (§8.1)
    assert obj.user_metadata.custom_per_frame["xyz:comment"] == ["frame 0", "frame 1"]


def test_positions_are_cartesian_angstrom() -> None:
    obj = parse_bytes(_parser(), (GOLDEN / "water_traj.xyz").read_bytes()).canonical
    assert np.array_equal(obj.frames[1].atoms.positions[:, 2], [0.01, 0.01, 0.01])
    assert obj.provenance.source_units == {"positions": "angstrom"}
    assert obj.provenance.original_coordinate_system == "cartesian"


def test_inconsistent_atom_count_raises_with_recovery_hint() -> None:
    # Frame declares 3 atoms but only 2 coordinate lines before EOF (Part 3 §5 rule 4).
    data = b"3\nframe 0\nO 0.0 0.0 0.0\nH 0.757 0.586 0.0\n"
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), data)
    (issue,) = [i for i in exc.value.issues if i.severity == "error"]
    assert issue.code == "XYZ_INCONSISTENT_ATOM_COUNT"
    assert issue.location == "frame 0"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"


def test_mid_file_corruption_in_second_frame_reports_that_frame() -> None:
    # Frame 0 is valid; frame 1 declares 2 atoms but supplies 1 — the §5 rule-4 example.
    data = b"1\na\nO 0.0 0.0 0.0\n2\nb\nH 0.0 0.0 0.0\n"
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), data)
    issue = exc.value.issues[0]
    assert issue.code == "XYZ_INCONSISTENT_ATOM_COUNT"
    assert issue.location == "frame 1"


def test_empty_file_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"   \n\n")
    assert exc.value.issues[0].code == "XYZ_EMPTY"


def test_non_integer_header_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"notanumber\ncomment\nO 0 0 0\n")
    assert exc.value.issues[0].code == "XYZ_MALFORMED_HEADER"


def test_unknown_symbol_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"1\nc\nZz 0.0 0.0 0.0\n")
    assert exc.value.issues[0].code == "XYZ_INVALID_SYMBOL"


def test_non_numeric_coordinate_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"1\nc\nO x y z\n")
    assert exc.value.issues[0].code == "XYZ_MALFORMED_COORDINATE"


def test_sniff_recognises_plain_xyz() -> None:
    score = _parser().sniff((GOLDEN / "water_traj.xyz").read_bytes(), "water_traj.xyz")
    assert score >= 0.9


def test_sniff_rejects_non_xyz() -> None:
    assert _parser().sniff(b"NaCl primitive test\n1.0\n", "POSCAR") == 0.0


def test_sniff_yields_to_extxyz_markers() -> None:
    # A comment line bearing extXYZ key=value markers caps confidence so a future extXYZ
    # parser (M3c) wins the tie (Part 3 §3 n.2, §6.1).
    data = b'2\nLattice="1 0 0 0 1 0 0 0 1" Properties=species:S:1:pos:R:3\nO 0 0 0\nH 1 0 0\n'
    assert _parser().sniff(data, "thing.xyz") <= 0.6
