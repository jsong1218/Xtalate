"""The Canonical Data Model (MASTER_SPEC Part 2 §3).

One ``CanonicalObject`` == one structure or one trajectory (a structure is a trajectory
with a single frame, §3.2). Every field obeys the **Absence Convention** (§2): ``None``
means *not present in the source* and nothing else — never zero, never a default. Parsers
are forbidden from filling absent fields; that is exclusively the Recovery Engine's job.

All values are stored in the one canonical unit system (§3.1): Å, fs, eV, eV/Å, u, e, μB.
Numeric arrays are ``float64`` ``np.ndarray`` in memory and nested JSON lists when
serialized (see ``arrays``). Cross-field shape invariants (constant N, first-dim = N/F)
are enforced by the model validators here, since a lone array cannot know the object's
atom or frame count.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

if TYPE_CHECKING:
    from chembridge.schema.presence import PresenceMap

from chembridge.schema.arrays import (
    Array33,
    ArrayFx,
    ArrayN,
    ArrayN3,
    ArrayNx,
)
from chembridge.schema.elements import atomic_number, is_valid_symbol

# The schema version shipped with product v0.1. Pre-1.0 schema is a 0.x.y series
# (§5): reaching "1.0.0" is itself a v1.0 deliverable, so no v0.1 object may claim it.
SCHEMA_VERSION = "0.1.0"


class _Model(BaseModel):
    """Shared config. ``extra="forbid"`` makes a mis-routed carry-through key (§6.1) or a
    typo a construction error rather than silent data in an unread attribute."""

    model_config = ConfigDict(extra="forbid")


# --- §3.3 Geometry -------------------------------------------------------------------


class AtomsBlock(_Model):
    symbols: list[str]  # Chemical symbols, e.g. ["O", "H", "H"]. REQUIRED.
    # Derived from symbols at construction (§3.3); kept explicit for interop. The empty
    # default lets callers omit it (the before-validator fills it); _check() guarantees
    # it ends up populated and in agreement with symbols.
    atomic_numbers: list[int] = Field(default_factory=list)
    positions: ArrayN3  # Cartesian, Å. REQUIRED (§4).
    masses: ArrayN | None = None  # u. None = source specified none.

    @model_validator(mode="before")
    @classmethod
    def _derive_atomic_numbers(cls, data: Any) -> Any:
        # "Derived from symbols at construction" (§3.3): fill when omitted; when supplied
        # (interop / golden fixtures) it is kept and checked for agreement in _check().
        if isinstance(data, dict):
            symbols = data.get("symbols")
            if symbols is not None and data.get("atomic_numbers") is None:
                try:
                    derived = [atomic_number(s) for s in symbols]
                except (KeyError, TypeError):
                    return data  # let _check() raise the precise error
                return {**data, "atomic_numbers": derived}
        return data

    @model_validator(mode="after")
    def _check(self) -> AtomsBlock:
        n = self.positions.shape[0]
        if not (len(self.symbols) == len(self.atomic_numbers) == n):
            raise ValueError(
                "atoms length disagreement: "
                f"len(symbols)={len(self.symbols)}, "
                f"len(atomic_numbers)={len(self.atomic_numbers)}, "
                f"positions.shape[0]={n} must all be equal"
            )
        if self.masses is not None and self.masses.shape[0] != n:
            raise ValueError(f"masses length {self.masses.shape[0]} != atom count {n}")
        for s in self.symbols:
            if not is_valid_symbol(s):
                raise ValueError(f"invalid element symbol {s!r} (use 'X' for unknown, §3.3)")
        expected = [atomic_number(s) for s in self.symbols]
        if list(self.atomic_numbers) != expected:
            raise ValueError(
                f"atomic_numbers {list(self.atomic_numbers)} disagree with symbols "
                f"{self.symbols} (expected {expected})"
            )
        return self


# --- §3.4 Simulation Cell ------------------------------------------------------------


class Cell(_Model):
    lattice_vectors: Array33  # Rows a, b, c in Å, Cartesian. REQUIRED within Cell.
    pbc: tuple[bool, bool, bool]  # Periodicity per lattice direction. REQUIRED within Cell.
    space_group: str | None = None  # Hermann–Mauguin symbol as declared by source; never derived.


# --- §3.6 Dynamics -------------------------------------------------------------------


class Constraint(_Model):
    kind: str  # e.g. "fixed_atoms", "fixed_plane", "fixed_line".
    atom_indices: list[int]  # 0-based indices into this frame's atoms.
    parameters: dict[str, Any] = Field(default_factory=dict)  # Kind-specific; JSON-serializable.

    @model_validator(mode="after")
    def _check_json_serializable(self) -> Constraint:
        # §3.6: parameters is the one place a plain dict could smuggle in a
        # non-serializable value; every other field is JSON-safe via its typed schema.
        try:
            json.dumps(self.parameters)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Constraint.parameters must be JSON-serializable (str/int/float/bool/"
                f"list/dict/None only): {exc}"
            ) from exc
        return self


class Dynamics(_Model):
    velocities: ArrayN3 | None = None  # Å/fs. All-zeros = source states at-rest (§2 rule 3).
    forces: ArrayN3 | None = None  # eV/Å.
    # None = source says nothing; [] = source explicitly declares "no constraints".
    constraints: list[Constraint] | None = None


# --- §3.7 Electronic -----------------------------------------------------------------


class Electronic(_Model):
    total_energy: float | None = None  # eV.
    stress: Array33 | None = None  # eV/Å³, full symmetric tensor, tension-positive (§3.7.1).
    charges: ArrayN | None = None  # e, per-atom net charge, cation-positive (§3.7.1).
    magnetic_moments: ArrayN | None = None  # μB, per-atom, spin-up-positive (§3.7.1).
    total_spin: float | None = None  # Total S (not 2S/Sz), in ħ (§3.7.1).


# --- §3.5 Frame + Trajectory ---------------------------------------------------------


class TrajectoryMetadata(_Model):
    # fs. None = frames exist but source declared no timestep (XDATCAR). The container's
    # single field is an intentional seam for future trajectory-level metadata (§3.5);
    # frame_count is NOT stored — it is CanonicalObject.frame_count (== len(frames)).
    timestep: float | None = None


class Frame(_Model):
    index: int  # 0-based position in the trajectory. REQUIRED.
    time: float | None = None  # fs, absolute simulation time if the source states it.
    atoms: AtomsBlock  # REQUIRED (§3.3).
    cell: Cell | None = None  # §3.4.
    dynamics: Dynamics = Field(default_factory=Dynamics)  # required container, optional contents.
    electronic: Electronic = Field(default_factory=Electronic)  # required container.


# --- §3.8 Simulation Metadata --------------------------------------------------------


class SimulationMetadata(_Model):
    source_code: str | None = None  # Generating software as declared in the file.
    calculator: str | None = None  # Method family, e.g. "DFT".
    xc_functional: str | None = None  # e.g. "PBE", "HSE06".
    pseudopotentials: dict[str, str] | None = None  # element symbol -> potential label.
    thermostat: str | None = None  # e.g. "Nose-Hoover".
    md_ensemble: str | None = None  # e.g. "NVT", "NPT".
    temperature: float | None = None  # K.
    # Format-declared simulation/method metadata with no dedicated field, verbatim (§6.1).
    extra: dict[str, str] = Field(default_factory=dict)


# --- §3.9 Provenance -----------------------------------------------------------------


class ConversionRecord(_Model):
    """One entry in the object's conversion history. Append-only (§3.9)."""

    timestamp: str  # ISO 8601 UTC.
    operation: str  # "parse" | "convert" | "recovery" | "migrate" | "repair".
    source_format: str | None
    target_format: str | None
    tool_version: str
    parser_version: str | None
    assumptions: list[str] = Field(default_factory=list)


