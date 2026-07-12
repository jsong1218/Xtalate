"""Array-type validation and serialization (MASTER_SPEC Part 2 §1; DECISIONS.md D8).

List inputs are exercised via ``model_validate`` — the same path JSON loading takes, and
the representative way a serialized object is rehydrated. Direct ``ndarray`` construction
(what parsers do) is used where the array identity itself is under test.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from pydantic import BaseModel, ValidationError

from xtalate.schema.arrays import Array33, ArrayN, ArrayN3, ArrayNx


class _Holder(BaseModel):
    p: ArrayN3 | None = None
    m: ArrayN | None = None
    lat: Array33 | None = None
    custom: ArrayNx | None = None


def test_n3_accepts_valid_and_coerces_to_float64() -> None:
    h = _Holder.model_validate({"p": [[0.0, 0.0, 0.0], [1, 2, 3]]})
    assert isinstance(h.p, np.ndarray)
    assert h.p.dtype == np.float64
    assert h.p.shape == (2, 3)


def test_n3_rejects_wrong_trailing_dim() -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"p": [[0.0, 0.0]]})  # (1, 2), trailing must be 3


def test_n3_rejects_wrong_rank() -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"p": [0.0, 0.0, 0.0]})  # 1-D, needs 2-D


def test_33_requires_exact_shape() -> None:
    _Holder.model_validate({"lat": [[1.0, 0, 0], [0, 1, 0], [0, 0, 1]]})
    with pytest.raises(ValidationError):
        _Holder.model_validate({"lat": [[1.0, 0, 0], [0, 1, 0]]})  # (2, 3)


def test_non_finite_rejected() -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"m": [1.0, float("nan")]})


def test_input_array_is_copied_not_aliased() -> None:
    src = np.zeros((2, 3), dtype=np.float64)
    h = _Holder(p=src)
    src[0, 0] = 99.0
    assert h.p is not None
    assert h.p[0, 0] == 0.0  # model holds its own copy


def test_json_round_trip_is_lossless() -> None:
    h = _Holder.model_validate({"p": [[0.0, 0.757, -0.757], [2.82, 2.82, 2.82]]})
    reloaded = _Holder.model_validate_json(h.model_dump_json())
    assert reloaded.p is not None and h.p is not None
    assert np.array_equal(reloaded.p, h.p)


def test_json_serializes_to_nested_lists() -> None:
    h = _Holder.model_validate({"p": [[1.0, 2.0, 3.0]]})
    payload = json.loads(h.model_dump_json())
    assert payload["p"] == [[1.0, 2.0, 3.0]]
