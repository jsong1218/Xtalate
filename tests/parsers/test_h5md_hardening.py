"""H5MD resource-exhaustion and external-link hardening (v2.0 review, S4).

A hostile or corrupt H5MD file can be a few KB on disk yet declare an enormous per-frame particle
dimension or frame count (chunked/empty/``maxshape`` datasets write no bytes), OOMing the reader
during the count-only precheck — *before* ``max_frames`` can bound anything (``max_frames`` never
bounds per-frame size). And an ``h5py.ExternalLink`` carries an absolute path, so following it would
read an out-of-band file (``/etc/passwd``) even though the trajectory itself is opened from an
in-memory ``BytesIO`` with no filesystem base. These pin the loud, allocation-free refusals.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import h5py
import numpy as np
import pytest

from xtalate.parsers.h5md import H5MDParser
from xtalate.sdk.results import ParseError


def _bytes(build: Callable[[h5py.File], None]) -> bytes:
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        build(f)
    return buf.getvalue()


def test_h5md_refuses_absurd_per_frame_atom_count() -> None:
    def build(f: h5py.File) -> None:
        g = f.create_group("particles/all/position")
        g.create_dataset("step", data=np.arange(2))
        g.create_dataset("time", data=np.arange(2, dtype=float))
        # declared (2, 2_000_000_000, 3) via a chunked empty dataset — a few KB on disk.
        g.create_dataset("value", shape=(2, 2_000_000_000, 3), dtype="f8", chunks=(1, 1024, 3))

    with pytest.raises(ParseError) as ei:
        H5MDParser().parse(io.BytesIO(_bytes(build)), filename="a.h5")
    assert any(i.code == "H5MD_FRAME_TOO_LARGE" for i in ei.value.issues)


def test_h5md_refuses_external_link() -> None:
    def build(f: h5py.File) -> None:
        f["particles/all/position/value"] = h5py.ExternalLink("/etc/passwd", "/")

    with pytest.raises(ParseError) as ei:
        H5MDParser().parse(io.BytesIO(_bytes(build)), filename="a.h5")
    assert any(i.code == "H5MD_EXTERNAL_LINK" for i in ei.value.issues)


def test_h5md_refuses_absurd_frame_count() -> None:
    def build(f: h5py.File) -> None:
        g = f.create_group("particles/all/position")
        g.create_dataset("step", shape=(10**9,), dtype="i8", chunks=(1024,))
        g.create_dataset("value", shape=(10**9, 1, 3), dtype="f8", chunks=(1, 1, 3))
        # A species element so the file clears the required-group gate and reaches the frame count.
        s = f.create_group("particles/all/species")
        s.create_dataset("step", shape=(10**9,), dtype="i8", chunks=(1024,))
        s.create_dataset("value", shape=(10**9, 1), dtype="i8", chunks=(1, 1))

    with pytest.raises(ParseError) as ei:
        H5MDParser().parse(io.BytesIO(_bytes(build)), filename="a.h5")
    assert any(i.code == "H5MD_TOO_MANY_FRAMES" for i in ei.value.issues)


def test_h5md_refuses_absurd_fixed_element() -> None:
    # A fixed-in-time element (a bare dataset) is loaded eagerly in full (H2); an absurd declared
    # length must be refused before np.asarray materializes it.
    def build(f: h5py.File) -> None:
        g = f.create_group("particles/all/position")
        g.create_dataset("step", data=np.arange(1))
        g.create_dataset("value", shape=(1, 1, 3), dtype="f8")
        # species declared as a fixed 2e9-long dataset.
        f.create_dataset(
            "particles/all/species/value", shape=(1, 2_000_000_000), dtype="i8", chunks=(1, 1024)
        )

    with pytest.raises(ParseError) as ei:
        H5MDParser().parse(io.BytesIO(_bytes(build)), filename="a.h5")
    assert any(i.code == "H5MD_FRAME_TOO_LARGE" for i in ei.value.issues)