class Provenance(_Model):
    source_filename: str | None  # As uploaded (None if constructed programmatically).
    source_format: str  # Sniffed + confirmed format identifier. REQUIRED.
    source_units: dict[str, str] = Field(default_factory=dict)  # e.g. {"positions": "angstrom"}.
    original_coordinate_system: str  # "cartesian" | "fractional" — what the SOURCE used (§4).
    parse_notes: list[str] = Field(default_factory=list)
    history: list[ConversionRecord] = Field(default_factory=list)  # Append-only.


# --- §3.10 User Metadata -------------------------------------------------------------


# A per-atom/per-frame custom value is a sequence whose first dimension is N/F (§3.10, §6
# rule 1): either a numeric ndarray (extXYZ extra columns) OR a length-N/F list of JSON
# scalars (e.g. per-frame free-text comments — the §8.1 / §6.1 carry-through of XYZ comment
# lines). left_to_right union so numeric input becomes an ndarray and only non-numeric
# input (strings) falls through to the list form. See MASTER_SPEC Part 2 §3.10 Rev 1.3.
_PerAtomValue = Annotated[ArrayNx | list[JsonValue], Field(union_mode="left_to_right")]
_PerFrameValue = Annotated[ArrayFx | list[JsonValue], Field(union_mode="left_to_right")]


