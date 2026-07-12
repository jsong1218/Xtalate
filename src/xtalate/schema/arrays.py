"""NumPy array field types for the Canonical Model (MASTER_SPEC Part 2 §1, §3).

Numeric array fields (``positions``, ``lattice_vectors``, ``velocities``, ...) are
``np.ndarray`` of ``float64`` in memory — for zero-copy interop with the array-native
scientific libraries (ASE) the pipeline delegates to — and serialize to **nested JSON
lists**. This module provides the pydantic v2 custom types that enforce that contract.

Design (DECISIONS.md D8):

* In memory: ``np.ndarray``, dtype ``float64``, always a fresh copy (inputs are never
  aliased, so a caller mutating the array it passed in cannot corrupt the model).
* Serialized (JSON mode): nested lists via ``ndarray.tolist()`` — Python's default
  shortest-round-tripping float ``repr``, making ``float64 -> JSON -> float64`` lossless.
* Golden equality is defined as *deserialize-then-compare* (``np.array_equal`` on the
  parsed values), never a comparison of serialized text — see the round-trip tests.

Each type validates only its **local** shape (rank and any fixed axis, e.g. the trailing
``3`` of an ``(N, 3)`` array). Cross-field agreement — that ``positions``,
``velocities`` and ``forces`` share one ``N``, that ``N`` is constant across frames — is a
*model*-level invariant enforced by validators on the models (§3.3, §3.2), not here: a
lone array cannot know the object's atom count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import numpy as np
from numpy.typing import NDArray
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


@dataclass(frozen=True)
class _ArraySpec:
    """pydantic-v2 metadata object describing a ``float64`` ndarray field.

    Placed inside ``Annotated[...]``; pydantic calls ``__get_pydantic_core_schema__``
    to obtain the validate/serialize schema for the annotated field.
    """

    # Exact rank, or None for "any rank >= 1" (the custom-array case, Part 2 §3.10,
    # whose trailing shape is arbitrary and whose first-axis == N/F is a model check).
    ndim: int | None
    # (axis_index, required_size) pairs, e.g. (1, 3) for the trailing 3 of an (N, 3) array.
    fixed_axes: tuple[tuple[int, int], ...] = ()

    def _shape_label(self) -> str:
        if self.ndim is None:
            return "(first-axis, ...)"
        dims = ["?"] * self.ndim
        for axis, size in self.fixed_axes:
            dims[axis] = str(size)
        return "(" + ", ".join(dims) + ")"

    def _validate(self, value: Any) -> NDArray[np.float64]:
        if isinstance(value, np.ndarray) and value.dtype == np.float64:
            # Copy so a later mutation of the caller's array cannot reach into the model.
            arr = value.copy()
        else:
            try:
                arr = np.asarray(value, dtype=np.float64)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"expected a real-valued array coercible to float64, got {value!r}"
                ) from exc
        if self.ndim is None:
            if arr.ndim < 1:
                raise ValueError(
                    f"expected an array of rank >= 1 {self._shape_label()}, got a 0-D array"
                )
        elif arr.ndim != self.ndim:
            raise ValueError(
                f"expected a {self.ndim}-D array of shape {self._shape_label()}, "
                f"got a {arr.ndim}-D array of shape {arr.shape}"
            )
        for axis, size in self.fixed_axes:
            if arr.shape[axis] != size:
                raise ValueError(
                    f"expected axis {axis} of length {size} "
                    f"(shape {self._shape_label()}), got shape {arr.shape}"
                )
        if not np.all(np.isfinite(arr)):
            raise ValueError("array contains non-finite values (nan/inf); refusing")
        return arr

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            self._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda arr: arr.tolist(),
                when_used="json",
            ),
        )


# --- Concrete field types, named after their canonical shapes (Part 2 §3). -----------

#: ``(N, 3)`` — per-atom Cartesian triples: positions, velocities, forces.
ArrayN3 = Annotated[NDArray[np.float64], _ArraySpec(ndim=2, fixed_axes=((1, 3),))]

#: ``(N,)`` — per-atom scalars: masses, charges, magnetic moments.
ArrayN = Annotated[NDArray[np.float64], _ArraySpec(ndim=1)]

#: ``(3, 3)`` — lattice vectors (rows a, b, c) and the stress tensor.
Array33 = Annotated[NDArray[np.float64], _ArraySpec(ndim=2, fixed_axes=((0, 3), (1, 3)))]

#: First dimension ``N`` (per-atom), any trailing shape — ``user_metadata.custom_per_atom``.
ArrayNx = Annotated[NDArray[np.float64], _ArraySpec(ndim=None)]

#: First dimension ``F`` (per-frame), any trailing shape — ``user_metadata.custom_per_frame``.
ArrayFx = Annotated[NDArray[np.float64], _ArraySpec(ndim=None)]
