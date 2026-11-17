"""``floats_from_tokens`` is a drop-in for ``[float(t) for t in tokens]`` (spec E4)."""

from __future__ import annotations

import numpy as np
import pytest

from xtalate.parsers._common import floats_from_tokens

GOOD = ["0.1", "-2.5e-3", "1e5", "+.5", "nan", "inf", "-inf", "1_0", " 7 ", "1E+03", "0"]


def test_matches_float_bit_for_bit() -> None:
    expected = np.array([float(t) for t in GOOD], dtype=np.float64)
    got = floats_from_tokens(GOOD)
    assert got.dtype == np.float64
    assert got.shape == (len(GOOD),)
    assert got.tobytes() == expected.tobytes()  # includes nan payload / signed zero


def test_empty_input_is_an_empty_float_array() -> None:
    got = floats_from_tokens([])
    assert got.dtype == np.float64
    assert got.shape == (0,)


@pytest.mark.parametrize("bad", ["abc", "1,5", "0x10", "1e", "--1", ""])
def test_a_bad_token_raises_value_error_like_float(bad: str) -> None:
    with pytest.raises(ValueError):
        float(bad)
    with pytest.raises(ValueError):
        floats_from_tokens(["1.0", bad, "2.0"])
