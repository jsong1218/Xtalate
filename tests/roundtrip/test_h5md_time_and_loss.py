"""H5MD frame-time honesty and per-atom loss reporting (v2.0 review, S5).

Three defects the review found in the M74 H5MD pair, each a P1 violation:

* **Frame time was never read.** The parser dropped every element's ``time`` axis on the floor, and
  the exporter *fabricated* one — writing ``float(step_index)`` when the source had none, handing a
  reader a physical time indistinguishable from a real one. These pin: the parser reads ``time``
  verbatim (converting a declared unit), a source with no ``time`` yields ``frame.time = None``, and
  the exporter omits the optional ``time`` dataset rather than inventing it — round-tripping either
  way, and refusing a mixed present/absent time instead of fabricating the gaps.
* **A per-atom ``mass``/``charge`` whose length disagreed with a frame's atom count was dropped
  silently.** A fixed-in-time mass array cannot apply to a variable-N trajectory; the drop is now
  reported (``H5MD_INCONSISTENT_MASS``/``_CHARGE``).
* **The torn-tail check looked only at ``position``.** A torn ``velocity`` tail slipped past it and
  would then be indexed out of bounds. The check now spans every time-dependent element.
"""

from __future__ import annotations

from io import BytesIO

import h5py
import numpy as np
import pytest

from xtalate.exporters.h5md import H5MDExporter
from xtalate.parsers.h5md import H5MDParser
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    Provenance,
    TrajectoryMetadata,
)
from xtalate.sdk import ParseError

_CELL = Cell(lattice_vectors=np.diag([10.0, 10.0, 10.0]), pbc=(True, True, True))


def _h5md_constant_n(
    *,
    times: list[float] | None,
    time_unit: str | None = None,
    n_frames: int = 3,
) -> BytesIO:
    """A minimal constant-N (2-atom) H5MD file: ``position`` time-dependent with an optional
    ``time`` axis, ``species`` fixed-in-time. ``times=None`` writes ``step`` but no ``time``."""
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray([1, 1], dtype=np.int64)
        grp = f.create_group("particles/all")
        pos = grp.create_group("position")
        pos.create_dataset("value", data=np.zeros((n_frames, 2, 3), dtype=np.float64))
        pos.create_dataset("step", data=np.arange(n_frames, dtype=np.int64))
        if times is not None:
            td = pos.create_dataset("time", data=np.asarray(times, dtype=np.float64))
            if time_unit is not None:
                td.attrs["unit"] = time_unit
        grp.create_dataset("species", data=np.array([1, 8], dtype=np.int64))
    buf.seek(0)
    return buf


def _object_with_times(times: list[float | None]) -> CanonicalObject:
    frames = [
        Frame(
            index=i,
            atoms=AtomsBlock(symbols=["H", "O"], positions=np.array([[0.0, 0, 0], [0, 0, 1.0]])),
            cell=_CELL,
            time=t,
        )
        for i, t in enumerate(times)
    ]
    provenance = Provenance(
        source_filename=None, source_format="h5md", original_coordinate_system="cartesian"
    )
    return CanonicalObject(
        frames=frames, trajectory=TrajectoryMetadata(timestep=None), provenance=provenance
    )


# --- frame time is read verbatim, never faked from the index --------------------------


def test_h5md_reads_frame_time_verbatim_not_index() -> None:
    # times deliberately differ from the step index (0,1,2): a reader returning the index is caught.
    buf = _h5md_constant_n(times=[0.0, 2.5, 5.0])
    res = H5MDParser().parse(buf, filename="t.h5")
    assert [fr.time for fr in res.canonical.frames] == [0.0, 2.5, 5.0]


def test_h5md_without_time_axis_yields_none_frame_time() -> None:
    buf = _h5md_constant_n(times=None)
    res = H5MDParser().parse(buf, filename="t.h5")
    assert all(fr.time is None for fr in res.canonical.frames)


def test_h5md_time_unit_ps_converts_to_fs() -> None:
    buf = _h5md_constant_n(times=[0.0, 1.0, 2.0], time_unit="ps")
    res = H5MDParser().parse(buf, filename="t.h5")
    assert [fr.time for fr in res.canonical.frames] == [0.0, 1000.0, 2000.0]


# --- the exporter omits time rather than fabricating it, and round-trips --------------


def test_h5md_exporter_omits_time_dataset_when_frames_have_no_time() -> None:
    obj = _object_with_times([None, None])
    buf = BytesIO()
    H5MDExporter().export(obj, buf)
    buf.seek(0)
    with h5py.File(buf, "r") as f:
        pos = f["particles/all/position"]
        assert "step" in pos  # step is always written
        assert "time" not in pos  # ...but time is never fabricated (P3)


