"""H5MD unit laundering and torn-tail recovery (v2.0 M74 S2).

Two boundary behaviours the mission turns on: units are converted to canonical at the read boundary
**and recorded** (never silently reinterpreted, P1), and a truncated trajectory (a run killed
mid-write) is *refused by default* with a recovery hint rather than silently keeping a partial file
(P4). The dedicated ``truncate_at_last_valid_frame`` recovery then yields the complete-frame prefix.
"""

from __future__ import annotations

from io import BytesIO

import h5py
import numpy as np
import pytest

from xtalate.parsers.h5md import H5MDParser
from xtalate.sdk import ParseError


def _one_frame_positions(*, unit: str | None, value: np.ndarray) -> BytesIO:
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        f.create_group("h5md")
        particles = f.create_group("particles/all")
        pos = particles.create_group("position")
        vlen = h5py.vlen_dtype(np.float64)
        ds = pos.create_dataset("value", shape=(1,), dtype=vlen)
        ds[0] = np.asarray(value, dtype=np.float64).reshape(-1)
        if unit is not None:
            ds.attrs["unit"] = unit
        pos.create_dataset("step", data=np.array([0], dtype=np.int64))
        pos.create_dataset("time", data=np.array([0.0]))
        sp = particles.create_group("species")
        spv = sp.create_dataset("value", shape=(1,), dtype=h5py.vlen_dtype(np.int64))
        spv[0] = np.array([1], dtype=np.int64)
        sp.create_dataset("step", data=np.array([0], dtype=np.int64))
        sp.create_dataset("time", data=np.array([0.0]))
    buf.seek(0)
    return buf


def test_nm_positions_are_converted_to_angstrom_and_recorded() -> None:
    buf = _one_frame_positions(unit="nm", value=np.array([[1.0, 0.0, 0.0]]))
    result = H5MDParser().parse(buf, filename="nm.h5md")
    obj = result.canonical
    # 1 nm -> 10 Å.
    np.testing.assert_allclose(obj.frames[0].atoms.positions, [[10.0, 0.0, 0.0]])
    assert obj.provenance.source_units.get("positions") == "nm"
    assert any("nm" in note and "Angstrom" in note for note in obj.provenance.parse_notes)


def test_unspecified_position_unit_is_taken_verbatim_with_a_note() -> None:
    buf = _one_frame_positions(unit=None, value=np.array([[1.0, 0.0, 0.0]]))
    result = H5MDParser().parse(buf, filename="nounit.h5md")
    obj = result.canonical
    np.testing.assert_allclose(obj.frames[0].atoms.positions, [[1.0, 0.0, 0.0]])
    # No unit was declared, so none is assumed and none is recorded as the source unit (P4).
    assert "positions" not in obj.provenance.source_units
    assert any(
        "no unit" in note.lower() or "unspecified" in note.lower()
        for note in obj.provenance.parse_notes
    )


def _torn_trajectory() -> BytesIO:
    """A 3-declared-step trajectory whose ``position/value`` holds only 2 rows — a run killed
    mid-write (``step``/``time`` were preallocated to 3, but only 2 frames were flushed)."""
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        f.create_group("h5md")
        particles = f.create_group("particles/all")
        pos = particles.create_group("position")
        vlen = h5py.vlen_dtype(np.float64)
        value = pos.create_dataset("value", shape=(2,), dtype=vlen)
        value[0] = np.array([0.0, 0.0, 0.0])
        value[1] = np.array([0.1, 0.0, 0.0])
        pos.create_dataset("step", data=np.array([0, 1, 2], dtype=np.int64))
        pos.create_dataset("time", data=np.array([0.0, 1.0, 2.0]))
        sp = particles.create_group("species")
        spv = sp.create_dataset("value", shape=(2,), dtype=h5py.vlen_dtype(np.int64))
        spv[0] = np.array([1], dtype=np.int64)
        spv[1] = np.array([1], dtype=np.int64)
        sp.create_dataset("step", data=np.array([0, 1, 2], dtype=np.int64))
        sp.create_dataset("time", data=np.array([0.0, 1.0, 2.0]))
    buf.seek(0)
    return buf


def test_torn_tail_is_refused_by_default_with_a_truncate_hint() -> None:
    buf = _torn_trajectory()
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(buf, filename="torn.h5md")
    issue = exc.value.issues[0]
    assert issue.code == "H5MD_TRUNCATED"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"


def test_torn_tail_recovers_to_the_valid_prefix() -> None:
    buf = _torn_trajectory()
    result = H5MDParser().parse_recover(
        buf,
        filename="torn.h5md",
        hint="truncate_at_last_valid_frame",
        choice="truncate",
        parameters={},
    )
    obj = result.canonical
    assert obj.frame_count == 2
    np.testing.assert_allclose(obj.frames[1].atoms.positions, [[0.1, 0.0, 0.0]])
    assert any(issue.code == "H5MD_TRUNCATED" for issue in result.issues)