class UserMetadata(_Model):
    tags: list[str] = Field(default_factory=list)
    annotations: dict[str, str] = Field(default_factory=dict)
    custom_global: dict[str, JsonValue] = Field(default_factory=dict)
    custom_per_atom: dict[str, _PerAtomValue] = Field(default_factory=dict)  # first dim = N.
    custom_per_frame: dict[str, _PerFrameValue] = Field(default_factory=dict)  # first dim = F.


# --- §3.2 Root object ----------------------------------------------------------------


class CanonicalObject(_Model):
    """The single internal representation (§3.2). One instance = one structure or one
    trajectory. A static structure is ``frames`` of length 1 with ``trajectory = None``."""

    schema_version: str = SCHEMA_VERSION  # REQUIRED (§5).
    frames: Annotated[list[Frame], Field(min_length=1)]  # >= 1 (§3.2).
    trajectory: TrajectoryMetadata | None = None
    simulation: SimulationMetadata | None = None
    provenance: Provenance  # REQUIRED — ChemBridge itself always establishes it (§3.9).
    user_metadata: UserMetadata = Field(default_factory=UserMetadata)

    @property
    def frame_count(self) -> int:
        """Number of frames — a computed property, never stored (§3.5). Serialized
        envelopes that show ``frame_count`` render it from here at emit time."""
        return len(self.frames)

    def field_presence(self) -> PresenceMap:
        """Compute the ✓/✗ presence map of this object on demand (§3.11). Never stored;
        derived from the ``None``/populated state of the fields themselves."""
        from chembridge.schema.presence import compute_field_presence

        return compute_field_presence(self)

    @model_validator(mode="after")
    def _check(self) -> CanonicalObject:
        # Constant-N invariant (§3.2): every frame has the same atom count, which is what
        # makes the root-level custom_per_atom arrays (first dim N) well-defined.
        n = self.frames[0].atoms.positions.shape[0]
        for frame in self.frames:
            fn = frame.atoms.positions.shape[0]
            if fn != n:
                raise ValueError(
                    f"constant-atom-count invariant violated (§3.2): frame {frame.index} "
                    f"has {fn} atoms, frame 0 has {n}"
                )
        # Frame indices are their 0-based position in the trajectory (§3.5).
        for position, frame in enumerate(self.frames):
            if frame.index != position:
                raise ValueError(
                    f"frame at position {position} declares index {frame.index}; "
                    "frame.index must equal its 0-based position (§3.5)"
                )
        # Root-level custom per-atom / per-frame values must match N / F (§3.10, §6 rule 1).
        # A value is either a numeric ndarray (first-dim = shape[0]) or a JSON-scalar list
        # (first-dim = len); both are validated against the object's atom / frame count.
        f = len(self.frames)
        for key, val in self.user_metadata.custom_per_atom.items():
            length = val.shape[0] if isinstance(val, np.ndarray) else len(val)
            if length != n:
                raise ValueError(f"custom_per_atom[{key!r}] first dim {length} != atom count {n}")
        for key, val in self.user_metadata.custom_per_frame.items():
            length = val.shape[0] if isinstance(val, np.ndarray) else len(val)
            if length != f:
                raise ValueError(f"custom_per_frame[{key!r}] first dim {length} != frame count {f}")
        return self