def test_h5md_roundtrips_frame_time_when_present() -> None:
    obj = _object_with_times([0.0, 2.5])
    buf = BytesIO()
    H5MDExporter().export(obj, buf)
    buf.seek(0)
    res = H5MDParser().parse(buf, filename="rt.h5")
    assert [fr.time for fr in res.canonical.frames] == [0.0, 2.5]


def test_h5md_exporter_refuses_mixed_frame_time() -> None:
    # frame 0 has a time, frame 1 does not — H5MD cannot hold a time for some frames only, and it
    # must never be fabricated for the gaps, so the export is refused (P1).
    obj = _object_with_times([0.0, None])
    reason = H5MDExporter().unrepresentable(obj)
    assert reason is not None
    assert "frame time" in reason


# --- a per-atom mass/charge that cannot fit a frame is reported, not silently dropped -


def _variable_n_with_fixed_per_atom(kind: str) -> BytesIO:
    """A 2-then-3 atom variable-N trajectory with a fixed-in-time 2-long ``mass`` or ``charge``
    dataset: it fits frame 0 (2 atoms) but not frame 1 (3 atoms)."""
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray([1, 1], dtype=np.int64)
        grp = f.create_group("particles/all")
        pos = grp.create_group("position")
        pos_val = pos.create_dataset("value", shape=(2,), dtype=h5py.vlen_dtype(np.float64))
        pos_val[0] = np.zeros(2 * 3)
        pos_val[1] = np.zeros(3 * 3)
        pos.create_dataset("step", data=np.arange(2, dtype=np.int64))
        sp = grp.create_group("species")
        sp_val = sp.create_dataset("value", shape=(2,), dtype=h5py.vlen_dtype(np.int64))
        sp_val[0] = np.array([1, 8], dtype=np.int64)
        sp_val[1] = np.array([1, 8, 1], dtype=np.int64)
        sp.create_dataset("step", data=np.arange(2, dtype=np.int64))
        ds = grp.create_dataset(kind, data=np.array([1.0, 2.0], dtype=np.float64))
        ds.attrs["unit"] = "u" if kind == "mass" else "e"
    buf.seek(0)
    return buf


def test_h5md_mass_length_mismatch_is_reported_not_silent() -> None:
    res = H5MDParser().parse(_variable_n_with_fixed_per_atom("mass"), filename="m.h5")
    assert any(i.code == "H5MD_INCONSISTENT_MASS" for i in res.issues)
    assert res.canonical.frames[0].atoms.masses is not None  # fits the 2-atom frame
    assert res.canonical.frames[1].atoms.masses is None  # cannot fit the 3-atom frame, dropped


def test_h5md_charge_length_mismatch_is_reported_not_silent() -> None:
    res = H5MDParser().parse(_variable_n_with_fixed_per_atom("charge"), filename="c.h5")
    assert any(i.code == "H5MD_INCONSISTENT_CHARGE" for i in res.issues)
    assert res.canonical.frames[0].electronic.charges is not None
    assert res.canonical.frames[1].electronic.charges is None


# --- a torn tail on any time-dependent element is refused, not indexed out of bounds --


def _torn_velocity() -> BytesIO:
    """position has 3 flushed frames, but velocity's ``value`` holds only 2 while its ``step``
    declares 3 — a run killed mid-write. The old position-only check missed this."""
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray([1, 1], dtype=np.int64)
        grp = f.create_group("particles/all")
        pos = grp.create_group("position")
        pos.create_dataset("value", data=np.zeros((3, 2, 3), dtype=np.float64))
        pos.create_dataset("step", data=np.arange(3, dtype=np.int64))
        grp.create_dataset("species", data=np.array([1, 8], dtype=np.int64))
        vel = grp.create_group("velocity")
        vel_val = vel.create_dataset("value", shape=(2,), dtype=h5py.vlen_dtype(np.float64))
        vel_val[0] = np.zeros(2 * 3)
        vel_val[1] = np.zeros(2 * 3)
        vel_val.attrs["unit"] = "Angstrom/fs"
        vel.create_dataset("step", data=np.arange(3, dtype=np.int64))  # declares 3, holds 2
    buf.seek(0)
    return buf


def test_h5md_torn_velocity_tail_is_refused() -> None:
    with pytest.raises(ParseError) as ei:
        H5MDParser().parse(_torn_velocity(), filename="torn.h5")
    assert any(i.code == "H5MD_TRUNCATED" for i in ei.value.issues)


def test_h5md_torn_velocity_tail_recovers_to_complete_prefix() -> None:
    res = H5MDParser().parse_recover(
        _torn_velocity(),
        filename="torn.h5",
        hint="truncate_at_last_valid_frame",
        choice="truncate",
        parameters={},
    )
    assert len(res.canonical.frames) == 2  # the two complete frames survive
    assert any(i.code == "H5MD_TRUNCATED" for i in res.issues)  # the dropped tail is reported
