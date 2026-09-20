"""H5MD (HDF5-for-molecular-data) parser (MASTER_SPEC Part 3 §3; v2.0 M74).

Reads one H5MD file — the community HDF5 layout for molecular data — into a Canonical Object via
``h5py``. H5MD is the eighth first-party format and the one that proves the M72/M73 variable-N
engines against a real binary container: a trajectory whose atom count differs per frame is read
natively, each frame carrying its own N (P3), never coerced to a constant-N shape.

**Streaming-first.** ``parse`` is defined as ``materialize(parse_stream(...))`` (as XDATCAR and ASE
traj), so the whole-file and streamed readings are one code path that cannot diverge (D56). ``h5py``
gives random access into the file, so ``parse_stream`` genuinely yields one frame at a time and peak
memory tracks the resident frame, not the frame count.

**The variable-N read mechanism (paired with the exporter, DECISIONS.md D-DEP).** A time-dependent
element is a ``{step, time, value}`` triple. When ``value`` is a per-step variable-length (VLEN)
array — the layout ``exporters.h5md`` writes — each entry is that frame's data with its own particle
dimension, so N is read per frame. A constant-N ``[T, N, D]`` ``value`` reads through the same path
(``value[i]`` is that step's slice regardless of the underlying layout).

**Fields (§4).** ``position``/``species`` → ``atoms``; ``velocity`` → ``dynamics.velocities``;
``force`` → ``dynamics.forces``; ``mass`` → ``atoms.masses`` (u); ``charge`` →
``electronic.charges`` (e); ``box`` → ``cell``; the ``/observables/potential_energy`` series →
``electronic.total_energy`` (eV); every other ``/observables/<name>`` series →
``user_metadata.custom_per_frame['h5md:<name>']``. Absent optional groups launder to absence, never
to zeros or defaults (P3); ``unit`` attributes are honored when present, their absence recorded
rather than assumed (P4), and an unrecognized unit is carried verbatim under a loud warning rather
than silently reinterpreted (P1).

**Torn tails.** A run killed mid-write leaves ``step``/``time`` preallocated longer than the flushed
``value``. That is refused by default (``H5MD_TRUNCATED`` with the shared
``truncate_at_last_valid_frame`` hint) and recovered — via ``parse_recover`` — to the complete-frame
prefix, the dropped tail recorded as a warning so it is never silent (the xdatcar/outcar/qe pattern,
D166).
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO

import h5py
import numpy as np

from xtalate import __version__
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    TrajectoryMetadata,
)
from xtalate.schema.elements import symbol_for
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    FrameStream,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
    StreamFrame,
    StreamHeader,
    materialize,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

FORMAT_ID = "h5md"
# HDF5 files begin with this 8-byte signature (see the HDF5 spec); used only for sniffing.
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
_PARSER_VERSION = f"{FORMAT_ID}-parser {__version__} (h5py {h5py.__version__})"
_TRUNCATE_HINT = "truncate_at_last_valid_frame"

# Recognized source unit (normalized: lowercased, stripped) -> multiplicative factor to the
# canonical unit. The canonical spelling is 1.0. An unrecognized unit is not in the table — it is
# carried verbatim under a warning, never guessed (P1). Conversion factors are the CODATA/IUPAC
# constants; only physically common H5MD units are listed (this is not a unit-algebra engine).
_LENGTH: dict[str, float] = {
    "angstrom": 1.0,
    "a": 1.0,
    "aa": 1.0,
    "ang": 1.0,
    "nm": 10.0,
    "pm": 0.01,
}
_VELOCITY: dict[str, float] = {
    "angstrom/fs": 1.0,
    "a/fs": 1.0,
    "angstrom/ps": 1e-3,
    "nm/ps": 1e-2,
}
_FORCE: dict[str, float] = {"ev/angstrom": 1.0, "ev/a": 1.0}
_MASS: dict[str, float] = {"u": 1.0, "amu": 1.0, "da": 1.0, "dalton": 1.0, "g/mol": 1.0}
_CHARGE: dict[str, float] = {"e": 1.0, "elementary_charge": 1.0}
_ENERGY: dict[str, float] = {
    "ev": 1.0,
    "hartree": 27.211386245988,
    "ha": 27.211386245988,
    "ry": 13.605693122994,
    "rydberg": 13.605693122994,
    "kj/mol": 0.010364269574,
    "kcal/mol": 0.043364104242,
}
# quantity -> (canonical unit spelling, recognized-unit factor table).
_UNITS: dict[str, tuple[str, dict[str, float]]] = {
    "positions": ("Angstrom", _LENGTH),
    "velocities": ("Angstrom/fs", _VELOCITY),
    "forces": ("eV/Angstrom", _FORCE),
    "masses": ("u", _MASS),
    "charges": ("e", _CHARGE),
    "total_energy": ("eV", _ENERGY),
}


def _error(
    code: str, message: str, *, location: str | None = None, hint: str | None = None
) -> ParseError:
    return ParseError(
        [
            ParseIssue(
                severity="error", code=code, message=message, location=location, recovery_hint=hint
            )
        ]
    )


def _unit_of(dataset: h5py.Dataset) -> str | None:
    """The ``unit`` attribute on a dataset, decoded, or ``None`` when the source declared none."""
    raw = dataset.attrs.get("unit")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


class _Element:
    """A resolved H5MD element — time-dependent (``{step,time,value}``) or fixed-in-time (a bare
    dataset). ``at(i)`` returns frame ``i``'s array; a fixed element returns the same array for
    every frame. ``length`` is the flushed step count for a time-dependent element (``None`` when
    fixed), and ``step_len`` the declared step count (from ``step``) used for torn-tail detection.
    """

    def __init__(self, node: h5py.Group | h5py.Dataset) -> None:
        if isinstance(node, h5py.Group):
            self.kind = "timedep"
            self._value: h5py.Dataset = node["value"]
            self.length: int | None = int(self._value.shape[0])
            self.step_len: int | None = (
                int(node["step"].shape[0]) if "step" in node else self.length
            )
            self.unit = _unit_of(self._value)
        else:
            self.kind = "fixed"
            self._fixed = np.asarray(node)
            self.length = None
            self.step_len = None
            self.unit = _unit_of(node)

    def at(self, index: int) -> np.ndarray:
        if self.kind == "fixed":
            return np.asarray(self._fixed)
        return np.asarray(self._value[index])


def _resolve(group: h5py.Group, name: str) -> _Element | None:
    node = group.get(name)
    if node is None:
        return None
    return _Element(node)


def _pbc_from_boundary(boundary: h5py.Dataset | None) -> tuple[bool, bool, bool]:
    if boundary is None:
        return (True, True, True)
    flags = [_is_periodic(b) for b in np.asarray(boundary).reshape(-1)[:3]]
    while len(flags) < 3:
        flags.append(True)
    return (flags[0], flags[1], flags[2])


def _edges_to_lattice(arr: np.ndarray) -> np.ndarray:
    """H5MD ``box/edges`` -> a 3×3 lattice: a full matrix as-is, a 3-vector as an orthorhombic
    diagonal (the H5MD shorthand for a cuboid cell)."""
    arr = np.asarray(arr, dtype=np.float64)
    if arr.shape == (3, 3):
        return arr
    if arr.shape == (3,):
        return np.diag(arr)
    raise _error(
        "H5MD_MALFORMED_STRUCTURE",
        f"box/edges has shape {arr.shape}; expected (3, 3) or (3,)",
        location="box/edges",
    )


class _BoxReader:
    """Reads the cell for a given frame from a ``box`` group — fixed-in-time or time-dependent."""

    def __init__(self, edges: _Element, pbc: tuple[bool, bool, bool]) -> None:
        self._edges = edges
        self._pbc = pbc

    def at(self, index: int) -> Cell:
        return Cell(lattice_vectors=_edges_to_lattice(self._edges.at(index)), pbc=self._pbc)


def _resolve_box(group: h5py.Group) -> _BoxReader | None:
    box = group.get("box")
    if box is None or "edges" not in box:
        return None
    edges = _Element(box["edges"])
    return _BoxReader(edges, _pbc_from_boundary(box.get("boundary")))


def _resolve_unit(
    quantity: str,
    unit: str | None,
    *,
    notes: list[str],
    source_units: dict[str, str],
    issues: list[ParseIssue],
) -> float:
    """Resolve one quantity's ``unit`` attribute into a factor-to-canonical, recording the outcome.

    Absent unit -> factor 1.0, a note that none was assumed (P4), nothing recorded as the source
    unit. Recognized unit -> its factor, recorded as the source unit, a conversion note when the
    factor is not 1. Unrecognized unit -> factor 1.0 (verbatim) under a loud warning (P1), recorded
    as the source unit so the report shows exactly what the file declared.
    """
    canon, table = _UNITS[quantity]
    if unit is None:
        notes.append(
            f"{quantity}: the source declared no unit; values read verbatim as {canon} with no "
            "assumed conversion (P4)."
        )
        return 1.0
    source_units[quantity] = unit
    factor = table.get(unit.strip().lower())
    if factor is None:
        issues.append(
            ParseIssue(
                severity="warning",
                code="H5MD_UNKNOWN_UNIT",
                message=(
                    f"{quantity} unit {unit!r} is not recognized; values read verbatim without "
                    "conversion — verify them before trusting the output (P1)"
                ),
                location=quantity,
            )
        )
        return 1.0
    if factor != 1.0:
        notes.append(f"{quantity}: converted from {unit} to {canon} (×{factor}).")
    return factor


class H5MDParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "H5MD"
    version = "0.1.0"
    file_extensions = (".h5", ".h5md", ".hdf5")

    def sniff(self, head: bytes, filename: str | None) -> float:
        if head.startswith(_HDF5_MAGIC):
            # HDF5 is a binary container; H5MD is one layout within it. Probe the head for the
            # /h5md + /particles groups that make it H5MD. A partial head can fail to open (the
            # superblock points past it) — then the magic alone is a weak positive, not a claim.
            try:
                with h5py.File(BytesIO(head), "r") as f:
                    if "h5md" in f and "particles" in f:
                        return 0.95
                    return 0.0  # a generic HDF5 file that is not H5MD
            except Exception:  # noqa: BLE001 - a truncated head; fall back to the magic hint
                return 0.5
        if filename is not None and filename.endswith((".h5md", ".h5", ".hdf5")):
            return 0.2
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56)."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
        recovery_context: Mapping[str, object] | None = None,
    ) -> ParseResult:
        """Recover a torn H5MD trajectory by keeping the complete-frame prefix
        (``truncate_at_last_valid_frame`` → ``truncate``, Part 4 §3.3). Re-reads through the same
        streaming path in truncate mode, so the kept prefix is read by exactly the code that reads
        an intact file, and the dropped tail is recorded as a warning (P1)."""
        if hint != _TRUNCATE_HINT:
            raise NotImplementedError(f"h5md parse_recover does not handle hint {hint!r}")
        if choice != "truncate":
            raise NotImplementedError(
                f"h5md parse_recover applies only the 'truncate' choice (got {choice!r})"
            )
        frame_stream = self.parse_stream(stream, filename=filename, truncate=True)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def parse_stream(
        self, stream: BinaryIO, *, filename: str | None, truncate: bool = False
    ) -> FrameStream:
        try:
            f = h5py.File(stream, "r")
        except Exception as exc:  # h5py raises the OSError family; normalise to the §5 contract
            raise _error(
                "H5MD_MALFORMED_STRUCTURE", f"could not open the file as HDF5: {exc}"
            ) from exc

        try:
            group = self._single_particle_group(f)
            position = _resolve(group, "position")
            species = _resolve(group, "species")
            if position is None or species is None:
                missing = "position" if position is None else "species"
                raise _error(
                    "H5MD_MISSING_REQUIRED_GROUP",
                    f"particle group has no /{missing} element (not a readable H5MD trajectory)",
                )
            velocity = _resolve(group, "velocity")
            force = _resolve(group, "force")
            mass = _resolve(group, "mass")
            charge = _resolve(group, "charge")
            box = _resolve_box(group)

            issues: list[ParseIssue] = []
            n_steps = self._frame_count(position, truncate=truncate, issues_sink=issues)

            notes: list[str] = [
                f"read via h5py {h5py.__version__}; H5MD per-step elements read with each frame's "
                "own atom count (P3)."
            ]
            source_units: dict[str, str] = {}
            factors = {
                "positions": _resolve_unit(
                    "positions",
                    position.unit,
                    notes=notes,
                    source_units=source_units,
                    issues=issues,
                ),
                "velocities": _resolve_unit(
                    "velocities",
                    velocity.unit,
                    notes=notes,
                    source_units=source_units,
                    issues=issues,
                )
                if velocity
                else 1.0,
                "forces": _resolve_unit(
                    "forces", force.unit, notes=notes, source_units=source_units, issues=issues
                )
                if force
                else 1.0,
                "masses": _resolve_unit(
                    "masses", mass.unit, notes=notes, source_units=source_units, issues=issues
                )
                if mass
                else 1.0,
                "charges": _resolve_unit(
                    "charges", charge.unit, notes=notes, source_units=source_units, issues=issues
                )
                if charge
                else 1.0,
            }
            pe_series, other_obs, pe_factor = self._resolve_observables(
                f, notes=notes, source_units=source_units, issues=issues
            )
            creator = self._creator_note(f)
            if creator is not None:
                notes.append(creator)

            provenance = build_provenance(
                format_id=FORMAT_ID,
                filename=filename,
                original_coordinate_system="cartesian",
                source_units=source_units,
                parse_notes=notes,
                parser_version=_PARSER_VERSION,
            )
        except BaseException:
            f.close()
            raise

        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            trajectory=TrajectoryMetadata(timestep=None),
        )

        def _frames() -> Iterator[StreamFrame]:
            try:
                for index in range(n_steps):
                    frame = self._build_frame(
                        index,
                        position=position,
                        species=species,
                        velocity=velocity,
                        force=force,
                        mass=mass,
                        charge=charge,
                        box=box,
                        factors=factors,
                        pe_series=pe_series,
                        pe_factor=pe_factor,
                    )
                    per_frame = {
                        f"h5md:{name}": float(elem.at(index).reshape(-1)[0])
                        for name, elem in other_obs.items()
                    }
                    yield StreamFrame(frame=frame, per_frame_custom=per_frame)
            finally:
                f.close()

        return FrameStream(header, _frames(), issues=issues)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _frame_count(
        position: _Element, *, truncate: bool, issues_sink: list[ParseIssue] | None
    ) -> int:
        """The number of complete frames, refusing a torn tail unless recovering.

        A run killed mid-write leaves ``step`` preallocated longer than the flushed ``value``. That
        is a recoverable torn tail: refused by default (``H5MD_TRUNCATED`` + the truncate hint),
        kept-as-prefix under ``truncate`` with a warning so the dropped tail is never silent (P1).
        """
        flushed = position.length if position.length is not None else 1
        declared = position.step_len
        if declared is not None and flushed < declared:
            if not truncate:
                raise _error(
                    "H5MD_TRUNCATED",
                    f"position/value holds {flushed} frame(s) but /step declares {declared}: the "
                    "trajectory was truncated mid-write",
                    location=f"frame {flushed}",
                    hint=_TRUNCATE_HINT,
                )
            if issues_sink is not None:
                issues_sink.append(
                    ParseIssue(
                        severity="warning",
                        code="H5MD_TRUNCATED",
                        message=(
                            f"kept the {flushed} complete frame(s) and discarded the truncated "
                            f"tail (/step declared {declared})"
                        ),
                        location=f"frame {flushed}",
                    )
                )
        return flushed

    @staticmethod
    def _build_frame(
        index: int,
        *,
        position: _Element,
        species: _Element,
        velocity: _Element | None,
        force: _Element | None,
        mass: _Element | None,
        charge: _Element | None,
        box: _BoxReader | None,
        factors: dict[str, float],
        pe_series: _Element | None,
        pe_factor: float,
    ) -> Frame:
        atomic_numbers = species.at(index).reshape(-1)
        symbols = [symbol_for(int(z)) for z in atomic_numbers]
        pos = np.asarray(position.at(index), dtype=np.float64).reshape(-1, 3) * factors["positions"]
        n = pos.shape[0]
        masses = None
        if mass is not None:
            arr = np.asarray(mass.at(index), dtype=np.float64).reshape(-1) * factors["masses"]
            masses = arr if arr.shape[0] == n else None
        atoms = AtomsBlock(symbols=symbols, positions=pos, masses=masses)

        dynamics = Dynamics(
            velocities=(
                np.asarray(velocity.at(index), dtype=np.float64).reshape(-1, 3)
                * factors["velocities"]
                if velocity is not None
                else None
            ),
            forces=(
                np.asarray(force.at(index), dtype=np.float64).reshape(-1, 3) * factors["forces"]
                if force is not None
                else None
            ),
        )
        charges = None
        if charge is not None:
            arr = np.asarray(charge.at(index), dtype=np.float64).reshape(-1) * factors["charges"]
            charges = arr if arr.shape[0] == n else None
        total_energy = (
            float(pe_series.at(index).reshape(-1)[0]) * pe_factor if pe_series is not None else None
        )
        electronic = Electronic(total_energy=total_energy, charges=charges)

        try:
            return Frame(
                index=index,
                atoms=atoms,
                cell=box.at(index) if box is not None else None,
                dynamics=dynamics,
                electronic=electronic,
            )
        except ValueError as exc:  # keep pydantic shape errors inside the §5 contract
            raise _error(
                "H5MD_INCONSISTENT_FRAME",
                f"frame {index} is internally inconsistent: {exc}",
                location=f"frame {index}",
            ) from exc

    def _resolve_observables(
        self,
        f: h5py.File,
        *,
        notes: list[str],
        source_units: dict[str, str],
        issues: list[ParseIssue],
    ) -> tuple[_Element | None, dict[str, _Element], float]:
        """Split ``/observables`` into ``potential_energy`` (→ ``total_energy``) and everything else
        (→ ``custom_per_frame['h5md:<name>']``). Returns the energy element, the other-observable
        map, and the energy unit factor."""
        obs = f.get("observables")
        if obs is None:
            return None, {}, 1.0
        pe: _Element | None = None
        pe_factor = 1.0
        other: dict[str, _Element] = {}
        for name in obs:
            elem = _Element(obs[name])
            if name == "potential_energy":
                pe = elem
                pe_factor = _resolve_unit(
                    "total_energy", elem.unit, notes=notes, source_units=source_units, issues=issues
                )
            else:
                other[name] = elem
        return pe, other, pe_factor

    @staticmethod
    def _creator_note(f: h5py.File) -> str | None:
        """Record ``/h5md/creator`` (the program that wrote the file) as a provenance note — not as
        the simulation ``source_code``, which H5MD does not promise the creator to be."""
        h5md = f.get("h5md")
        if h5md is None or "creator" not in h5md:
            return None
        attrs = h5md["creator"].attrs

        def _text(key: str) -> str | None:
            raw = attrs.get(key)
            if raw is None:
                return None
            return raw.decode() if isinstance(raw, bytes) else str(raw)

        name = _text("name")
        if name is None:
            return None
        version = _text("version")
        return f"H5MD file created by {name}" + (f" {version}" if version else "")

    @staticmethod
    def _single_particle_group(f: h5py.File) -> h5py.Group:
        """Return the one ``/particles/<grp>`` group, or refuse. A multi-group file is refused
        rather than silently reading one and dropping the rest (D-MULTIGROUP)."""
        particles = f.get("particles")
        if particles is None:
            raise _error(
                "H5MD_MISSING_REQUIRED_GROUP",
                "file has no /particles group (not an H5MD trajectory)",
            )
        names = list(particles.keys())
        if len(names) > 1:
            raise _error(
                "H5MD_MULTIPLE_PARTICLE_GROUPS",
                f"file declares {len(names)} particle groups ({', '.join(sorted(names))}); Xtalate "
                "reads one structure per file and will not silently choose or merge them",
            )
        return particles[names[0]]

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "atoms.masses": full,
                "dynamics.velocities": full,
                "dynamics.forces": full,
                "electronic.charges": full,
                "electronic.total_energy": FieldCapability(
                    level=CapabilityLevel.FULL, notes="From /observables/potential_energy."
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="From box/edges (fixed-in-time or per step).",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL, notes="From box/boundary."
                ),
            },
            max_frames=None,
            supports_variable_atom_count=True,
            required_fields=[],
            native_coordinate_system="cartesian",
        )


def _is_periodic(raw: object) -> bool:
    """H5MD ``boundary`` entry → periodic? Accepts bytes/str ``"periodic"``/``"none"``."""
    if isinstance(raw, bytes):
        raw = raw.decode()
    return str(raw) == "periodic"


def make_h5md_parser() -> H5MDParser:
    return H5MDParser()
