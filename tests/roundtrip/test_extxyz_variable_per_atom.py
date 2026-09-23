"""Per-atom custom columns ride each frame losslessly, constant-N or not (v2.0 review, S2).

Post-M72 each ``Frame`` carries its own ``custom_per_atom``, so a per-atom column that varies
across the frames of a *constant-N* trajectory is representable without loss — each frame keeps
its own values. Before this fix both the materialized and streaming extXYZ paths collapsed such a
column to frame 0's values and emitted a now-false ``EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE``
warning. This pins the corrected, lossless behaviour and the streamed==materialized identity.
"""

import io

import numpy as np

from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.sdk.streaming import materialize


def _two_frame_varying_force() -> bytes:
    # Two frames, N=2 both, a per-atom "force" column that DIFFERS between frames.
    return (
        b"2\n"
        b'Properties=species:S:1:pos:R:3:force:R:3 Lattice="10 0 0 0 10 0 0 0 10" pbc="T T T"\n'
        b"H 0 0 0 1.0 0.0 0.0\n"
        b"H 1 0 0 2.0 0.0 0.0\n"
        b"2\n"
        b'Properties=species:S:1:pos:R:3:force:R:3 Lattice="10 0 0 0 10 0 0 0 10" pbc="T T T"\n'
        b"H 0 0 0 9.0 0.0 0.0\n"
        b"H 1 0 0 8.0 0.0 0.0\n"
    )


def test_extxyz_constant_n_varying_column_is_lossless_and_per_frame() -> None:
    data = _two_frame_varying_force()
    parser = ExtxyzParser()
    mat_result = parser.parse(io.BytesIO(data), filename="t.extxyz")
    mat = mat_result.canonical
    strm, strm_issues = materialize(parser.parse_stream(io.BytesIO(data), filename="t.extxyz"))

    # No "not representable" warning — the varying column IS representable per frame now.
    assert "EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE" not in {i.code for i in mat_result.issues}
    assert "EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE" not in {i.code for i in strm_issues}

    # Frame 1 keeps ITS OWN values, not frame 0's.
    f0 = mat.frames[0].custom_per_atom["extxyz:force"]
    f1 = mat.frames[1].custom_per_atom["extxyz:force"]
    assert not np.array_equal(np.asarray(f0), np.asarray(f1))
    assert np.allclose(np.asarray(f1)[:, 0], [9.0, 8.0])

    # Streamed == materialized (identity theorem).
    for i in range(2):
        assert np.allclose(
            np.asarray(mat.frames[i].custom_per_atom["extxyz:force"]),
            np.asarray(strm.frames[i].custom_per_atom["extxyz:force"]),
        )
